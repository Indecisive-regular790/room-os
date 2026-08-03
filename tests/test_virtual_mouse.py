"""Pruebas unitarias seguras del mouse virtual."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.event_bus import EventBus
from modules.virtual_mouse import (
    OneEuroFilter,
    VirtualMouse,
    VirtualMouseState,
    normalized_to_screen,
)
from platforms.windows.mouse_control import WindowsMouseControl


def make_hand(
    extended_fingers: tuple[str, ...] = ("index",),
    pinch: str | None = None,
    handedness: str = "Right",
    confidence: float = 0.95,
) -> dict:
    points = [(0.5, 0.75) for _ in range(21)]
    points[0] = (0.5, 0.90)
    finger_ids = {
        "index": (5, 6, 7, 8, 0.43),
        "middle": (9, 10, 11, 12, 0.50),
        "ring": (13, 14, 15, 16, 0.57),
        "pinky": (17, 18, 19, 20, 0.64),
    }
    for name, (mcp, pip, dip, tip, x) in finger_ids.items():
        points[mcp] = (x, 0.64)
        if name in extended_fingers:
            points[pip] = (x, 0.48)
            points[dip] = (x, 0.34)
            points[tip] = (x, 0.20)
        else:
            points[pip] = (x, 0.52)
            points[dip] = (x, 0.61)
            points[tip] = (x, 0.68)

    points[1] = (0.44, 0.78)
    points[2] = (0.42, 0.70)
    points[3] = (0.44, 0.64)
    points[4] = (0.48, 0.66)
    if pinch == "left":
        points[4] = (points[8][0] + 0.01, points[8][1] + 0.01)
    elif pinch == "right":
        points[12] = (0.50, 0.57)
        points[4] = (points[12][0] + 0.01, points[12][1] + 0.01)
    elif pinch == "both":
        points[8] = (0.46, 0.30)
        points[12] = (0.48, 0.30)
        points[4] = (0.47, 0.31)

    landmarks = [
        {
            "id": landmark_id,
            "normalized": {"x": x, "y": y, "z": 0.0},
            "pixel": {"x": int(x * 640), "y": int(y * 480)},
        }
        for landmark_id, (x, y) in enumerate(points)
    ]
    return {
        "handedness": handedness,
        "confidence": confidence,
        "landmarks": landmarks,
    }


def translate_hand_y(hand: dict, amount: float) -> dict:
    for landmark in hand["landmarks"]:
        landmark["normalized"]["y"] += amount
    return hand


def move_index_to(hand: dict, x: float, y: float) -> dict:
    current = hand["landmarks"][8]["normalized"]
    delta_x = x - current["x"]
    delta_y = y - current["y"]
    for landmark in hand["landmarks"]:
        landmark["normalized"]["x"] += delta_x
        landmark["normalized"]["y"] += delta_y
    return hand


class CoordinateAndFilterTests(unittest.TestCase):
    def test_coordinate_conversion_and_limits(self) -> None:
        region = (0.15, 0.85, 0.15, 0.85)
        self.assertEqual(
            (0, 0),
            normalized_to_screen(0.15, 0.15, (1920, 1080), region, False),
        )
        self.assertEqual(
            (1919, 1079),
            normalized_to_screen(0.85, 0.85, (1920, 1080), region, False),
        )
        self.assertIsNone(
            normalized_to_screen(0.10, 0.50, (1920, 1080), region, False)
        )

    def test_horizontal_inversion(self) -> None:
        region = (0.0, 1.0, 0.0, 1.0)
        normal = normalized_to_screen(0.25, 0.5, (100, 100), region, False)
        mirrored = normalized_to_screen(0.25, 0.5, (100, 100), region, True)
        self.assertEqual(25, normal[0])
        self.assertEqual(74, mirrored[0])

    def test_one_euro_filter_smooths_changes(self) -> None:
        filter_ = OneEuroFilter(min_cutoff=1.0, beta=0.0, smoothing_factor=0.25)
        self.assertEqual(0.0, filter_.filter(0.0, 1.0))
        filtered = filter_.filter(100.0, 1.1)
        self.assertGreater(filtered, 0.0)
        self.assertLess(filtered, 100.0)


class VirtualMouseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.constants = patch.multiple(
            "modules.virtual_mouse",
            HAND_WARMUP_FRAMES=1,
            MOUSE_SMOOTHING_ENABLED=False,
            MOUSE_DEAD_ZONE_PIXELS=0,
            MOUSE_POSE_CONFIRM_FRAMES=1,
            MOUSE_POSE_GRACE_FRAMES=2,
            SCROLL_ACTIVATION_HOLD_SECONDS=1.0,
            GESTURE_SUSPEND_DELAY_SECONDS=0.4,
            VIRTUAL_MOUSE_CALIBRATION_SAMPLES=2,
            VIRTUAL_MOUSE_CALIBRATION_SETTLE_FRAMES=0,
            VIRTUAL_MOUSE_CALIBRATION_MIN_SPAN=0.2,
            VIRTUAL_MOUSE_CALIBRATION_TARGET_RADIUS=0.06,
            VIRTUAL_MOUSE_CALIBRATION_TARGETS=(
                (0.20, 0.30),
                (0.70, 0.30),
                (0.45, 0.20),
                (0.45, 0.50),
            ),
        )
        self.constants.start()
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.calibration_path = (
            Path(self.temporary_directory.name) / "calibration.json"
        )
        self.bus = EventBus()
        self.controller = Mock(spec=WindowsMouseControl)
        self.controller.get_screen_size.return_value = (1920, 1080)
        self.controller.is_key_pressed.return_value = False
        self.mouse = VirtualMouse(
            self.bus,
            controller=self.controller,
            enabled=True,
            calibration_path=self.calibration_path,
        )
        self.mouse.start()
        self.events: dict[str, list[dict]] = {}
        for name in (
            "left_click",
            "right_click",
            "drag_started",
            "drag_ended",
            "scroll",
            "suspended",
            "error",
            "enabled",
            "disabled",
            "calibration_started",
            "calibration_completed",
            "calibration_cancelled",
        ):
            self.events[name] = []
            self.bus.subscribe(f"virtual_mouse.{name}", self.events[name].append)

    def tearDown(self) -> None:
        self.mouse.close()
        self.temporary_directory.cleanup()
        self.constants.stop()

    def publish_hand(self, hand: dict, timestamp: float) -> None:
        self.bus.publish("hand.detected", {"hands": [hand], "timestamp": timestamp})

    def start_drag(self) -> None:
        pinch = make_hand(pinch="left")
        self.publish_hand(pinch, 1.0)
        self.publish_hand(pinch, 1.6)

    def test_index_moves_cursor(self) -> None:
        self.publish_hand(make_hand(), 1.0)
        self.controller.move_cursor.assert_called_once()
        self.assertEqual(VirtualMouseState.MOVING, self.mouse.state)

    def test_movement_pose_survives_brief_landmark_noise(self) -> None:
        good = VirtualMouse._points_by_id(make_hand()["landmarks"])
        noisy = VirtualMouse._points_by_id(
            make_hand(extended_fingers=("index", "ring"))["landmarks"]
        )
        self.assertTrue(self.mouse._stable_movement_pose(good))
        self.assertTrue(self.mouse._stable_movement_pose(noisy))
        self.assertTrue(self.mouse._stable_movement_pose(noisy))
        self.assertFalse(self.mouse._stable_movement_pose(noisy))

    def test_dead_zone_avoids_micro_movements(self) -> None:
        with patch("modules.virtual_mouse.MOUSE_DEAD_ZONE_PIXELS", 20):
            first = make_hand()
            second = make_hand()
            second["landmarks"][8]["normalized"]["x"] += 0.001
            self.publish_hand(first, 1.0)
            self.publish_hand(second, 1.1)
        self.controller.move_cursor.assert_called_once()

    def test_pinch_generates_one_click_after_release(self) -> None:
        pinch = make_hand(pinch="left")
        self.publish_hand(pinch, 1.0)
        self.publish_hand(pinch, 1.1)
        self.publish_hand(make_hand(), 1.2)
        self.publish_hand(make_hand(), 1.3)

        self.controller.mouse_down.assert_called_once()
        self.controller.mouse_up.assert_called_once()
        self.assertEqual(1, len(self.events["left_click"]))

    def test_sustained_pinch_starts_and_ends_drag(self) -> None:
        self.start_drag()
        self.assertEqual(VirtualMouseState.DRAGGING, self.mouse.state)
        self.assertEqual(1, len(self.events["drag_started"]))

        self.publish_hand(make_hand(), 1.7)

        self.assertEqual(1, len(self.events["drag_ended"]))
        self.controller.mouse_up.assert_called_once()

    def test_losing_hand_ends_drag(self) -> None:
        self.start_drag()
        self.bus.publish("hand.lost", {"timestamp": 1.7})

        self.controller.mouse_up.assert_called_once()
        self.assertEqual(1, len(self.events["drag_ended"]))

    def test_middle_pinch_generates_right_click(self) -> None:
        self.publish_hand(make_hand(pinch="right"), 1.0)
        self.publish_hand(make_hand(pinch="right"), 1.1)

        self.controller.right_click.assert_called_once()
        self.controller.mouse_down.assert_not_called()
        self.assertEqual(1, len(self.events["right_click"]))

    def test_right_click_has_priority_when_pinches_overlap(self) -> None:
        self.publish_hand(
            make_hand(extended_fingers=("index", "middle"), pinch="both"),
            1.0,
        )
        self.controller.right_click.assert_called_once()
        self.controller.mouse_down.assert_not_called()

    def test_scroll_requires_hold_and_peace_does_not_scroll_immediately(self) -> None:
        peace = make_hand(extended_fingers=("index", "middle"))
        self.publish_hand(peace, 1.0)
        self.publish_hand(peace, 1.5)
        self.controller.scroll.assert_not_called()

        self.publish_hand(peace, 2.1)
        moved = translate_hand_y(
            make_hand(extended_fingers=("index", "middle")),
            -0.05,
        )
        self.publish_hand(moved, 2.2)
        self.controller.scroll.assert_called_once()

    def test_general_gesture_does_not_interrupt_mouse_mode(self) -> None:
        self.bus.publish(
            "gesture.started",
            {"gesture": "OPEN_PALM", "timestamp": 1.0, "confidence": 0.9},
        )
        self.publish_hand(make_hand(), 1.1)

        self.assertNotEqual(VirtualMouseState.SUSPENDED, self.mouse.state)
        self.assertEqual(0, len(self.events["suspended"]))

    def test_f8_toggles_mouse(self) -> None:
        self.controller.is_key_pressed.side_effect = [True, False, False]
        self.mouse._handle_hotkeys(1.0)
        self.assertFalse(self.mouse.enabled)
        self.assertEqual(1, len(self.events["disabled"]))

        self.controller.is_key_pressed.side_effect = [False, False, False]
        self.mouse._handle_hotkeys(1.1)
        self.controller.is_key_pressed.side_effect = [True, False, False]
        self.mouse._handle_hotkeys(1.2)
        self.assertTrue(self.mouse.enabled)
        self.assertEqual(1, len(self.events["enabled"]))

    def test_escape_releases_drag(self) -> None:
        self.start_drag()
        self.controller.is_key_pressed.side_effect = [False, True, False]
        self.mouse._handle_hotkeys(1.7)
        self.controller.mouse_up.assert_called_once()
        self.assertEqual(VirtualMouseState.IDLE, self.mouse.state)

    def test_f9_starts_and_escape_cancels_calibration(self) -> None:
        self.controller.is_key_pressed.side_effect = [False, False, True]
        self.mouse._handle_hotkeys(1.0)
        self.assertEqual(VirtualMouseState.CALIBRATING, self.mouse.state)
        self.assertEqual(1, len(self.events["calibration_started"]))

        self.controller.is_key_pressed.side_effect = [False, True, False]
        self.mouse._handle_hotkeys(1.1)
        self.assertEqual(VirtualMouseState.IDLE, self.mouse.state)
        self.assertEqual(1, len(self.events["calibration_cancelled"]))

    def test_calibration_survives_gestures_and_temporary_hand_loss(self) -> None:
        self.mouse.start_calibration(1.0)
        self.bus.publish(
            "gesture.started",
            {"gesture": "OPEN_PALM", "timestamp": 1.1, "confidence": 0.9},
        )
        self.assertEqual(VirtualMouseState.CALIBRATING, self.mouse.state)

        self.publish_hand(make_hand(handedness="Left"), 1.2)
        self.assertEqual(VirtualMouseState.CALIBRATING, self.mouse.state)

        self.publish_hand(make_hand(confidence=0.3), 1.3)
        self.assertEqual(VirtualMouseState.CALIBRATING, self.mouse.state)

        self.bus.publish("hand.lost", {"timestamp": 1.4})
        self.assertEqual(VirtualMouseState.CALIBRATING, self.mouse.state)

    def test_guided_calibration_is_saved_and_loaded(self) -> None:
        self.mouse.start_calibration(1.0)
        samples = (
            (0.20, 0.30),
            (0.70, 0.30),
            (0.45, 0.20),
            (0.45, 0.50),
        )
        timestamp = 1.1
        for x, y in samples:
            for _ in range(2):
                self.publish_hand(move_index_to(make_hand(), x, y), timestamp)
                timestamp += 0.1

        self.assertEqual(VirtualMouseState.IDLE, self.mouse.state)
        self.assertEqual(1, len(self.events["calibration_completed"]))
        self.assertTrue(self.calibration_path.is_file())
        self.assertEqual((0.2, 0.7, 0.2, 0.5), self.mouse._active_region)
        self.assertIsNotNone(self.mouse._movement_pose_profile)

        movement_pose = VirtualMouse._points_by_id(make_hand()["landmarks"])
        confusing_pose = VirtualMouse._points_by_id(make_hand()["landmarks"])
        for tip_id in (12, 16, 20):
            x, _ = confusing_pose[tip_id]
            confusing_pose[tip_id] = (x, 0.55)
        self.assertTrue(self.mouse._index_only_extended(movement_pose))
        self.assertFalse(self.mouse._index_only_extended(confusing_pose))

        second_controller = Mock(spec=WindowsMouseControl)
        second_controller.get_screen_size.return_value = (1920, 1080)
        second_controller.is_key_pressed.return_value = False
        second_mouse = VirtualMouse(
            EventBus(),
            controller=second_controller,
            calibration_path=self.calibration_path,
        )
        second_mouse.start()
        self.assertEqual((0.2, 0.7, 0.2, 0.5), second_mouse._active_region)
        self.assertIsNotNone(second_mouse._movement_pose_profile)
        second_mouse.close()

    def test_exception_releases_pressed_button(self) -> None:
        pinch = make_hand(pinch="left")
        self.publish_hand(pinch, 1.0)
        self.controller.move_cursor.side_effect = OSError("simulated move error")
        self.publish_hand(pinch, 1.1)

        self.controller.mouse_up.assert_called_once()
        self.assertEqual(1, len(self.events["error"]))

    def test_left_hand_is_ignored(self) -> None:
        self.publish_hand(make_hand(handedness="Left"), 1.0)
        self.controller.move_cursor.assert_not_called()

    def test_low_confidence_is_ignored(self) -> None:
        self.publish_hand(make_hand(confidence=0.4), 1.0)
        self.controller.move_cursor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
