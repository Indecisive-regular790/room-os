"""Mouse virtual desacoplado basado en los landmarks publicados de la mano."""

import json
import logging
import math
import threading
import time
from enum import Enum
from pathlib import Path
from statistics import median
from typing import Any, Callable, Optional

import cv2

from core.runtime_paths import application_data_dir
from config import (
    ACTIVE_REGION_BOTTOM,
    ACTIVE_REGION_LEFT,
    ACTIVE_REGION_RIGHT,
    ACTIVE_REGION_TOP,
    CLICK_DEBOUNCE_SECONDS,
    CONTROL_HAND,
    DRAG_HOLD_SECONDS,
    GESTURE_SUSPEND_DELAY_SECONDS,
    HAND_WARMUP_FRAMES,
    MIN_HAND_CONFIDENCE,
    MIRROR_MOUSE_X,
    MOUSE_BETA,
    MOUSE_DEAD_ZONE_PIXELS,
    MOUSE_MIN_CUTOFF,
    MOUSE_POSE_CONFIRM_FRAMES,
    MOUSE_POSE_GRACE_FRAMES,
    MOUSE_SMOOTHING_ENABLED,
    MOUSE_SMOOTHING_FACTOR,
    PINCH_CLICK_THRESHOLD,
    PINCH_RELEASE_THRESHOLD,
    RIGHT_CLICK_DEBOUNCE_SECONDS,
    RIGHT_CLICK_RELEASE_THRESHOLD,
    RIGHT_CLICK_THRESHOLD,
    SCROLL_ACTIVATION_HOLD_SECONDS,
    SCROLL_DEAD_ZONE,
    SCROLL_ENABLED,
    SCROLL_MAX_STEP,
    SCROLL_SENSITIVITY,
    VIRTUAL_MOUSE_ENABLED,
    VIRTUAL_MOUSE_CALIBRATE_KEY,
    VIRTUAL_MOUSE_CALIBRATION_MIN_SPAN,
    VIRTUAL_MOUSE_CALIBRATION_SAMPLES,
    VIRTUAL_MOUSE_CALIBRATION_SETTLE_FRAMES,
    VIRTUAL_MOUSE_CALIBRATION_TARGET_RADIUS,
    VIRTUAL_MOUSE_CALIBRATION_TARGETS,
    VIRTUAL_MOUSE_MOVE_EVENT_INTERVAL_SECONDS,
    VIRTUAL_MOUSE_RELEASE_KEY,
    VIRTUAL_MOUSE_TOGGLE_KEY,
)
from core.event_bus import EventBus
from platforms.windows.mouse_control import WindowsMouseControl


logger = logging.getLogger(__name__)

_APP_GESTURES = {
    "PEACE",
    "THUMBS_UP",
    "THUMBS_DOWN",
    "OPEN_PALM",
    "SPIDERMAN",
}


class VirtualMouseState(str, Enum):
    DISABLED = "DISABLED"
    IDLE = "IDLE"
    MOVING = "MOVING"
    LEFT_PINCH = "LEFT_PINCH"
    DRAGGING = "DRAGGING"
    RIGHT_PINCH = "RIGHT_PINCH"
    SCROLLING = "SCROLLING"
    SUSPENDED = "SUSPENDED"
    CALIBRATING = "CALIBRATING"


class OneEuroFilter:
    """Filtro One Euro unidimensional sin dependencias adicionales."""

    def __init__(
        self,
        min_cutoff: float = 1.0,
        beta: float = 0.015,
        smoothing_factor: float = 1.0,
    ) -> None:
        self.min_cutoff = max(0.001, float(min_cutoff))
        self.beta = max(0.0, float(beta))
        self.smoothing_factor = min(max(float(smoothing_factor), 0.01), 1.0)
        self._value: Optional[float] = None
        self._derivative = 0.0
        self._timestamp: Optional[float] = None

    @staticmethod
    def _alpha(cutoff: float, elapsed: float) -> float:
        tau = 1.0 / (2.0 * math.pi * max(cutoff, 0.001))
        return 1.0 / (1.0 + tau / max(elapsed, 1e-6))

    def filter(self, value: float, timestamp: float) -> float:
        value = float(value)
        timestamp = float(timestamp)
        if self._value is None or self._timestamp is None:
            self._value = value
            self._timestamp = timestamp
            return value

        elapsed = max(timestamp - self._timestamp, 1e-6)
        derivative = (value - self._value) / elapsed
        derivative_alpha = self._alpha(1.0, elapsed)
        self._derivative += derivative_alpha * (derivative - self._derivative)
        cutoff = self.min_cutoff + self.beta * abs(self._derivative)
        filtered = self._value + self._alpha(cutoff, elapsed) * (
            value - self._value
        )
        filtered = self._value + self.smoothing_factor * (
            filtered - self._value
        )
        self._value = filtered
        self._timestamp = timestamp
        return filtered

    def reset(self) -> None:
        self._value = None
        self._derivative = 0.0
        self._timestamp = None


