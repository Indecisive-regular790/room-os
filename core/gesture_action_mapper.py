"""Mapeo no bloqueante entre gestos confirmados y acciones registradas."""

import logging
import queue
import threading
import time
from collections.abc import Mapping
from typing import Any, Optional

from config import (
    GESTURE_ACTION_COOLDOWN_SECONDS,
    GESTURE_ACTION_MAP,
    GESTURE_ACTION_STARTUP_GRACE_SECONDS,
    GESTURE_ACTIONS_ENABLED,
)
from core.action_engine import ACTION_EXECUTE_EVENT
from core.event_bus import EventBus


logger = logging.getLogger(__name__)


class GestureActionMapper:
    """Convierte gestos estables en solicitudes al Action Engine."""

    def __init__(
        self,
        event_bus: EventBus,
        gesture_map: Optional[Mapping[str, str]] = None,
        enabled: bool = GESTURE_ACTIONS_ENABLED,
        cooldown_seconds: float = GESTURE_ACTION_COOLDOWN_SECONDS,
        startup_grace_seconds: float = GESTURE_ACTION_STARTUP_GRACE_SECONDS,
    ) -> None:
        self._event_bus = event_bus
        self._gesture_map = dict(
            GESTURE_ACTION_MAP if gesture_map is None else gesture_map
        )
        self._enabled = bool(enabled)
        self._cooldown_seconds = max(0.0, float(cooldown_seconds))
        self._startup_grace_seconds = max(0.0, float(startup_grace_seconds))
        self._ready_at = 0.0
        self._last_requested_at: dict[str, float] = {}
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=16)
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._started = False
        self._paused_for_calibration = False
        self._paused_for_mouse = False

    def start(self) -> None:
        if self._started or not self._enabled:
            if not self._enabled:
                logger.info("Acciones por gestos deshabilitadas")
            return

        self._ready_at = time.perf_counter() + self._startup_grace_seconds
        self._event_bus.subscribe("gesture.started", self._on_gesture)
        self._event_bus.subscribe("gesture.changed", self._on_gesture)
        self._event_bus.subscribe(
            "virtual_mouse.calibration_started",
            self._on_calibration_started,
        )
        self._event_bus.subscribe(
            "virtual_mouse.calibration_completed",
            self._on_calibration_finished,
        )
        self._event_bus.subscribe(
            "virtual_mouse.calibration_cancelled",
            self._on_calibration_finished,
        )
        self._event_bus.subscribe("virtual_mouse.enabled", self._on_mouse_enabled)
        self._event_bus.subscribe("virtual_mouse.disabled", self._on_mouse_disabled)
        self._worker = threading.Thread(
            target=self._run,
            name="gesture-actions",
            daemon=True,
        )
        self._worker.start()
        self._started = True
        logger.info("Mapeo gesto-acción iniciado con %d gestos", len(self._gesture_map))

    def _on_gesture(self, event_data: Any) -> None:
        if not isinstance(event_data, dict):
            return

        gesture = str(event_data.get("gesture", ""))
        action_id = self._gesture_map.get(gesture)
        if not action_id:
            return

        now = time.perf_counter()
        with self._lock:
            if self._actions_paused or now < self._ready_at:
                return
            previous = self._last_requested_at.get(action_id)
            if previous is not None and now - previous < self._cooldown_seconds:
                return
            self._last_requested_at[action_id] = now

        request = {
            "action_id": action_id,
            "context": {
                "source": "gesture",
                "gesture": gesture,
                "handedness": str(event_data.get("handedness", "Unknown")),
                "confidence": float(event_data.get("confidence", 0.0)),
                "gesture_timestamp": event_data.get("timestamp"),
            },
        }
        try:
            self._queue.put_nowait(request)
        except queue.Full:
            logger.warning("Cola de acciones por gestos llena; se omitió %s", gesture)

    def _run(self) -> None:
        while True:
            request = self._queue.get()
            try:
                if request is None:
                    return
                with self._lock:
                    if self._actions_paused:
                        continue
                self._event_bus.publish(ACTION_EXECUTE_EVENT, request)
            finally:
                self._queue.task_done()

    def _on_calibration_started(self, event_data: Any) -> None:
        with self._lock:
            self._paused_for_calibration = True
        logger.info("Acciones por gestos pausadas durante la calibración")

    def _on_calibration_finished(self, event_data: Any) -> None:
        with self._lock:
            self._paused_for_calibration = False
            still_paused = self._paused_for_mouse
        logger.info(
            "Calibración terminada; acciones por gestos %s",
            "siguen pausadas por modo mouse" if still_paused else "reanudadas",
        )

    @property
    def _actions_paused(self) -> bool:
        return self._paused_for_calibration or self._paused_for_mouse

    def _on_mouse_enabled(self, event_data: Any) -> None:
        with self._lock:
            self._paused_for_mouse = True
        logger.info("Acciones por gestos pausadas: modo mouse exclusivo")

    def _on_mouse_disabled(self, event_data: Any) -> None:
        with self._lock:
            self._paused_for_mouse = False
        logger.info("Acciones por gestos activas: modo mouse deshabilitado")

    def set_gesture_map(self, gesture_map: Mapping[str, str]) -> None:
        with self._lock:
            self._gesture_map = {
                str(gesture): str(action_id)
                for gesture, action_id in gesture_map.items()
                if action_id
            }
            self._last_requested_at.clear()
        logger.info("Mapa gesto-acción actualizado con %d gestos", len(self._gesture_map))

    @property
    def gesture_map(self) -> dict[str, str]:
        with self._lock:
            return dict(self._gesture_map)

    def close(self) -> None:
        if self._started:
            self._event_bus.unsubscribe("gesture.started", self._on_gesture)
            self._event_bus.unsubscribe("gesture.changed", self._on_gesture)
            self._event_bus.unsubscribe(
                "virtual_mouse.calibration_started",
                self._on_calibration_started,
            )
            self._event_bus.unsubscribe(
                "virtual_mouse.calibration_completed",
                self._on_calibration_finished,
            )
            self._event_bus.unsubscribe(
                "virtual_mouse.calibration_cancelled",
                self._on_calibration_finished,
            )
            self._event_bus.unsubscribe("virtual_mouse.enabled", self._on_mouse_enabled)
            self._event_bus.unsubscribe("virtual_mouse.disabled", self._on_mouse_disabled)
            try:
                self._queue.put(None, timeout=2.0)
            except queue.Full:
                logger.warning("No se pudo detener inmediatamente la cola de gestos")
            if self._worker is not None:
                self._worker.join(timeout=2.0)
        self._worker = None
        self._started = False
        logger.info("Mapeo gesto-acción cerrado")
