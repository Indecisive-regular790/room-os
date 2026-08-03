"""Detección asíncrona de presencia mediante rostros, sin identificar personas."""

import logging
import queue
import threading
import time
from collections import deque
from enum import Enum
from typing import Any, Optional

import cv2
import mediapipe as mp

from config import (
    MULTIPLE_PERSON_THRESHOLD,
    PRESENCE_DETECTION_ENABLED,
    PRESENCE_ENTER_FRAMES,
    PRESENCE_EXIT_TIMEOUT_SECONDS,
    PRESENCE_HISTORY_LIMIT,
    PRESENCE_MIN_CONFIDENCE,
    PRESENCE_PROCESS_EVERY_N_FRAMES,
    PRESENCE_UPDATE_THROTTLE_SECONDS,
)
from core.event_bus import EventBus


logger = logging.getLogger(__name__)


class PresenceState(str, Enum):
    EMPTY = "EMPTY"
    PERSON_PRESENT = "PERSON_PRESENT"
    MULTIPLE_PEOPLE = "MULTIPLE_PEOPLE"
    TEMPORARILY_LOST = "TEMPORARILY_LOST"


class MediaPipeFaceDetector:
    """Adaptador pequeño alrededor de MediaPipe Face Detection."""

    def __init__(self, min_confidence: float = PRESENCE_MIN_CONFIDENCE) -> None:
        self._detector = mp.solutions.face_detection.FaceDetection(
            model_selection=0,
            min_detection_confidence=float(min_confidence),
        )

    def detect(self, frame: Any) -> list[dict[str, float]]:
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb_frame.flags.writeable = False
        result = self._detector.process(rgb_frame)
        boxes: list[dict[str, float]] = []
        for detection in result.detections or ():
            confidence = float(detection.score[0])
            relative = detection.location_data.relative_bounding_box
            left = min(max(float(relative.xmin), 0.0), 1.0)
            top = min(max(float(relative.ymin), 0.0), 1.0)
            right = min(max(float(relative.xmin + relative.width), 0.0), 1.0)
            bottom = min(max(float(relative.ymin + relative.height), 0.0), 1.0)
            if right <= left or bottom <= top:
                continue
            boxes.append(
                {
                    "x": left,
                    "y": top,
                    "width": right - left,
                    "height": bottom - top,
                    "confidence": confidence,
                }
            )
        return boxes

    def close(self) -> None:
        self._detector.close()