def normalized_to_screen(
    x: float,
    y: float,
    screen_size: tuple[int, int],
    active_region: tuple[float, float, float, float],
    mirror_x: bool,
) -> Optional[tuple[int, int]]:
    """Convierte un punto normalizado dentro de la región activa a pantalla."""
    left, right, top, bottom = active_region
    if right <= left or bottom <= top:
        raise ValueError("La región activa del mouse no es válida")
    if not (left <= x <= right and top <= y <= bottom):
        return None

    relative_x = (float(x) - left) / (right - left)
    relative_y = (float(y) - top) / (bottom - top)
    if mirror_x:
        relative_x = 1.0 - relative_x

    width, height = screen_size
    screen_x = round(min(max(relative_x, 0.0), 1.0) * max(width - 1, 0))
    screen_y = round(min(max(relative_y, 0.0), 1.0) * max(height - 1, 0))
    return screen_x, screen_y


class VirtualMouse:
    """Máquina de estados para movimiento, clic, arrastre y scroll."""

    def __init__(
        self,
        event_bus: EventBus,
        controller: Optional[WindowsMouseControl] = None,
        enabled: bool = VIRTUAL_MOUSE_ENABLED,
        draw_overlay: bool = True,
        control_hand: str = CONTROL_HAND,
        clock: Callable[[], float] = time.perf_counter,
        calibration_path: Optional[Path] = None,
    ) -> None:
        self._event_bus = event_bus
        self._controller = controller or WindowsMouseControl()
        self._configured_enabled = bool(enabled)
        self._enabled = bool(enabled)
        self._draw_overlay_enabled = bool(draw_overlay)
        self._control_hand = str(control_hand)
        self._clock = clock
        self._calibration_path = calibration_path or (
            application_data_dir() / "virtual_mouse_calibration.json"
        )
        self._screen_size = (1, 1)
        self._active_region = (
            ACTIVE_REGION_LEFT,
            ACTIVE_REGION_RIGHT,
            ACTIVE_REGION_TOP,
            ACTIVE_REGION_BOTTOM,
        )
        self._state = (
            VirtualMouseState.IDLE if enabled else VirtualMouseState.DISABLED
        )
        self._lock = threading.RLock()
        self._started = False

        self._x_filter = OneEuroFilter(
            MOUSE_MIN_CUTOFF,
            MOUSE_BETA,
            MOUSE_SMOOTHING_FACTOR,
        )
        self._y_filter = OneEuroFilter(
            MOUSE_MIN_CUTOFF,
            MOUSE_BETA,
            MOUSE_SMOOTHING_FACTOR,
        )
        self._last_cursor_position: Optional[tuple[int, int]] = None
        self._latest_frame_position: Optional[tuple[float, float]] = None
        self._latest_confidence = 0.0
        self._latest_pose_match: Optional[bool] = None
        self._warmup_frames = 0
        self._movement_pose_hits = 0
        self._movement_pose_misses = 0
        self._movement_pose_active = False

        self._left_pressed = False
        self._left_pinched_at = 0.0
        self._dragging = False
        self._left_release_required = False
        self._right_pinched = False
        self._last_left_click_at = float("-inf")
        self._last_right_click_at = float("-inf")

        self._scroll_candidate_since: Optional[float] = None
        self._scroll_last_y: Optional[float] = None
        self._active_gestures: set[str] = set()
        self._suspended_until = 0.0
        self._suspend_reason = ""

        self._last_move_event_at = float("-inf")
        self._toggle_key_was_down = False
        self._release_key_was_down = False
        self._calibrate_key_was_down = False

        self._calibration_targets = tuple(
            (float(x), float(y)) for x, y in VIRTUAL_MOUSE_CALIBRATION_TARGETS
        )
        self._calibration_target_index = -1
        self._calibration_positions: list[tuple[float, float]] = []
        self._calibration_target_samples: list[tuple[float, float]] = []
        self._calibration_pose_samples: list[tuple[float, ...]] = []
        self._calibration_settle_frames = 0
        self._calibration_message = ""
        self._movement_pose_profile: Optional[dict[str, list[float]]] = None

    @property
    def state(self) -> VirtualMouseState:
        with self._lock:
            return self._state

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def start(self) -> None:
        if self._started:
            return
        self._screen_size = self._controller.get_screen_size()
        self._load_calibration()
        self._event_bus.subscribe("hand.detected", self._on_hand_detected)
        self._event_bus.subscribe("hand.lost", self._on_hand_lost)
        self._event_bus.subscribe("camera.frame", self._on_camera_frame)
        self._started = True
        logger.info(
            "Mouse virtual %s para la mano %s (%dx%d)",
            "activo" if self._enabled else "deshabilitado",
            self._control_hand,
            *self._screen_size,
        )
        self._publish(
            "virtual_mouse.enabled" if self._enabled else "virtual_mouse.disabled",
            self._clock(),
            reason="startup",
        )

    def _on_hand_detected(self, event_data: Any) -> None:
        if not isinstance(event_data, dict):
            return
        timestamp = float(event_data.get("timestamp", self._clock()))
        try:
            with self._lock:
                if not self._enabled:
                    return
                hand = self._select_control_hand(event_data.get("hands", []))
                if hand is None:
                    self._reset_hand_state(release_mouse=True)
                    return

                confidence = float(hand.get("confidence", 0.0))
                if confidence < MIN_HAND_CONFIDENCE:
                    self._reset_hand_state(release_mouse=True)
                    return
                landmarks = hand.get("landmarks", [])
                points = self._points_by_id(landmarks)
                if len(points) != 21:
                    self._reset_hand_state(release_mouse=True)
                    return

                self._latest_confidence = confidence
                self._latest_frame_position = points[8]
                self._latest_pose_match = (
                    self._matches_movement_pose(points)
                    if self._movement_pose_profile is not None
                    else None
                )
                self._warmup_frames += 1
                if self._state == VirtualMouseState.CALIBRATING:
                    self._process_calibration(points, timestamp, confidence)
                    return
                self._process_hand(points, timestamp, confidence)
        except Exception as error:
            logger.exception("Error procesando el mouse virtual")
            with self._lock:
                was_calibrating = self._state == VirtualMouseState.CALIBRATING
                was_dragging = self._release_left_button(reason="exception")
                self._state = VirtualMouseState.IDLE
            if was_dragging:
                self._publish(
                    "virtual_mouse.drag_ended",
                    timestamp,
                    reason="exception",
                )
            self._publish(
                "virtual_mouse.error",
                timestamp,
                reason=str(error),
                confidence=self._latest_confidence,
            )
            if was_calibrating:
                self._publish(
                    "virtual_mouse.calibration_cancelled",
                    timestamp,
                    reason="exception",
                )

    def _process_hand(
        self,
        points: dict[int, tuple[float, float]],
        timestamp: float,
        confidence: float,
    ) -> None:
        scroll_pose = self._is_scroll_pose(points)
        if scroll_pose:
            if self._scroll_candidate_since is None:
                self._scroll_candidate_since = timestamp
                self._scroll_last_y = points[9][1]
        else:
            self._reset_scroll()

        if self._must_suspend(timestamp, scroll_pose):
            was_dragging = self._release_left_button(reason="gesture")
            self._state = VirtualMouseState.SUSPENDED
            if was_dragging:
                self._publish(
                    "virtual_mouse.drag_ended",
                    timestamp,
                    reason="gesture",
                    confidence=confidence,
                )
            return

        warmed_up = self._warmup_frames >= HAND_WARMUP_FRAMES
        palm_size = max(self._distance(points[0], points[9]), 1e-6)
        left_ratio = self._distance(points[4], points[8]) / palm_size
        right_ratio = self._distance(points[4], points[12]) / palm_size

        if self._handle_right_pinch(
            points,
            right_ratio,
            timestamp,
            confidence,
            warmed_up,
        ):
            return
        if self._handle_left_pinch(
            points,
            left_ratio,
            timestamp,
            confidence,
            warmed_up,
        ):
            return
        if self._handle_scroll(points, timestamp, confidence, warmed_up):
            return

        if self._stable_movement_pose(points):
            moved = self._move_from_index(points[8], timestamp, confidence)
            self._state = (
                VirtualMouseState.MOVING if moved else VirtualMouseState.IDLE
            )
        else:
            self._state = VirtualMouseState.IDLE

    def _handle_right_pinch(
        self,
        points: dict[int, tuple[float, float]],
        ratio: float,
        timestamp: float,
        confidence: float,
        warmed_up: bool,
    ) -> bool:
        if self._right_pinched:
            if ratio >= RIGHT_CLICK_RELEASE_THRESHOLD:
                self._right_pinched = False
                self._state = VirtualMouseState.IDLE
                return False
            self._state = VirtualMouseState.RIGHT_PINCH
            return True

        valid_pose = (
            self._finger_extended(points, 5, 6, 8)
            and points[12][1] <= points[10][1] + 0.08
            and not self._finger_extended(points, 13, 14, 16)
            and not self._finger_extended(points, 17, 18, 20)
        )
        if (
            warmed_up
            and valid_pose
            and ratio <= RIGHT_CLICK_THRESHOLD
            and timestamp - self._last_right_click_at
            >= RIGHT_CLICK_DEBOUNCE_SECONDS
        ):
            was_dragging = self._release_left_button(reason="right_click")
            if was_dragging:
                self._publish(
                    "virtual_mouse.drag_ended",
                    timestamp,
                    reason="right_click",
                    confidence=confidence,
                )
            self._controller.right_click()
            self._right_pinched = True
            self._last_right_click_at = timestamp
            self._state = VirtualMouseState.RIGHT_PINCH
            self._publish(
                "virtual_mouse.right_click",
                timestamp,
                confidence=confidence,
            )
            return True
        return False

    def _handle_left_pinch(
        self,
        points: dict[int, tuple[float, float]],
        ratio: float,
        timestamp: float,
        confidence: float,
        warmed_up: bool,
    ) -> bool:
        if self._left_release_required:
            if ratio >= PINCH_RELEASE_THRESHOLD:
                self._left_release_required = False
            return True

        if self._left_pressed:
            if ratio >= PINCH_RELEASE_THRESHOLD:
                was_dragging = self._dragging
                self._controller.mouse_up()
                self._left_pressed = False
                self._dragging = False
                self._last_left_click_at = timestamp
                event_name = (
                    "virtual_mouse.drag_ended"
                    if was_dragging
                    else "virtual_mouse.left_click"
                )
                self._state = VirtualMouseState.IDLE
                self._publish(event_name, timestamp, confidence=confidence)
                return True

            if (
                not self._dragging
                and timestamp - self._left_pinched_at >= DRAG_HOLD_SECONDS
            ):
                self._dragging = True
                self._state = VirtualMouseState.DRAGGING
                self._publish(
                    "virtual_mouse.drag_started",
                    timestamp,
                    confidence=confidence,
                )
            else:
                self._state = (
                    VirtualMouseState.DRAGGING
                    if self._dragging
                    else VirtualMouseState.LEFT_PINCH
                )
            self._move_from_index(points[8], timestamp, confidence)
            return True

        valid_pose = all(
            not self._finger_extended(points, mcp, pip, tip)
            for mcp, pip, tip in ((9, 10, 12), (13, 14, 16), (17, 18, 20))
        )
        if (
            warmed_up
            and valid_pose
            and ratio <= PINCH_CLICK_THRESHOLD
            and timestamp - self._last_left_click_at >= CLICK_DEBOUNCE_SECONDS
        ):
            self._controller.mouse_down()
            self._left_pressed = True
            self._left_pinched_at = timestamp
            self._dragging = False
            self._state = VirtualMouseState.LEFT_PINCH
            return True
        return False

    def _handle_scroll(
        self,
        points: dict[int, tuple[float, float]],
        timestamp: float,
        confidence: float,
        warmed_up: bool,
    ) -> bool:
        if (
            not SCROLL_ENABLED
            or not warmed_up
            or not self._is_scroll_pose(points)
            or self._scroll_candidate_since is None
            or timestamp - self._scroll_candidate_since
            < SCROLL_ACTIVATION_HOLD_SECONDS
        ):
            return False

        current_y = points[9][1]
        previous_y = self._scroll_last_y
        self._scroll_last_y = current_y
        self._state = VirtualMouseState.SCROLLING
        if previous_y is None:
            return True
        delta = previous_y - current_y
        if abs(delta) < SCROLL_DEAD_ZONE:
            return True
        amount = round(delta * 100.0 * SCROLL_SENSITIVITY)
        amount = max(-SCROLL_MAX_STEP, min(SCROLL_MAX_STEP, amount))
        if amount:
            self._controller.scroll(amount)
            self._publish(
                "virtual_mouse.scroll",
                timestamp,
                confidence=confidence,
                reason=str(amount),
                amount=amount,
            )
        return True

    def _move_from_index(
        self,
        frame_position: tuple[float, float],
        timestamp: float,
        confidence: float,
    ) -> bool:
        target = normalized_to_screen(
            frame_position[0],
            frame_position[1],
            self._screen_size,
            self._active_region,
            MIRROR_MOUSE_X,
        )
        if target is None:
            return False

        x, y = target
        if MOUSE_SMOOTHING_ENABLED:
            x = round(self._x_filter.filter(x, timestamp))
            y = round(self._y_filter.filter(y, timestamp))
        x = min(max(x, 0), max(self._screen_size[0] - 1, 0))
        y = min(max(y, 0), max(self._screen_size[1] - 1, 0))

        if self._last_cursor_position is not None:
            if self._distance(self._last_cursor_position, (x, y)) < MOUSE_DEAD_ZONE_PIXELS:
                return False

        self._controller.move_cursor(x, y)
        self._last_cursor_position = (x, y)
        if timestamp - self._last_move_event_at >= VIRTUAL_MOUSE_MOVE_EVENT_INTERVAL_SECONDS:
            self._last_move_event_at = timestamp
            self._publish(
                "virtual_mouse.moved",
                timestamp,
                confidence=confidence,
                screen_position=(x, y),
                frame_position=frame_position,
            )
        return True

    def _on_gesture_started(self, event_data: Any) -> None:
        if not isinstance(event_data, dict):
            return
        gesture = str(event_data.get("gesture", ""))
        if gesture not in _APP_GESTURES:
            return
        timestamp = float(event_data.get("timestamp", self._clock()))
        with self._lock:
            if self._state == VirtualMouseState.CALIBRATING:
                return
            self._active_gestures.add(gesture)
            self._suspend_reason = gesture
            was_dragging = self._release_left_button(reason="gesture")
            self._state = VirtualMouseState.SUSPENDED
        if was_dragging:
            self._publish(
                "virtual_mouse.drag_ended",
                timestamp,
                reason="gesture",
            )
        self._publish(
            "virtual_mouse.suspended",
            timestamp,
            reason=gesture,
            confidence=float(event_data.get("confidence", 0.0)),
        )

    def _on_gesture_changed(self, event_data: Any) -> None:
        if not isinstance(event_data, dict):
            return
        with self._lock:
            if self._state == VirtualMouseState.CALIBRATING:
                return
        previous = str(event_data.get("previous_gesture", ""))
        current = str(event_data.get("gesture", ""))
        timestamp = float(event_data.get("timestamp", self._clock()))
        if previous in _APP_GESTURES:
            with self._lock:
                self._active_gestures.discard(previous)
                self._suspended_until = timestamp + GESTURE_SUSPEND_DELAY_SECONDS
        if current in _APP_GESTURES:
            self._on_gesture_started(event_data)

    def _on_gesture_ended(self, event_data: Any) -> None:
        if not isinstance(event_data, dict):
            return
        with self._lock:
            if self._state == VirtualMouseState.CALIBRATING:
                return
        gesture = str(event_data.get("gesture", ""))
        if gesture not in _APP_GESTURES:
            return
        timestamp = float(event_data.get("timestamp", self._clock()))
        with self._lock:
            self._active_gestures.discard(gesture)
            self._suspended_until = timestamp + GESTURE_SUSPEND_DELAY_SECONDS
            self._suspend_reason = "gesture_cooldown"

    def _must_suspend(self, timestamp: float, scroll_pose: bool) -> bool:
        if not self._active_gestures:
            return timestamp < self._suspended_until
        if self._active_gestures == {"PEACE"} and scroll_pose:
            return not (
                self._scroll_candidate_since is not None
                and timestamp - self._scroll_candidate_since
                >= SCROLL_ACTIVATION_HOLD_SECONDS
            )
        return True

    def _on_hand_lost(self, event_data: Any) -> None:
        timestamp = (
            float(event_data.get("timestamp", self._clock()))
            if isinstance(event_data, dict)
            else self._clock()
        )
        with self._lock:
            was_dragging = self._dragging
            was_calibrating = self._state == VirtualMouseState.CALIBRATING
            self._reset_hand_state(release_mouse=True)
            if was_calibrating:
                self._state = VirtualMouseState.CALIBRATING
                self._calibration_message = "Muestra la mano derecha con solo el índice"
        if was_dragging:
            self._publish(
                "virtual_mouse.drag_ended",
                timestamp,
                reason="hand_lost",
            )

    def start_calibration(self, timestamp: Optional[float] = None) -> None:
        """Inicia una calibración guiada de los límites cómodos de movimiento."""
        timestamp = self._clock() if timestamp is None else float(timestamp)
        with self._lock:
            if not self._enabled:
                return
            self._release_left_button(reason="calibration")
            self._calibration_target_index = 0
            self._calibration_positions = []
            self._calibration_target_samples = []
            self._calibration_pose_samples = []
            self._calibration_settle_frames = VIRTUAL_MOUSE_CALIBRATION_SETTLE_FRAMES
            self._calibration_message = "Lleva el punto amarillo al objetivo azul"
            self._active_gestures.clear()
            self._suspended_until = 0.0
            self._suspend_reason = ""
            self._state = VirtualMouseState.CALIBRATING
        self._publish(
            "virtual_mouse.calibration_started",
            timestamp,
            reason="F9",
        )

    def cancel_calibration(
        self,
        timestamp: Optional[float] = None,
        reason: str = "cancelled",
    ) -> None:
        timestamp = self._clock() if timestamp is None else float(timestamp)
        with self._lock:
            if self._state != VirtualMouseState.CALIBRATING:
                return
            self._calibration_target_index = -1
            self._calibration_positions = []
            self._calibration_target_samples = []
            self._calibration_pose_samples = []
            self._calibration_message = "Calibración cancelada"
            self._state = VirtualMouseState.IDLE
        self._publish(
            "virtual_mouse.calibration_cancelled",
            timestamp,
            reason=reason,
        )

    def _process_calibration(
        self,
        points: dict[int, tuple[float, float]],
        timestamp: float,
        confidence: float,
    ) -> None:
        if not self._raw_index_only_extended(points):
            self._calibration_message = "Extiende únicamente el índice"
            return

        target = self._calibration_targets[self._calibration_target_index]
        index_position = points[8]
        if self._distance(index_position, target) > VIRTUAL_MOUSE_CALIBRATION_TARGET_RADIUS:
            self._calibration_settle_frames = VIRTUAL_MOUSE_CALIBRATION_SETTLE_FRAMES
            self._calibration_target_samples = []
            self._calibration_message = "Lleva el punto amarillo al objetivo azul"
            return
        if self._calibration_settle_frames > 0:
            self._calibration_settle_frames -= 1
            self._calibration_message = "Mantén la mano estable sobre el objetivo"
            return

        self._calibration_target_samples.append(index_position)
        self._calibration_pose_samples.append(self._movement_pose_features(points))
        self._calibration_message = "Leyendo tu postura de movimiento..."
        if len(self._calibration_target_samples) < VIRTUAL_MOUSE_CALIBRATION_SAMPLES:
            return

        captured_x = median(sample[0] for sample in self._calibration_target_samples)
        captured_y = median(sample[1] for sample in self._calibration_target_samples)
        self._calibration_positions.append((float(captured_x), float(captured_y)))
        self._calibration_target_index += 1
        self._calibration_target_samples = []
        if self._calibration_target_index >= len(self._calibration_targets):
            self._finish_calibration(timestamp, confidence)
            return

        self._calibration_settle_frames = VIRTUAL_MOUSE_CALIBRATION_SETTLE_FRAMES
        self._calibration_message = "Bien. Ahora alcanza el siguiente objetivo"

    def _finish_calibration(self, timestamp: float, confidence: float) -> None:
        left = min(position[0] for position in self._calibration_positions)
        right = max(position[0] for position in self._calibration_positions)
        top = min(position[1] for position in self._calibration_positions)
        bottom = max(position[1] for position in self._calibration_positions)
        if (
            right - left < VIRTUAL_MOUSE_CALIBRATION_MIN_SPAN
            or bottom - top < VIRTUAL_MOUSE_CALIBRATION_MIN_SPAN
        ):
            self._calibration_message = "Rango insuficiente; pulsa F9 para repetir"
            self._state = VirtualMouseState.IDLE
            self._calibration_target_index = -1
            self._publish(
                "virtual_mouse.error",
                timestamp,
                confidence=confidence,
                reason="calibration_span_too_small",
            )
            self._publish(
                "virtual_mouse.calibration_cancelled",
                timestamp,
                confidence=confidence,
                reason="calibration_span_too_small",
            )
            return

        self._active_region = (
            min(max(left, 0.0), 1.0),
            min(max(right, 0.0), 1.0),
            min(max(top, 0.0), 1.0),
            min(max(bottom, 0.0), 1.0),
        )
        self._movement_pose_profile = self._build_movement_pose_profile(
            self._calibration_pose_samples
        )
        self._save_calibration()
        self._calibration_message = "Región y postura de movimiento guardadas"
        self._calibration_target_index = -1
        self._state = VirtualMouseState.IDLE
        self._reset_tracking()
        self._publish(
            "virtual_mouse.calibration_completed",
            timestamp,
            confidence=confidence,
            reason="saved",
        )

    def _load_calibration(self) -> None:
        if not self._calibration_path.is_file():
            return
        try:
            data = json.loads(self._calibration_path.read_text(encoding="utf-8"))
            region = tuple(float(value) for value in data["active_region"])
            if len(region) != 4:
                raise ValueError("active_region debe tener cuatro valores")
            left, right, top, bottom = region
            if not (
                0.0 <= left < right <= 1.0
                and 0.0 <= top < bottom <= 1.0
                and right - left >= VIRTUAL_MOUSE_CALIBRATION_MIN_SPAN
                and bottom - top >= VIRTUAL_MOUSE_CALIBRATION_MIN_SPAN
            ):
                raise ValueError("La región guardada no es válida")
            self._active_region = (left, right, top, bottom)
            profile = data.get("movement_pose")
            calibration_version = int(data.get("version", 1))
            if calibration_version >= 3 and isinstance(profile, dict):
                center = [float(value) for value in profile.get("center", [])]
                tolerance = [
                    float(value) for value in profile.get("tolerance", [])
                ]
                if len(center) == 6 and len(tolerance) == 6:
                    self._movement_pose_profile = {
                        "center": center,
                        "tolerance": tolerance,
                    }
            logger.info("Calibración del mouse cargada: %s", self._active_region)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            logger.exception("No se pudo cargar la calibración del mouse")

    def _save_calibration(self) -> None:
        self._calibration_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._calibration_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(
                {
                    "version": 3,
                    "active_region": list(self._active_region),
                    "movement_pose": self._movement_pose_profile,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary_path.replace(self._calibration_path)

    def _on_camera_frame(self, event_data: Any) -> None:
        if not isinstance(event_data, dict):
            return
        timestamp = float(event_data.get("timestamp", self._clock()))
        try:
            self._handle_hotkeys(timestamp)
        except Exception as error:
            logger.exception("Error leyendo teclas del mouse virtual")
            self._publish("virtual_mouse.error", timestamp, reason=str(error))

        frame = event_data.get("frame")
        if frame is not None and self._draw_overlay_enabled:
            self._draw_status(frame)

    def set_draw_enabled(self, enabled: bool) -> None:
        self._draw_overlay_enabled = bool(enabled)

    def _handle_hotkeys(self, timestamp: float) -> None:
        toggle_down = self._controller.is_key_pressed(VIRTUAL_MOUSE_TOGGLE_KEY)
        release_down = self._controller.is_key_pressed(VIRTUAL_MOUSE_RELEASE_KEY)
        calibrate_down = self._controller.is_key_pressed(
            VIRTUAL_MOUSE_CALIBRATE_KEY
        )
        if toggle_down and not self._toggle_key_was_down:
            self.set_enabled(not self._enabled, timestamp, reason="hotkey")
        if release_down and not self._release_key_was_down:
            if self._state == VirtualMouseState.CALIBRATING:
                self.cancel_calibration(timestamp, reason="release_hotkey")
            else:
                with self._lock:
                    was_dragging = self._release_left_button(reason="release_hotkey")
                    if self._enabled:
                        self._state = VirtualMouseState.IDLE
                if was_dragging:
                    self._publish(
                        "virtual_mouse.drag_ended",
                        timestamp,
                        reason="release_hotkey",
                    )
        if calibrate_down and not self._calibrate_key_was_down:
            if self._state == VirtualMouseState.CALIBRATING:
                self.cancel_calibration(timestamp, reason="F9")
            else:
                self.start_calibration(timestamp)
        self._toggle_key_was_down = toggle_down
        self._release_key_was_down = release_down
        self._calibrate_key_was_down = calibrate_down

    def set_enabled(
        self,
        enabled: bool,
        timestamp: Optional[float] = None,
        reason: str = "manual",
    ) -> None:
        timestamp = self._clock() if timestamp is None else float(timestamp)
        was_dragging = False
        was_calibrating = False
        with self._lock:
            enabled = bool(enabled)
            if enabled == self._enabled:
                return
            if not enabled:
                was_calibrating = self._state == VirtualMouseState.CALIBRATING
                was_dragging = self._release_left_button(reason=reason)
                self._state = VirtualMouseState.DISABLED
            else:
                self._state = VirtualMouseState.IDLE
                self._reset_tracking()
            self._enabled = enabled
        if was_dragging:
            self._publish(
                "virtual_mouse.drag_ended",
                timestamp,
                reason=reason,
            )
        if was_calibrating:
            self._publish(
                "virtual_mouse.calibration_cancelled",
                timestamp,
                reason=reason,
            )
        self._publish(
            "virtual_mouse.enabled" if enabled else "virtual_mouse.disabled",
            timestamp,
            reason=reason,
        )

    def _draw_status(self, frame: Any) -> None:
        height, width = frame.shape[:2]
        with self._lock:
            state = self._state.value
            enabled = self._enabled
            point = self._latest_frame_position
            confidence = self._latest_confidence
            reason = self._suspend_reason
            calibration_message = self._calibration_message
            calibration_target_index = self._calibration_target_index
            calibration_sample_count = len(self._calibration_target_samples)
            calibration_targets = self._calibration_targets
            pose_match = self._latest_pose_match

        left, right, top, bottom = self._active_region
        cv2.rectangle(
            frame,
            (int(left * width), int(top * height)),
            (int(right * width), int(bottom * height)),
            (80, 180, 255),
            1,
        )
        if point is not None:
            cv2.circle(
                frame,
                (int(point[0] * width), int(point[1] * height)),
                8,
                (0, 255, 255),
                2,
            )

        color = (60, 220, 60) if enabled else (80, 80, 255)
        cv2.putText(
            frame,
            f"Mouse: {state} | {self._control_hand} {confidence:.2f}",
            (20, max(height - 48, 25)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.62,
            color,
            2,
            cv2.LINE_AA,
        )
        detail = "F8 ON/OFF | F9 calibrar | ESC liberar/cancelar"
        if state == VirtualMouseState.SUSPENDED.value and reason:
            detail += f" | gesto: {reason}"
        cv2.putText(
            frame,
            detail,
            (20, max(height - 20, 25)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            (220, 220, 220),
            1,
            cv2.LINE_AA,
        )
        if state == VirtualMouseState.CALIBRATING.value:
            target_radius = max(
                18,
                int(VIRTUAL_MOUSE_CALIBRATION_TARGET_RADIUS * min(width, height)),
            )
            for target_index, target in enumerate(calibration_targets):
                target_point = (int(target[0] * width), int(target[1] * height))
                if target_index < calibration_target_index:
                    target_color = (70, 220, 70)
                elif target_index == calibration_target_index:
                    target_color = (255, 140, 0)
                else:
                    target_color = (120, 120, 120)
                cv2.circle(frame, target_point, target_radius, target_color, 3)
                cv2.circle(frame, target_point, 3, target_color, cv2.FILLED)

            if (
                point is not None
                and 0 <= calibration_target_index < len(calibration_targets)
            ):
                target = calibration_targets[calibration_target_index]
                cv2.line(
                    frame,
                    (int(point[0] * width), int(point[1] * height)),
                    (int(target[0] * width), int(target[1] * height)),
                    (0, 255, 255),
                    1,
                )

            total = VIRTUAL_MOUSE_CALIBRATION_SAMPLES
            progress = (
                f"Objetivo {calibration_target_index + 1}/{len(calibration_targets)} | "
                f"muestras {calibration_sample_count}/{total}"
            )
            cv2.rectangle(frame, (12, 54), (min(width - 12, 650), 118), (0, 0, 0), -1)
            cv2.putText(
                frame,
                calibration_message,
                (20, 78),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.62,
                (0, 255, 255),
                2,
                cv2.LINE_AA,
            )
            cv2.putText(
                frame,
                progress,
                (20, 105),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.52,
                (255, 255, 255),
                1,
                cv2.LINE_AA,
            )
        elif self._movement_pose_profile is not None and pose_match is not None:
            pose_text = "Postura mouse: OK" if pose_match else "Postura mouse: NO COINCIDE"
            pose_color = (60, 220, 60) if pose_match else (0, 150, 255)
            cv2.putText(
                frame,
                pose_text,
                (20, 75),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.56,
                pose_color,
                2,
                cv2.LINE_AA,
            )

    def _select_control_hand(self, hands: Any) -> Optional[dict[str, Any]]:
        if not isinstance(hands, list):
            return None
        return next(
            (
                hand
                for hand in hands
                if str(hand.get("handedness", "")).casefold()
                == self._control_hand.casefold()
            ),
            None,
        )

    @staticmethod
    def _points_by_id(landmarks: Any) -> dict[int, tuple[float, float]]:
        if not isinstance(landmarks, list):
            return {}
        points: dict[int, tuple[float, float]] = {}
        for landmark in landmarks:
            normalized = landmark.get("normalized", {})
            if "x" in normalized and "y" in normalized:
                points[int(landmark.get("id", -1))] = (
                    float(normalized["x"]),
                    float(normalized["y"]),
                )
        return points

    @staticmethod
    def _distance(first: tuple[float, float], second: tuple[float, float]) -> float:
        return math.hypot(first[0] - second[0], first[1] - second[1])

    @staticmethod
    def _finger_extended(
        points: dict[int, tuple[float, float]],
        mcp: int,
        pip: int,
        tip: int,
    ) -> bool:
        return (
            points[tip][1] < points[pip][1] - 0.015
            and points[pip][1] < points[mcp][1] - 0.01
        )

    def _index_only_extended(self, points: dict[int, tuple[float, float]]) -> bool:
        return self._raw_index_only_extended(
            points
        ) and self._matches_movement_pose(points)

    def _stable_movement_pose(
        self,
        points: dict[int, tuple[float, float]],
    ) -> bool:
        if self._index_only_extended(points):
            self._movement_pose_hits += 1
            self._movement_pose_misses = 0
            if self._movement_pose_hits >= MOUSE_POSE_CONFIRM_FRAMES:
                self._movement_pose_active = True
        else:
            self._movement_pose_hits = 0
            self._movement_pose_misses += 1
            if self._movement_pose_misses > MOUSE_POSE_GRACE_FRAMES:
                self._movement_pose_active = False
        return self._movement_pose_active

    def _raw_index_only_extended(
        self,
        points: dict[int, tuple[float, float]],
    ) -> bool:
        return self._finger_extended(points, 5, 6, 8) and all(
            not self._finger_extended(points, mcp, pip, tip)
            for mcp, pip, tip in ((9, 10, 12), (13, 14, 16), (17, 18, 20))
        )

    def _movement_pose_features(
        self,
        points: dict[int, tuple[float, float]],
    ) -> tuple[float, ...]:
        palm_size = max(self._distance(points[0], points[9]), 1e-6)
        finger_scores = tuple(
            (points[pip][1] - points[tip][1]) / palm_size
            for pip, tip in ((6, 8), (10, 12), (14, 16), (18, 20))
        )
        return (
            *finger_scores,
            self._distance(points[4], points[8]) / palm_size,
            self._distance(points[4], points[12]) / palm_size,
        )

    @staticmethod
    def _build_movement_pose_profile(
        samples: list[tuple[float, ...]],
    ) -> dict[str, list[float]]:
        if not samples:
            raise ValueError("No hay muestras de postura para calibrar")
        columns = tuple(zip(*samples))
        center = [float(median(column)) for column in columns]
        minimum_tolerance = (0.18, 0.18, 0.18, 0.18, 0.35, 0.35)
        tolerance = []
        for index, column in enumerate(columns):
            deviations = [abs(value - center[index]) for value in column]
            tolerance.append(
                max(minimum_tolerance[index], float(median(deviations)) * 4.0)
            )
        return {"center": center, "tolerance": tolerance}

    def _matches_movement_pose(
        self,
        points: dict[int, tuple[float, float]],
    ) -> bool:
        if self._movement_pose_profile is None:
            return True
        features = self._movement_pose_features(points)
        center = self._movement_pose_profile["center"]
        tolerance = self._movement_pose_profile["tolerance"]
        return all(
            abs(value - expected) <= allowed
            for value, expected, allowed in zip(features, center, tolerance)
        )

    def _is_scroll_pose(self, points: dict[int, tuple[float, float]]) -> bool:
        return (
            self._finger_extended(points, 5, 6, 8)
            and self._finger_extended(points, 9, 10, 12)
            and not self._finger_extended(points, 13, 14, 16)
            and not self._finger_extended(points, 17, 18, 20)
        )

    def _release_left_button(self, reason: str) -> bool:
        was_dragging = self._dragging
        if self._left_pressed:
            try:
                self._controller.mouse_up()
            except Exception:
                logger.exception(
                    "No se pudo liberar el botón izquierdo (%s)",
                    reason,
                )
            finally:
                self._left_pressed = False
                self._left_release_required = True
        self._dragging = False
        return was_dragging

    def _reset_scroll(self) -> None:
        self._scroll_candidate_since = None
        self._scroll_last_y = None

    def _reset_tracking(self) -> None:
        self._warmup_frames = 0
        self._last_cursor_position = None
        self._latest_frame_position = None
        self._latest_confidence = 0.0
        self._latest_pose_match = None
        self._movement_pose_hits = 0
        self._movement_pose_misses = 0
        self._movement_pose_active = False
        self._right_pinched = False
        self._left_release_required = False
        self._reset_scroll()
        self._x_filter.reset()
        self._y_filter.reset()

    def _reset_hand_state(self, release_mouse: bool) -> None:
        was_calibrating = self._state == VirtualMouseState.CALIBRATING
        if release_mouse:
            self._release_left_button(reason="hand_unavailable")
        self._reset_tracking()
        if was_calibrating and self._enabled:
            self._state = VirtualMouseState.CALIBRATING
            self._calibration_message = "Buscando la mano derecha..."
        else:
            self._state = (
                VirtualMouseState.IDLE
                if self._enabled
                else VirtualMouseState.DISABLED
            )

    def _publish(
        self,
        event_name: str,
        timestamp: float,
        confidence: float = 0.0,
        reason: str = "",
        screen_position: Optional[tuple[int, int]] = None,
        frame_position: Optional[tuple[float, float]] = None,
        amount: Optional[int] = None,
    ) -> None:
        payload = {
            "timestamp": float(timestamp),
            "handedness": self._control_hand,
            "screen_position": screen_position or self._last_cursor_position,
            "frame_position": frame_position or self._latest_frame_position,
            "state": self._state.value,
            "confidence": float(confidence),
            "reason": reason,
        }
        if amount is not None:
            payload["amount"] = int(amount)
        self._event_bus.publish(event_name, payload)

    def close(self) -> None:
        if self._started:
            self._event_bus.unsubscribe("hand.detected", self._on_hand_detected)
            self._event_bus.unsubscribe("hand.lost", self._on_hand_lost)
            self._event_bus.unsubscribe("camera.frame", self._on_camera_frame)
        with self._lock:
            try:
                was_dragging = self._release_left_button(reason="close")
            finally:
                self._enabled = False
                self._state = VirtualMouseState.DISABLED
                self._reset_tracking()
        if was_dragging:
            self._publish(
                "virtual_mouse.drag_ended",
                self._clock(),
                reason="close",
            )
        self._publish("virtual_mouse.disabled", self._clock(), reason="close")
        self._started = False
        logger.info("Mouse virtual cerrado y botones liberados")
