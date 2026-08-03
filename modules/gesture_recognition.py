"""Reconocimiento geométrico y estabilizado de gestos de mano."""

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import cv2

from config import (
    GESTURE_CONFIRMATION_FRAMES,
    GESTURE_HELD_INTERVAL_SECONDS,
    GESTURE_MISSING_FRAMES,
)
from core.event_bus import EventBus
from core.gesture_profiles import GestureProfileStore


logger = logging.getLogger(__name__)

OPEN_PALM = "OPEN_PALM"
FIST = "FIST"
POINT = "POINT"
PEACE = "PEACE"
THUMBS_UP = "THUMBS_UP"
THUMBS_DOWN = "THUMBS_DOWN"
SPIDERMAN = "SPIDERMAN"
PINCH = "PINCH"
UNKNOWN = "UNKNOWN"

_WRIST = 0
_THUMB_MCP = 2
_THUMB_IP = 3
_THUMB_TIP = 4
_INDEX_MCP = 5
_INDEX_PIP = 6
_INDEX_TIP = 8
_MIDDLE_MCP = 9
_MIDDLE_PIP = 10
_MIDDLE_TIP = 12
_RING_MCP = 13
_RING_PIP = 14
_RING_TIP = 16
_PINKY_MCP = 17
_PINKY_PIP = 18
_PINKY_TIP = 20

_FINGERS = {
    "index": (_INDEX_MCP, _INDEX_PIP, _INDEX_TIP),
    "middle": (_MIDDLE_MCP, _MIDDLE_PIP, _MIDDLE_TIP),
    "ring": (_RING_MCP, _RING_PIP, _RING_TIP),
    "pinky": (_PINKY_MCP, _PINKY_PIP, _PINKY_TIP),
}


@dataclass
class _HandGestureState:
    candidate: str = UNKNOWN
    candidate_frames: int = 0
    confirmed: str = UNKNOWN
    confirmed_observation: bool = False
    confirmed_since: float = 0.0
    last_held_at: float = 0.0
    confidence: float = 0.0
    position: dict[str, Any] = field(default_factory=dict)
    label_anchor: tuple[float, float] = (0.5, 0.5)
    missing_frames: int = 0


def _points_by_id(landmarks: list[dict[str, Any]]) -> dict[int, tuple[float, float]]:
    """Convierte los landmarks recibidos del tracker a puntos normalizados."""
    points: dict[int, tuple[float, float]] = {}
    for landmark in landmarks:
        normalized = landmark.get("normalized", {})
        landmark_id = int(landmark.get("id", -1))
        if landmark_id < 0 or "x" not in normalized or "y" not in normalized:
            continue
        points[landmark_id] = (
            float(normalized["x"]),
            float(normalized["y"]),
        )
    return points


