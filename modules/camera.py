"""Captura y visualización de video desde una webcam disponible."""

import logging
import os
import threading
import time
from typing import Optional

import cv2

from config import (
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_MAX_INDEX,
    CAMERA_MIRROR,
    CAMERA_RETRY_SECONDS,
    CAMERA_WIDTH,
    CAMERA_WINDOW_NAME,
)
from core.event_bus import EventBus


logger = logging.getLogger(__name__)


class CameraNotFoundError(RuntimeError):
    """Indica que no se encontró ninguna cámara utilizable."""


class CameraModule:
    """Detecta una webcam y muestra su imagen en tiempo real."""

    def __init__(
        self,
        width: int = CAMERA_WIDTH,
        height: int = CAMERA_HEIGHT,
        target_fps: int = CAMERA_FPS,
        mirror: bool = CAMERA_MIRROR,
        max_camera_index: int = CAMERA_MAX_INDEX,
        window_name: str = CAMERA_WINDOW_NAME,
        event_bus: Optional[EventBus] = None,
        show_window: bool = True,
        retry_seconds: float = CAMERA_RETRY_SECONDS,
    ) -> None:
        self.width = width
        self.height = height
        self.target_fps = target_fps
        self.mirror = mirror
        self.max_camera_index = max_camera_index
        self.window_name = window_name
        self._event_bus = event_bus
        self._show_window = bool(show_window)
        self._retry_seconds = max(1.0, float(retry_seconds))
        self._capture: Optional[cv2.VideoCapture] = None
        self._camera_index: Optional[int] = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_error: Optional[Exception] = None

    @property
    def last_error(self) -> Optional[Exception]:
        return self._last_error

    def start_background(self) -> None:
        """Inicia la captura sin bloquear el hilo de la interfaz."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._last_error = None
        self._thread = threading.Thread(
            target=self._run_background,
            name="room-os-camera",
            daemon=True,
        )
        self._thread.start()

    def _run_background(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run()
                return
            except Exception as error:
                self._last_error = error
                logger.error("Cámara no disponible: %s", error)
                if self._event_bus is not None:
                    self._event_bus.publish(
                        "camera.error",
                        {
                            "error": str(error),
                            "retry_seconds": self._retry_seconds,
                        },
                    )
                if self._stop_event.wait(self._retry_seconds):
                    return
                logger.info("Reintentando conexión con la cámara")

    def _create_captures(self, index: int):
        """Prueba los backends compatibles sin depender de uno solo."""
        if os.name == "nt":
            for backend in (cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY):
                yield cv2.VideoCapture(index, backend)
            return
        yield cv2.VideoCapture(index)

    def _find_camera(self) -> cv2.VideoCapture:
        """Devuelve la primera cámara que pueda entregar una imagen."""
        logger.info(
            "Buscando una cámara entre los índices 0 y %d",
            self.max_camera_index,
        )

        for index in range(self.max_camera_index + 1):
            for capture in self._create_captures(index):
                if capture.isOpened():
                    success, _ = capture.read()
                    if success:
                        self._camera_index = index
                        logger.info("Cámara detectada en el índice %d", index)
                        return capture
                capture.release()

        raise CameraNotFoundError(
            "No se encontró una cámara disponible. Comprueba que esté conectada, "
            "que Windows permita el acceso y que ninguna otra aplicación la esté usando."
        )

    def _apply_settings(self) -> None:
        """Solicita la resolución y los FPS definidos en config.py."""
        if self._capture is None:
            return

        self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self._capture.set(cv2.CAP_PROP_FPS, self.target_fps)

        actual_width = int(self._capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_height = int(self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = self._capture.get(cv2.CAP_PROP_FPS)
        logger.info(
            "Configuración activa de cámara: %dx%d a %.1f FPS",
            actual_width,
            actual_height,
            actual_fps,
        )

        if actual_width != self.width or actual_height != self.height:
            logger.warning(
                "La cámara no aceptó la resolución solicitada de %dx%d",
                self.width,
                self.height,
            )

    def run(self) -> None:
        """Muestra el video hasta que el usuario presione Q."""
        self._capture = self._find_camera()
        self._apply_settings()
        logger.info("Vista de cámara iniciada. Presiona Q para cerrar")

        displayed_fps = 0.0
        previous_time = time.perf_counter()

        try:
            while not self._stop_event.is_set():
                success, frame = self._capture.read()
                if not success:
                    raise RuntimeError(
                        "Se perdió la señal de la cámara durante la captura."
                    )

                if self.mirror:
                    frame = cv2.flip(frame, 1)

                current_time = time.perf_counter()
                elapsed = current_time - previous_time
                previous_time = current_time
                instant_fps = 1.0 / elapsed if elapsed > 0 else 0.0
                displayed_fps = (
                    instant_fps
                    if displayed_fps == 0.0
                    else (0.9 * displayed_fps) + (0.1 * instant_fps)
                )

                if self._event_bus is not None:
                    self._event_bus.publish(
                        "camera.frame",
                        {
                            "frame": frame,
                            "timestamp": current_time,
                            "fps": displayed_fps,
                        },
                    )

                if self._show_window:
                    cv2.putText(
                        frame, f"FPS: {displayed_fps:.1f}", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2,
                        cv2.LINE_AA,
                    )
                    cv2.imshow(self.window_name, frame)
                    key = cv2.waitKey(1) & 0xFF
                    if key in (ord("q"), ord("Q")):
                        break
        finally:
            self._release_capture()

    def _release_capture(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
            logger.info("Cámara liberada")
        if self._show_window:
            cv2.destroyAllWindows()

    def close(self) -> None:
        """Libera la cámara y cierra las ventanas de OpenCV."""
        self._stop_event.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=3.0)
            self._thread = None
        self._release_capture()
