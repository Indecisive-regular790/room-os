"""Seguimiento asíncrono de manos mediante MediaPipe."""

import logging
import queue
import threading
import time
from typing import Any, Optional

import cv2
import mediapipe as mp

from config import (
    CAMERA_MIRROR,
    HAND_TRACKING_DRAW,
    HAND_TRACKING_FACE_BOX_MARGIN,
    HAND_TRACKING_FACE_BOX_MAX_AGE_SECONDS,
    HAND_TRACKING_FACE_EXCLUSION_ENABLED,
    HAND_TRACKING_FACE_MIN_LANDMARKS,
    HAND_TRACKING_MAX_HANDS,
    HAND_TRACKING_MIN_DETECTION_CONFIDENCE,
    HAND_TRACKING_MIN_TRACKING_CONFIDENCE,
)
from core.event_bus import EventBus


logger = logging.getLogger(__name__)


class HandTrackingModule:
    """Procesa los frames de cámara y publica datos de una o dos manos."""

    def __init__(
        self,
        event_bus: EventBus,
        draw_landmarks: bool = HAND_TRACKING_DRAW,
        max_hands: int = HAND_TRACKING_MAX_HANDS,
        min_detection_confidence: float = HAND_TRACKING_MIN_DETECTION_CONFIDENCE,
        min_tracking_confidence: float = HAND_TRACKING_MIN_TRACKING_CONFIDENCE,
        input_is_mirrored: bool = CAMERA_MIRROR,
        exclude_face_regions: bool = HAND_TRACKING_FACE_EXCLUSION_ENABLED,
    ) -> None:
        self._event_bus = event_bus
        self._draw_landmarks_enabled = draw_landmarks
        self._max_hands = max(1, min(max_hands, 2))
        self._min_detection_confidence = min_detection_confidence
        self._min_tracking_confidence = min_tracking_confidence
        self._input_is_mirrored = input_is_mirrored
        self._exclude_face_regions = bool(exclude_face_regions)

        self._frame_queue: queue.Queue[Optional[tuple[Any, float]]] = queue.Queue(
            maxsize=1
        )
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._results_lock = threading.Lock()
        self._latest_hands: list[dict[str, Any]] = []
        self._hands_visible = False
        self._face_regions_lock = threading.Lock()
        self._latest_face_regions: list[dict[str, float]] = []
        self._face_regions_timestamp = float("-inf")

        self._connections = tuple(mp.solutions.hands.HAND_CONNECTIONS)

    def start(self) -> None:
        """Suscribe el módulo e inicia el procesamiento en segundo plano."""
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._event_bus.subscribe("camera.frame", self._on_camera_frame)
        self._event_bus.subscribe("presence.faces", self._on_face_regions)
        self._thread = threading.Thread(
            target=self._processing_loop,
            name="room-os-hand-tracking",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Seguimiento de manos iniciado (máximo: %d, dibujo: %s)",
            self._max_hands,
            "activo" if self._draw_landmarks_enabled else "inactivo",
        )

    def _on_camera_frame(self, event_data: Any) -> None:
        """Recibe un frame, dibuja el último resultado y agenda su análisis."""
        if not isinstance(event_data, dict):
            return

        frame = event_data.get("frame")
        if frame is None:
            return

        timestamp = float(event_data.get("timestamp", time.perf_counter()))
        frame_for_processing = frame.copy()
        self._enqueue_latest_frame(frame_for_processing, timestamp)

        if self._draw_landmarks_enabled:
            with self._results_lock:
                hands = tuple(self._latest_hands)
            self._draw_hands(frame, hands)

    def set_draw_enabled(self, enabled: bool) -> None:
        self._draw_landmarks_enabled = bool(enabled)

    def _enqueue_latest_frame(self, frame: Any, timestamp: float) -> None:
        """Encola sin esperar y descarta trabajo antiguo si el worker está ocupado."""
        item = (frame, timestamp)
        try:
            self._frame_queue.put_nowait(item)
            return
        except queue.Full:
            pass

        try:
            self._frame_queue.get_nowait()
        except queue.Empty:
            pass

        try:
            self._frame_queue.put_nowait(item)
        except queue.Full:
            pass

    def _processing_loop(self) -> None:
        """Mantiene MediaPipe fuera del hilo de captura de cámara."""
        previous_processed_at: Optional[float] = None
        displayed_fps = 0.0

        try:
            with mp.solutions.hands.Hands(
                static_image_mode=False,
                max_num_hands=self._max_hands,
                min_detection_confidence=self._min_detection_confidence,
                min_tracking_confidence=self._min_tracking_confidence,
            ) as hands_model:
                while not self._stop_event.is_set():
                    try:
                        item = self._frame_queue.get(timeout=0.1)
                    except queue.Empty:
                        continue

                    if item is None:
                        break

                    frame, timestamp = item
                    hand_data = self._process_frame(hands_model, frame, timestamp)

                    processed_at = time.perf_counter()
                    if previous_processed_at is not None:
                        elapsed = processed_at - previous_processed_at
                        instant_fps = 1.0 / elapsed if elapsed > 0 else 0.0
                        displayed_fps = (
                            instant_fps
                            if displayed_fps == 0.0
                            else (0.9 * displayed_fps) + (0.1 * instant_fps)
                        )
                    previous_processed_at = processed_at

                    self._update_results_and_events(
                        hand_data,
                        timestamp,
                        displayed_fps,
                    )
        except Exception:
            logger.exception("El seguimiento de manos se detuvo por un error")

    def _process_frame(
        self,
        hands_model: Any,
        frame: Any,
        timestamp: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        """Detecta manos y convierte sus puntos a coordenadas útiles."""
        frame_height, frame_width = frame.shape[:2]
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb_frame.flags.writeable = False
        results = hands_model.process(rgb_frame)

        detected_hands: list[dict[str, Any]] = []
        landmarks_list = results.multi_hand_landmarks or []
        handedness_list = results.multi_handedness or []

        for hand_index, hand_landmarks in enumerate(landmarks_list):
            label = "Unknown"
            score = 0.0
            if hand_index < len(handedness_list):
                classification = handedness_list[hand_index].classification[0]
                label = self._correct_handedness(classification.label)
                score = float(classification.score)

            landmarks = []
            for landmark_id, landmark in enumerate(hand_landmarks.landmark):
                pixel_x = self._normalized_to_pixel(landmark.x, frame_width)
                pixel_y = self._normalized_to_pixel(landmark.y, frame_height)
                landmarks.append(
                    {
                        "id": landmark_id,
                        "normalized": {
                            "x": float(landmark.x),
                            "y": float(landmark.y),
                            "z": float(landmark.z),
                        },
                        "pixel": {
                            "x": pixel_x,
                            "y": pixel_y,
                        },
                    }
                )

            if self._is_inside_recent_face(landmarks, timestamp):
                logger.debug(
                    "Detección de mano descartada por coincidir con un rostro"
                )
                self._event_bus.publish(
                    "hand.rejected",
                    {
                        "timestamp": timestamp,
                        "reason": "inside_face",
                        "handedness": label,
                        "confidence": score,
                    },
                )
                continue

            detected_hands.append(
                {
                    "handedness": label,
                    "confidence": score,
                    "landmarks": landmarks,
                }
            )

        return detected_hands

    def _on_face_regions(self, event_data: Any) -> None:
        if not isinstance(event_data, dict):
            return
        boxes = []
        for raw_box in event_data.get("bounding_boxes", []):
            if not isinstance(raw_box, dict):
                continue
            try:
                box = {
                    key: float(raw_box[key])
                    for key in ("x", "y", "width", "height")
                }
            except (KeyError, TypeError, ValueError):
                continue
            if box["width"] > 0 and box["height"] > 0:
                boxes.append(box)
        timestamp = float(event_data.get("timestamp", time.perf_counter()))
        with self._face_regions_lock:
            self._latest_face_regions = boxes
            self._face_regions_timestamp = timestamp

    def _is_inside_recent_face(
        self,
        landmarks: list[dict[str, Any]],
        timestamp: Optional[float],
    ) -> bool:
        if not self._exclude_face_regions or not landmarks:
            return False
        current_time = time.perf_counter() if timestamp is None else float(timestamp)
        with self._face_regions_lock:
            age = current_time - self._face_regions_timestamp
            boxes = tuple(self._latest_face_regions)
        if age < 0 or age > HAND_TRACKING_FACE_BOX_MAX_AGE_SECONDS:
            return False

        for box in boxes:
            margin_x = box["width"] * HAND_TRACKING_FACE_BOX_MARGIN
            margin_y = box["height"] * HAND_TRACKING_FACE_BOX_MARGIN
            left = box["x"] - margin_x
            right = box["x"] + box["width"] + margin_x
            top = box["y"] - margin_y
            bottom = box["y"] + box["height"] + margin_y
            inside = sum(
                left <= float(point["normalized"]["x"]) <= right
                and top <= float(point["normalized"]["y"]) <= bottom
                for point in landmarks
            )
            if inside >= HAND_TRACKING_FACE_MIN_LANDMARKS:
                return True
        return False

    def _correct_handedness(self, label: str) -> str:
        """Ajusta la etiqueta según la orientación del frame de entrada."""
        if self._input_is_mirrored:
            return label
        if label == "Left":
            return "Right"
        if label == "Right":
            return "Left"
        return label

    @staticmethod
    def _normalized_to_pixel(value: float, dimension: int) -> int:
        """Convierte una coordenada normalizada a un píxel dentro del frame."""
        clamped = min(max(float(value), 0.0), 1.0)
        return min(int(clamped * dimension), max(dimension - 1, 0))

    def _update_results_and_events(
        self,
        hands: list[dict[str, Any]],
        timestamp: float,
        processing_fps: float,
    ) -> None:
        """Actualiza la visualización y publica detección o pérdida."""
        with self._results_lock:
            self._latest_hands = hands

        if hands:
            self._hands_visible = True
            self._event_bus.publish(
                "hand.detected",
                {
                    "timestamp": timestamp,
                    "processing_fps": processing_fps,
                    "hands": hands,
                },
            )
        elif self._hands_visible:
            self._hands_visible = False
            self._event_bus.publish(
                "hand.lost",
                {
                    "timestamp": timestamp,
                    "processing_fps": processing_fps,
                },
            )

    def _draw_hands(
        self,
        frame: Any,
        hands: tuple[dict[str, Any], ...],
    ) -> None:
        """Dibuja los 21 puntos, conexiones y lateralidad de cada mano."""
        frame_height, frame_width = frame.shape[:2]

        for hand in hands:
            points = []
            for landmark in hand["landmarks"]:
                normalized = landmark["normalized"]
                points.append(
                    (
                        self._normalized_to_pixel(normalized["x"], frame_width),
                        self._normalized_to_pixel(normalized["y"], frame_height),
                    )
                )

            for start_id, end_id in self._connections:
                cv2.line(frame, points[start_id], points[end_id], (0, 200, 255), 2)

            for point in points:
                cv2.circle(frame, point, 4, (0, 255, 0), cv2.FILLED)
                cv2.circle(frame, point, 6, (0, 0, 0), 1)

            if points:
                label = hand["handedness"]
                confidence = hand["confidence"]
                label_y = max(points[0][1] - 20, 25)
                cv2.putText(
                    frame,
                    f"{label} {confidence:.2f}",
                    (points[0][0], label_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (255, 255, 255),
                    2,
                    cv2.LINE_AA,
                )

    def close(self) -> None:
        """Desuscribe el módulo y termina su worker de forma segura."""
        self._event_bus.unsubscribe("camera.frame", self._on_camera_frame)
        self._event_bus.unsubscribe("presence.faces", self._on_face_regions)
        self._stop_event.set()

        try:
            self._frame_queue.put_nowait(None)
        except queue.Full:
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._frame_queue.put_nowait(None)
            except queue.Full:
                pass

        if self._thread is not None:
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("El worker de seguimiento no terminó a tiempo")
            self._thread = None

        with self._results_lock:
            self._latest_hands = []
        self._hands_visible = False
        with self._face_regions_lock:
            self._latest_face_regions = []
        logger.info("Seguimiento de manos cerrado")
