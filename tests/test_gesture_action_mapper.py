"""Pruebas del mapeo desacoplado entre gestos y acciones."""

import threading
import unittest

from core.action_engine import ACTION_EXECUTE_EVENT
from core.event_bus import EventBus
from core.gesture_action_mapper import GestureActionMapper


class GestureActionMapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bus = EventBus()
        self.received: list[dict] = []
        self.received_event = threading.Event()

        def receive(payload: dict) -> None:
            self.received.append(payload)
            self.received_event.set()

        self.bus.subscribe(ACTION_EXECUTE_EVENT, receive)
        self.mapper = GestureActionMapper(
            self.bus,
            gesture_map={
                "PEACE": "apps.open_apple_music",
                "THUMBS_UP": "media.play",
                "THUMBS_DOWN": "media.pause",
                "OPEN_PALM": "apps.open_codex",
                "SPIDERMAN": "apps.open_browser",
            },
            cooldown_seconds=10.0,
            startup_grace_seconds=0.0,
        )
        self.mapper.start()

    def tearDown(self) -> None:
        self.mapper.close()

    def publish_and_wait(self, gesture: str, event_name: str = "gesture.started") -> dict:
        self.received_event.clear()
        self.bus.publish(
            event_name,
            {
                "gesture": gesture,
                "handedness": "Right",
                "confidence": 0.9,
                "timestamp": 10.0,
            },
        )
        self.assertTrue(self.received_event.wait(1.0))
        return self.received[-1]

    def test_requested_gestures_map_to_expected_actions(self) -> None:
        expected = {
            "PEACE": "apps.open_apple_music",
            "THUMBS_UP": "media.play",
            "THUMBS_DOWN": "media.pause",
            "OPEN_PALM": "apps.open_codex",
            "SPIDERMAN": "apps.open_browser",
        }
        for gesture, action_id in expected.items():
            with self.subTest(gesture=gesture):
                request = self.publish_and_wait(gesture)
                self.assertEqual(action_id, request["action_id"])
                self.assertEqual("gesture", request["context"]["source"])

    def test_held_does_not_repeat_action(self) -> None:
        self.publish_and_wait("PEACE")
        count = len(self.received)
        self.bus.publish("gesture.held", {"gesture": "PEACE"})
        self.assertEqual(count, len(self.received))

    def test_cooldown_prevents_duplicate_request(self) -> None:
        self.publish_and_wait("PEACE")
        count = len(self.received)
        self.bus.publish("gesture.changed", {"gesture": "PEACE"})
        self.assertEqual(count, len(self.received))

    def test_unknown_gesture_has_no_action(self) -> None:
        self.bus.publish("gesture.started", {"gesture": "FIST"})
        self.assertFalse(self.received_event.wait(0.05))

    def test_calibration_temporarily_pauses_gesture_actions(self) -> None:
        self.received_event.clear()
        self.bus.publish("virtual_mouse.calibration_started", {"timestamp": 1.0})
        self.bus.publish("gesture.started", {"gesture": "SPIDERMAN"})
        self.assertFalse(self.received_event.wait(0.05))

        self.bus.publish("virtual_mouse.calibration_completed", {"timestamp": 2.0})
        request = self.publish_and_wait("SPIDERMAN")
        self.assertEqual("apps.open_browser", request["action_id"])

    def test_mouse_mode_blocks_actions_until_disabled(self) -> None:
        self.received_event.clear()
        self.bus.publish("virtual_mouse.enabled", {"timestamp": 1.0})
        self.bus.publish("gesture.started", {"gesture": "THUMBS_UP"})
        self.assertFalse(self.received_event.wait(0.05))

        self.bus.publish("virtual_mouse.disabled", {"timestamp": 2.0})
        request = self.publish_and_wait("THUMBS_UP")
        self.assertEqual("media.play", request["action_id"])


if __name__ == "__main__":
    unittest.main()