class PresenceDetector:
    """Estabiliza entradas y salidas y publica regiones faciales para consumidores."""

    def __init__(
        self,
        event_bus: EventBus,
        detector: Optional[Any] = None,
        enabled: bool = PRESENCE_DETECTION_ENABLED,
        enter_frames: int = PRESENCE_ENTER_FRAMES,
        exit_timeout_seconds: float = PRESENCE_EXIT_TIMEOUT_SECONDS,
        process_every_n_frames: int = PRESENCE_PROCESS_EVERY_N_FRAMES,
        draw_overlay: bool = True,
    ) -> None:
        self._event_bus = event_bus
        self._detector = detector
        self._owns_detector = detector is None
        self._enabled = bool(enabled)
        self._enter_frames = max(1, int(enter_frames))
        self._exit_timeout = max(0.1, float(exit_timeout_seconds))
        self._process_every = max(1, int(process_every_n_frames))
        self._draw_overlay_enabled = bool(draw_overlay)
        self._queue: queue.Queue[tuple[Any, float, int] | None] = queue.Queue(
            maxsize=1
        )
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._started = False
        self._frame_counter = 0

        self._state = PresenceState.EMPTY
        self._candidate_frames = 0
        self._candidate_since = 0.0
        self._present_since = 0.0
        self._last_detection_at = 0.0
        self._last_update_event_at = float("-inf")
        self._temporarily_lost = False
        self._latest_boxes: list[dict[str, float]] = []
        self._latest_count = 0
        self._latest_confidence = 0.0

        self._history: deque[dict[str, Any]] = deque(maxlen=PRESENCE_HISTORY_LIMIT)
        self._current_session: Optional[dict[str, Any]] = None

    @property
    def state(self) -> PresenceState:
        with self._lock:
            return self._state

    def start(self) -> None:
        if self._started:
            return
        self._event_bus.subscribe("camera.frame", self._on_camera_frame)
        self._event_bus.subscribe("face.identity_changed", self._on_identity_event)
        if self._enabled:
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="room-os-presence",
                daemon=True,
            )
            self._thread.start()
        self._started = True
        logger.info(
            "Detección de presencia %s",
            "iniciada" if self._enabled else "deshabilitada",
        )

    def _on_camera_frame(self, event_data: Any) -> None:
        if not isinstance(event_data, dict):
            return
        frame = event_data.get("frame")
        if frame is None:
            return
        timestamp = float(event_data.get("timestamp", time.perf_counter()))
        if self._draw_overlay_enabled:
            self._draw_status(frame, timestamp)
        if not self._enabled:
            return
        self._frame_counter += 1
        if self._frame_counter % self._process_every:
            return
        self._enqueue_latest((frame.copy(), timestamp, self._frame_counter))

    def _enqueue_latest(self, item: tuple[Any, float, int]) -> None:
        try:
            self._queue.put_nowait(item)
            return
        except queue.Full:
            pass
        try:
            self._queue.get_nowait()
            self._queue.task_done()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            logger.debug("Se descartó un frame de presencia atrasado")

    def _worker_loop(self) -> None:
        detector = self._detector or MediaPipeFaceDetector()
        try:
            while not self._stop_event.is_set():
                try:
                    item = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    if item is None:
                        return
                    frame, timestamp, frame_id = item
                    boxes = [
                        box
                        for box in detector.detect(frame)
                        if float(box.get("confidence", 0.0))
                        >= PRESENCE_MIN_CONFIDENCE
                    ]
                    self._process_observation(boxes, timestamp, frame_id)
                    self._event_bus.publish(
                        "presence.faces",
                        {
                            "frame": frame,
                            "timestamp": timestamp,
                            "frame_id": frame_id,
                            "bounding_boxes": boxes,
                        },
                    )
                except Exception as error:
                    logger.exception("Error detectando presencia")
                    self._event_bus.publish(
                        "presence.error",
                        {"timestamp": time.perf_counter(), "error": str(error)},
                    )
                finally:
                    self._queue.task_done()
        finally:
            if self._owns_detector and hasattr(detector, "close"):
                detector.close()

    def _process_observation(
        self,
        boxes: list[dict[str, float]],
        timestamp: float,
        frame_id: int,
    ) -> None:
        person_count = len(boxes)
        confidence = (
            sum(float(box.get("confidence", 0.0)) for box in boxes) / person_count
            if person_count
            else 0.0
        )
        events: list[tuple[str, dict[str, Any]]] = []
        with self._lock:
            self._latest_boxes = [dict(box) for box in boxes]
            self._latest_count = person_count
            self._latest_confidence = confidence

            if person_count:
                self._last_detection_at = timestamp
                if self._state == PresenceState.EMPTY:
                    if self._candidate_frames == 0:
                        self._candidate_since = timestamp
                    self._candidate_frames += 1
                    if self._candidate_frames >= self._enter_frames:
                        self._present_since = self._candidate_since
                        self._state = self._state_for_count(person_count)
                        self._start_history_session(timestamp, person_count)
                        events.append(
                            (
                                "presence.entered",
                                self._payload(timestamp, frame_id),
                            )
                        )
                        if self._state == PresenceState.MULTIPLE_PEOPLE:
                            events.append(
                                (
                                    "presence.multiple_people",
                                    self._payload(timestamp, frame_id),
                                )
                            )
                else:
                    if self._temporarily_lost:
                        self._temporarily_lost = False
                        events.append(
                            (
                                "presence.restored",
                                self._payload(timestamp, frame_id),
                            )
                        )
                    previous_state = self._state
                    self._state = self._state_for_count(person_count)
                    if self._current_session is not None:
                        self._current_session["max_person_count"] = max(
                            self._current_session["max_person_count"],
                            person_count,
                        )
                    if (
                        self._state == PresenceState.MULTIPLE_PEOPLE
                        and previous_state != PresenceState.MULTIPLE_PEOPLE
                    ):
                        events.append(
                            (
                                "presence.multiple_people",
                                self._payload(timestamp, frame_id),
                            )
                        )
            elif self._state == PresenceState.EMPTY:
                self._candidate_frames = 0
                self._candidate_since = 0.0
            elif timestamp - self._last_detection_at < self._exit_timeout:
                self._state = PresenceState.TEMPORARILY_LOST
                if not self._temporarily_lost:
                    self._temporarily_lost = True
                    events.append(
                        (
                            "presence.temporarily_lost",
                            self._payload(timestamp, frame_id),
                        )
                    )
            else:
                self._finish_history_session(timestamp)
                self._state = PresenceState.EMPTY
                exit_payload = self._payload(timestamp, frame_id)
                self._candidate_frames = 0
                self._temporarily_lost = False
                self._present_since = 0.0
                events.append(("presence.exited", exit_payload))

            if timestamp - self._last_update_event_at >= PRESENCE_UPDATE_THROTTLE_SECONDS:
                self._last_update_event_at = timestamp
                events.append(("presence.updated", self._payload(timestamp, frame_id)))

        for event_name, payload in events:
            self._event_bus.publish(event_name, payload)

    def _state_for_count(self, person_count: int) -> PresenceState:
        return (
            PresenceState.MULTIPLE_PEOPLE
            if person_count >= MULTIPLE_PERSON_THRESHOLD
            else PresenceState.PERSON_PRESENT
        )

    def _payload(self, timestamp: float, frame_id: int) -> dict[str, Any]:
        duration = (
            max(0.0, timestamp - self._present_since)
            if self._present_since
            else 0.0
        )
        return {
            "timestamp": float(timestamp),
            "person_count": self._latest_count,
            "duration_seconds": duration,
            "confidence": self._latest_confidence,
            "state": self._state.value,
            "frame_id": int(frame_id),
            "bounding_boxes": [dict(box) for box in self._latest_boxes],
        }

    def _start_history_session(self, timestamp: float, person_count: int) -> None:
        self._current_session = {
            "entered_at": timestamp,
            "exited_at": None,
            "duration_seconds": 0.0,
            "identities": [],
            "identity_changes": [],
            "max_person_count": person_count,
        }

    def _finish_history_session(self, timestamp: float) -> None:
        if self._current_session is None:
            return
        self._current_session["exited_at"] = timestamp
        self._current_session["duration_seconds"] = max(
            0.0,
            timestamp - float(self._current_session["entered_at"]),
        )
        self._history.append(dict(self._current_session))
        self._current_session = None

    def _on_identity_event(self, event_data: Any) -> None:
        if not isinstance(event_data, dict):
            return
        with self._lock:
            if self._current_session is None:
                return
            identity = str(event_data.get("identity", "UNKNOWN"))
            if identity not in self._current_session["identities"]:
                self._current_session["identities"].append(identity)
            self._current_session["identity_changes"].append(
                {
                    "timestamp": event_data.get("timestamp"),
                    "track_id": event_data.get("track_id"),
                    "identity": identity,
                }
            )

    def get_history(self) -> tuple[dict[str, Any], ...]:
        with self._lock:
            history = list(self._history)
            if self._current_session is not None:
                history.append(dict(self._current_session))
            return tuple(history)

    def _draw_status(self, frame: Any, timestamp: float) -> None:
        height, width = frame.shape[:2]
        with self._lock:
            boxes = tuple(dict(box) for box in self._latest_boxes)
            state = self._state.value if self._enabled else "OFF"
            count = self._latest_count
            duration = (
                max(0.0, timestamp - self._present_since)
                if self._present_since
                else 0.0
            )
        for box in boxes:
            left = int(box["x"] * width)
            top = int(box["y"] * height)
            right = int((box["x"] + box["width"]) * width)
            bottom = int((box["y"] + box["height"]) * height)
            cv2.rectangle(frame, (left, top), (right, bottom), (255, 180, 40), 2)
        cv2.putText(
            frame,
            f"Presence: {state} | People: {count} | Present: {self._format_duration(duration)}",
            (20, 170),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            (255, 210, 80),
            2,
            cv2.LINE_AA,
        )

    @staticmethod
    def _format_duration(duration: float) -> str:
        total_seconds = max(0, int(duration))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def set_draw_enabled(self, enabled: bool) -> None:
        self._draw_overlay_enabled = bool(enabled)

    def close(self) -> None:
        if self._started:
            self._event_bus.unsubscribe("camera.frame", self._on_camera_frame)
            self._event_bus.unsubscribe("face.identity_changed", self._on_identity_event)
        self._stop_event.set()
        if self._thread is not None:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                try:
                    self._queue.get_nowait()
                    self._queue.task_done()
                except queue.Empty:
                    pass
                try:
                    self._queue.put_nowait(None)
                except queue.Full:
                    pass
            self._thread.join(timeout=5.0)
            if self._thread.is_alive():
                logger.warning("El worker de presencia no terminó a tiempo")
            self._thread = None
        self._started = False
        logger.info("Detector de presencia cerrado")
