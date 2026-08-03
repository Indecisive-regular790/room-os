"""Puente seguro entre el EventBus y el hilo visual de Qt."""

from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Signal


class EventBridge(QObject):
    frame_ready = Signal(object, float)
    event_received = Signal(str, object)

    EVENT_NAMES = (
        "camera.error", "hand.detected", "hand.lost",
        "gesture.started", "gesture.changed", "gesture.held", "gesture.ended",
        "presence.entered", "presence.updated", "presence.exited",
        "presence.multiple_people", "face.recognized", "face.unknown",
        "face.lost", "virtual_mouse.enabled", "virtual_mouse.disabled",
        "virtual_mouse.error", "action.result", "vision_ai.started",
        "vision_ai.ready",
        "vision_ai.completed", "vision_ai.failed", "vision_ai.cancelled",
        "vision_ai.unavailable", "vision_ai.rate_limited",
    )

    def __init__(self, event_bus: Any) -> None:
        super().__init__()
        self._event_bus = event_bus
        self._callbacks: dict[str, Any] = {}
        event_bus.subscribe("camera.frame", self._on_frame)
        for name in self.EVENT_NAMES:
            callback = self._make_callback(name)
            self._callbacks[name] = callback
            event_bus.subscribe(name, callback)

    def _on_frame(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        frame = data.get("frame")
        if isinstance(frame, np.ndarray) and frame.size:
            self.frame_ready.emit(frame.copy(), float(data.get("fps", 0.0)))

    def _make_callback(self, name: str):
        def callback(data: Any) -> None:
            self.event_received.emit(name, data)
        return callback

    def close(self) -> None:
        self._event_bus.unsubscribe("camera.frame", self._on_frame)
        for name, callback in self._callbacks.items():
            self._event_bus.unsubscribe(name, callback)
        self._callbacks.clear()