def _distance(
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


def _palm_scale(points: dict[int, tuple[float, float]]) -> float:
    """Escala geometrica para que los umbrales no dependan de la distancia."""
    return max(_distance(points[_WRIST], points[_MIDDLE_MCP]), 1e-6)


def _finger_extended(
    points: dict[int, tuple[float, float]],
    finger_name: str,
) -> bool:
    mcp_id, pip_id, tip_id = _FINGERS[finger_name]
    mcp = points[mcp_id]
    pip = points[pip_id]
    tip = points[tip_id]
    scale = _palm_scale(points)
    return (
        tip[1] < pip[1] - (0.04 * scale)
        and pip[1] < mcp[1] - (0.025 * scale)
        and _distance(tip, mcp) > _distance(pip, mcp) * 1.35
    )


def _finger_folded(
    points: dict[int, tuple[float, float]],
    finger_name: str,
) -> bool:
    _, pip_id, tip_id = _FINGERS[finger_name]
    return points[tip_id][1] > points[pip_id][1] - (0.02 * _palm_scale(points))


def _thumb_extended(points: dict[int, tuple[float, float]]) -> bool:
    thumb_tip = points[_THUMB_TIP]
    thumb_ip = points[_THUMB_IP]
    index_mcp = points[_INDEX_MCP]
    wrist = points[_WRIST]
    return (
        _distance(thumb_tip, index_mcp) > _distance(thumb_ip, index_mcp) * 1.15
        and _distance(thumb_tip, wrist) > _distance(thumb_ip, wrist) * 1.05
    )


def _thumb_points_up(points: dict[int, tuple[float, float]]) -> bool:
    thumb_tip = points[_THUMB_TIP]
    thumb_ip = points[_THUMB_IP]
    thumb_mcp = points[_THUMB_MCP]
    scale = _palm_scale(points)
    vertical_change = thumb_mcp[1] - thumb_tip[1]
    horizontal_change = abs(thumb_tip[0] - thumb_mcp[0])
    return (
        thumb_tip[1] < thumb_ip[1] - (0.06 * scale)
        and thumb_ip[1] < thumb_mcp[1] - (0.06 * scale)
        and vertical_change > 0.70 * scale
        and vertical_change > horizontal_change * 1.10
    )


def _thumb_points_down(points: dict[int, tuple[float, float]]) -> bool:
    thumb_tip = points[_THUMB_TIP]
    thumb_ip = points[_THUMB_IP]
    thumb_mcp = points[_THUMB_MCP]
    scale = _palm_scale(points)
    vertical_change = thumb_tip[1] - thumb_mcp[1]
    horizontal_change = abs(thumb_tip[0] - thumb_mcp[0])
    return (
        thumb_tip[1] > thumb_ip[1] + (0.04 * scale)
        and thumb_tip[1] > thumb_mcp[1] + (0.45 * scale)
        and vertical_change > horizontal_change * 0.65
    )


def _has_required_points(points: dict[int, tuple[float, float]]) -> bool:
    return all(landmark_id in points for landmark_id in range(21))


def _palm_faces_camera(
    points: dict[int, tuple[float, float]],
    handedness: Optional[str],
) -> bool:
    """Distingue palma y dorso en una imagen espejo."""
    normalized_handedness = (handedness or "").casefold()
    if normalized_handedness not in {"left", "right"}:
        return True

    wrist = points[_WRIST]
    index_mcp = points[_INDEX_MCP]
    pinky_mcp = points[_PINKY_MCP]
    signed_area = (
        (index_mcp[0] - wrist[0]) * (pinky_mcp[1] - wrist[1])
        - (index_mcp[1] - wrist[1]) * (pinky_mcp[0] - wrist[0])
    )
    normalized_area = signed_area / (_palm_scale(points) ** 2)
    if abs(normalized_area) < 0.05:
        return False
    return normalized_area > 0 if normalized_handedness == "right" else normalized_area < 0


def is_open_palm(
    landmarks: list[dict[str, Any]],
    handedness: Optional[str] = None,
) -> bool:
    """Indica si los cuatro dedos y el pulgar están extendidos."""
    points = _points_by_id(landmarks)
    return (
        _has_required_points(points)
        and all(_finger_extended(points, finger_name) for finger_name in _FINGERS)
        and _palm_faces_camera(points, handedness)
    )


def is_fist(landmarks: list[dict[str, Any]]) -> bool:
    """Indica si los cuatro dedos están plegados y el pulgar no apunta arriba."""
    points = _points_by_id(landmarks)
    return _has_required_points(points) and all(
        _finger_folded(points, finger_name) for finger_name in _FINGERS
    ) and not _thumb_points_up(points)


def is_point(landmarks: list[dict[str, Any]]) -> bool:
    """Indica si únicamente el índice está extendido."""
    points = _points_by_id(landmarks)
    return (
        _has_required_points(points)
        and _finger_extended(points, "index")
        and all(
            _finger_folded(points, finger_name)
            for finger_name in ("middle", "ring", "pinky")
        )
    )


def is_peace(landmarks: list[dict[str, Any]]) -> bool:
    """Indica si índice y medio están extendidos y los demás plegados."""
    points = _points_by_id(landmarks)
    return (
        _has_required_points(points)
        and _finger_extended(points, "index")
        and _finger_extended(points, "middle")
        and _finger_folded(points, "ring")
        and _finger_folded(points, "pinky")
    )


def is_thumbs_up(landmarks: list[dict[str, Any]]) -> bool:
    """Indica si el pulgar apunta arriba y los otros dedos están plegados."""
    points = _points_by_id(landmarks)
    return _has_required_points(points) and _thumb_points_up(points) and all(
        _finger_folded(points, finger_name) for finger_name in _FINGERS
    )


def is_thumbs_down(landmarks: list[dict[str, Any]]) -> bool:
    """Indica si el pulgar apunta abajo y los otros dedos están plegados."""
    points = _points_by_id(landmarks)
    return (
        _has_required_points(points)
        and _thumb_points_down(points)
        and all(
            not _finger_extended(points, finger_name)
            for finger_name in _FINGERS
        )
    )


def is_spiderman(landmarks: list[dict[str, Any]]) -> bool:
    """Reconoce el signo rock/Spider-Man: índice y meñique levantados."""
    points = _points_by_id(landmarks)
    return (
        _has_required_points(points)
        and _finger_extended(points, "index")
        and _finger_folded(points, "middle")
        and _finger_folded(points, "ring")
        and _finger_extended(points, "pinky")
    )


def is_pinch(landmarks: list[dict[str, Any]]) -> bool:
    """Indica si pulgar e índice están juntos sin formar un puño."""
    points = _points_by_id(landmarks)
    if not _has_required_points(points):
        return False

    palm_size = _distance(points[_WRIST], points[_MIDDLE_MCP])
    if palm_size <= 0:
        return False

    pinch_ratio = _distance(points[_THUMB_TIP], points[_INDEX_TIP]) / palm_size
    all_fingers_folded = all(
        _finger_folded(points, finger_name) for finger_name in _FINGERS
    )
    index_not_folded = points[_INDEX_TIP][1] <= points[_INDEX_PIP][1] + 0.08
    return pinch_ratio <= 0.35 and index_not_folded and not all_fingers_folded


def classify_gesture(
    landmarks: list[dict[str, Any]],
    handedness: Optional[str] = None,
) -> tuple[str, float]:
    """Clasifica un conjunto de 21 puntos y devuelve nombre y confianza aproximada."""
    if len(landmarks) != 21:
        return UNKNOWN, 0.0

    if is_pinch(landmarks):
        points = _points_by_id(landmarks)
        palm_size = max(_distance(points[_WRIST], points[_MIDDLE_MCP]), 1e-6)
        ratio = _distance(points[_THUMB_TIP], points[_INDEX_TIP]) / palm_size
        return PINCH, max(0.75, min(1.0, 1.0 - ratio * 0.5))
    if is_thumbs_up(landmarks):
        return THUMBS_UP, 0.93
    if is_thumbs_down(landmarks):
        return THUMBS_DOWN, 0.93
    if is_spiderman(landmarks):
        return SPIDERMAN, 0.92
    if is_fist(landmarks):
        return FIST, 0.90
    if is_point(landmarks):
        return POINT, 0.92
    if is_peace(landmarks):
        return PEACE, 0.92
    if is_open_palm(landmarks, handedness):
        return OPEN_PALM, 0.94
    return UNKNOWN, 0.0


class GestureRecognitionModule:
    """Estabiliza gestos por mano, publica eventos y dibuja sus nombres."""

    def __init__(
        self,
        event_bus: EventBus,
        confirmation_frames: int = GESTURE_CONFIRMATION_FRAMES,
        missing_frames: int = GESTURE_MISSING_FRAMES,
        held_interval_seconds: float = GESTURE_HELD_INTERVAL_SECONDS,
        draw_labels: bool = True,
        profile_store: Optional[GestureProfileStore] = None,
    ) -> None:
        self._event_bus = event_bus
        self._confirmation_frames = max(1, confirmation_frames)
        self._missing_frames = max(1, missing_frames)
        self._held_interval_seconds = max(0.0, held_interval_seconds)
        self._draw_labels_enabled = bool(draw_labels)
        self._profile_store = profile_store
        self._states: dict[str, _HandGestureState] = {}
        self._lock = threading.RLock()
        self._started = False

    def start(self) -> None:
        """Conecta el reconocimiento a los eventos existentes."""
        if self._started:
            return
        self._event_bus.subscribe("hand.detected", self._on_hand_detected)
        self._event_bus.subscribe("hand.lost", self._on_hand_lost)
        self._event_bus.subscribe("camera.frame", self._on_camera_frame)
        self._started = True
        logger.info(
            "Reconocimiento de gestos iniciado (confirmación: %d frames)",
            self._confirmation_frames,
        )

    def _on_hand_detected(self, event_data: Any) -> None:
        """Clasifica y estabiliza todas las manos incluidas en el evento."""
        if not isinstance(event_data, dict):
            return

        timestamp = float(event_data.get("timestamp", time.perf_counter()))
        hands = event_data.get("hands", [])
        seen_hands: set[str] = set()
        pending_events: list[tuple[str, dict[str, Any]]] = []

        with self._lock:
            for hand in hands:
                handedness = str(hand.get("handedness", "Unknown"))
                landmarks = hand.get("landmarks", [])
                if handedness in seen_hands or len(landmarks) != 21:
                    continue

                seen_hands.add(handedness)
                gesture, rule_confidence = classify_gesture(landmarks, handedness)
                if self._profile_store is not None:
                    personalized = self._profile_store.match(landmarks, handedness)
                    if personalized is not None:
                        profile_gesture, profile_confidence = personalized
                        if gesture == UNKNOWN or profile_confidence > rule_confidence:
                            gesture = profile_gesture
                            rule_confidence = profile_confidence
                        elif gesture == profile_gesture:
                            rule_confidence = max(rule_confidence, profile_confidence)
                tracking_confidence = float(hand.get("confidence", 0.0))
                confidence = max(
                    0.0,
                    min(1.0, rule_confidence * tracking_confidence),
                )
                position, anchor = self._hand_position(landmarks)

                state = self._states.setdefault(handedness, _HandGestureState())
                state.missing_frames = 0
                state.position = position
                state.label_anchor = anchor
                pending_events.extend(
                    self._advance_state(
                        handedness,
                        state,
                        gesture,
                        confidence,
                        timestamp,
                    )
                )

            for handedness in tuple(self._states):
                if handedness in seen_hands:
                    continue
                state = self._states[handedness]
                state.missing_frames += 1
                if state.missing_frames >= self._missing_frames:
                    ended = self._end_state(handedness, state, timestamp)
                    if ended is not None:
                        pending_events.append(("gesture.ended", ended))
                    del self._states[handedness]

        self._publish_pending(pending_events)

    def _advance_state(
        self,
        handedness: str,
        state: _HandGestureState,
        gesture: str,
        confidence: float,
        timestamp: float,
    ) -> list[tuple[str, dict[str, Any]]]:
        """Aplica confirmación por frames y devuelve los eventos resultantes."""
        pending: list[tuple[str, dict[str, Any]]] = []

        if gesture == state.confirmed and state.confirmed_observation:
            state.candidate = gesture
            state.candidate_frames = 0
            if gesture != UNKNOWN:
                state.confidence = confidence
                if timestamp - state.last_held_at >= self._held_interval_seconds:
                    state.last_held_at = timestamp
                    pending.append(
                        (
                            "gesture.held",
                            self._event_payload(handedness, state, timestamp),
                        )
                    )
            return pending

        if gesture == state.candidate:
            state.candidate_frames += 1
        else:
            state.candidate = gesture
            state.candidate_frames = 1

        if state.candidate_frames < self._confirmation_frames:
            return pending

        previous_gesture = state.confirmed
        previous_confidence = state.confidence
        previous_duration = (
            max(0.0, timestamp - state.confirmed_since)
            if previous_gesture != UNKNOWN
            else 0.0
        )

        state.confirmed = gesture
        state.confirmed_observation = True
        state.confirmed_since = timestamp
        state.last_held_at = timestamp
        state.confidence = confidence
        state.candidate_frames = 0

        if previous_gesture == UNKNOWN and gesture != UNKNOWN:
            pending.append(
                (
                    "gesture.started",
                    self._event_payload(handedness, state, timestamp),
                )
            )
        elif previous_gesture != UNKNOWN and gesture == UNKNOWN:
            ended_payload = self._event_payload(
                handedness,
                state,
                timestamp,
                gesture_override=previous_gesture,
                duration_override=previous_duration,
                confidence_override=previous_confidence,
            )
            pending.append(("gesture.ended", ended_payload))
        elif previous_gesture != gesture:
            changed_payload = self._event_payload(handedness, state, timestamp)
            changed_payload["previous_gesture"] = previous_gesture
            changed_payload["previous_duration"] = previous_duration
            pending.append(("gesture.changed", changed_payload))

        return pending

    def _on_hand_lost(self, event_data: Any) -> None:
        """Finaliza inmediatamente los gestos cuando ya no hay manos visibles."""
        timestamp = (
            float(event_data.get("timestamp", time.perf_counter()))
            if isinstance(event_data, dict)
            else time.perf_counter()
        )
        pending_events: list[tuple[str, dict[str, Any]]] = []

        with self._lock:
            for handedness, state in self._states.items():
                ended = self._end_state(handedness, state, timestamp)
                if ended is not None:
                    pending_events.append(("gesture.ended", ended))
            self._states.clear()

        self._publish_pending(pending_events)

    def _end_state(
        self,
        handedness: str,
        state: _HandGestureState,
        timestamp: float,
    ) -> Optional[dict[str, Any]]:
        if state.confirmed == UNKNOWN:
            return None
        return self._event_payload(handedness, state, timestamp)

    @staticmethod
    def _hand_position(
        landmarks: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], tuple[float, float]]:
        normalized_x = [float(item["normalized"]["x"]) for item in landmarks]
        normalized_y = [float(item["normalized"]["y"]) for item in landmarks]
        pixel_x = [int(item["pixel"]["x"]) for item in landmarks]
        pixel_y = [int(item["pixel"]["y"]) for item in landmarks]

        center = {
            "normalized": {
                "x": sum(normalized_x) / len(normalized_x),
                "y": sum(normalized_y) / len(normalized_y),
            },
            "pixel": {
                "x": int(sum(pixel_x) / len(pixel_x)),
                "y": int(sum(pixel_y) / len(pixel_y)),
            },
        }
        anchor = (center["normalized"]["x"], min(normalized_y))
        return center, anchor

    @staticmethod
    def _event_payload(
        handedness: str,
        state: _HandGestureState,
        timestamp: float,
        gesture_override: Optional[str] = None,
        duration_override: Optional[float] = None,
        confidence_override: Optional[float] = None,
    ) -> dict[str, Any]:
        duration = (
            max(0.0, timestamp - state.confirmed_since)
            if duration_override is None
            else max(0.0, duration_override)
        )
        return {
            "gesture": gesture_override or state.confirmed,
            "handedness": handedness,
            "confidence": (
                state.confidence
                if confidence_override is None
                else confidence_override
            ),
            "duration": duration,
            "position": state.position,
            "timestamp": timestamp,
        }

    def _on_camera_frame(self, event_data: Any) -> None:
        if not self._draw_labels_enabled:
            return
        """Dibuja los gestos confirmados sobre el frame de visualización."""
        if not isinstance(event_data, dict):
            return
        frame = event_data.get("frame")
        if frame is None:
            return

        with self._lock:
            labels = tuple(
                (
                    handedness,
                    state.confirmed,
                    state.confidence,
                    state.label_anchor,
                )
                for handedness, state in self._states.items()
                if state.confirmed_observation
            )

        frame_height, frame_width = frame.shape[:2]
        for handedness, gesture, confidence, anchor in labels:
            x = min(max(int(anchor[0] * frame_width), 10), max(frame_width - 10, 10))
            y = min(max(int(anchor[1] * frame_height) - 18, 25), max(frame_height - 10, 25))
            cv2.putText(
                frame,
                f"{handedness}: {gesture} {confidence:.2f}",
                (x, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                (255, 80, 255),
                2,
                cv2.LINE_AA,
            )

    def set_draw_enabled(self, enabled: bool) -> None:
        self._draw_labels_enabled = bool(enabled)

    def _publish_pending(
        self,
        pending_events: list[tuple[str, dict[str, Any]]],
    ) -> None:
        for event_name, payload in pending_events:
            self._event_bus.publish(event_name, payload)

    def close(self) -> None:
        """Desconecta el módulo sin emitir acciones ni eventos artificiales."""
        if self._started:
            self._event_bus.unsubscribe("hand.detected", self._on_hand_detected)
            self._event_bus.unsubscribe("hand.lost", self._on_hand_lost)
            self._event_bus.unsubscribe("camera.frame", self._on_camera_frame)
        with self._lock:
            self._states.clear()
        self._started = False
        logger.info("Reconocimiento de gestos cerrado")
