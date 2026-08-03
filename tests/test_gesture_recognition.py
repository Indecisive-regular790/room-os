"""Pruebas unitarias del reconocimiento geométrico de gestos."""

import unittest

from core.event_bus import EventBus
from modules.gesture_recognition import (
    FIST,
    OPEN_PALM,
    PEACE,
    PINCH,
    POINT,
    SPIDERMAN,
    THUMBS_DOWN,
    THUMBS_UP,
    UNKNOWN,
    GestureRecognitionModule,
    classify_gesture,
)


def make_hand(
    extended_fingers: tuple[str, ...] = (),
    thumb: str = "folded",
) -> list[dict]:
    """Construye 21 landmarks simples para probar reglas sin cámara."""
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
    if thumb == "open":
        points[2] = (0.36, 0.68)
        points[3] = (0.28, 0.62)
        points[4] = (0.20, 0.56)
    elif thumb == "up":
        points[2] = (0.46, 0.64)
        points[3] = (0.45, 0.45)
        points[4] = (0.44, 0.25)
    elif thumb == "down":
        points[2] = (0.46, 0.64)
        points[3] = (0.45, 0.76)
        points[4] = (0.44, 0.90)
    else:
        points[2] = (0.42, 0.70)
        points[3] = (0.44, 0.64)
        points[4] = (0.48, 0.66)

    return [
        {
            "id": landmark_id,
            "normalized": {"x": x, "y": y, "z": 0.0},
            "pixel": {"x": int(x * 640), "y": int(y * 480)},
        }
        for landmark_id, (x, y) in enumerate(points)
    ]


def make_pinch() -> list[dict]:
    landmarks = make_hand(
        extended_fingers=("index", "middle", "ring", "pinky"),
        thumb="open",
    )
    index_tip = landmarks[8]["normalized"]
    landmarks[4]["normalized"]["x"] = index_tip["x"] + 0.01
    landmarks[4]["normalized"]["y"] = index_tip["y"] + 0.01
    landmarks[4]["pixel"]["x"] = int((index_tip["x"] + 0.01) * 640)
    landmarks[4]["pixel"]["y"] = int((index_tip["y"] + 0.01) * 480)
    return landmarks


def scale_hand(landmarks: list[dict], factor: float) -> list[dict]:
    """Reduce una mano alrededor del centro para simular mayor distancia."""
    scaled = []
    for landmark in landmarks:
        normalized = landmark["normalized"]
        x = 0.5 + (normalized["x"] - 0.5) * factor
        y = 0.5 + (normalized["y"] - 0.5) * factor
        scaled.append(
            {
                "id": landmark["id"],
                "normalized": {"x": x, "y": y, "z": 0.0},
                "pixel": {"x": int(x * 640), "y": int(y * 480)},
            }
        )
    return scaled


class GestureClassificationTests(unittest.TestCase):
    def assert_gesture(
        self,
        expected: str,
        landmarks: list[dict],
        handedness: str | None = None,
    ) -> None:
        gesture, confidence = classify_gesture(landmarks, handedness)
        self.assertEqual(expected, gesture)
        if expected == UNKNOWN:
            self.assertEqual(0.0, confidence)
        else:
            self.assertGreater(confidence, 0.0)

    def test_open_palm(self) -> None:
        self.assert_gesture(
            OPEN_PALM,
            make_hand(("index", "middle", "ring", "pinky"), "open"),
        )

    def test_open_palm_requires_front_of_right_hand(self) -> None:
        front = make_hand(("index", "middle", "ring", "pinky"), "open")
        back = make_hand(("index", "middle", "ring", "pinky"), "open")
        for landmark_id in range(21):
            mirrored_x = 1.0 - front[landmark_id]["normalized"]["x"]
            back[landmark_id]["normalized"]["x"] = mirrored_x
            back[landmark_id]["pixel"]["x"] = int(mirrored_x * 640)

        self.assert_gesture(OPEN_PALM, front, "Right")
        self.assert_gesture(UNKNOWN, back, "Right")

    def test_open_palm_requires_front_of_left_hand(self) -> None:
        right_front = make_hand(("index", "middle", "ring", "pinky"), "open")
        left_front = make_hand(("index", "middle", "ring", "pinky"), "open")
        for landmark_id, landmark in enumerate(left_front):
            mirrored_x = 1.0 - right_front[landmark_id]["normalized"]["x"]
            landmark["normalized"]["x"] = mirrored_x
            landmark["pixel"]["x"] = int(mirrored_x * 640)

        left_back = make_hand(("index", "middle", "ring", "pinky"), "open")

        self.assert_gesture(OPEN_PALM, left_front, "Left")
        self.assert_gesture(UNKNOWN, left_back, "Left")

    def test_open_palm_does_not_require_thumb_to_be_fully_spread(self) -> None:
        hand = make_hand(("index", "middle", "ring", "pinky"), "folded")

        self.assert_gesture(OPEN_PALM, hand, "Right")

    def test_fist(self) -> None:
        self.assert_gesture(FIST, make_hand())

    def test_point(self) -> None:
        self.assert_gesture(POINT, make_hand(("index",)))

    def test_peace(self) -> None:
        self.assert_gesture(PEACE, make_hand(("index", "middle")))

    def test_thumbs_up(self) -> None:
        self.assert_gesture(THUMBS_UP, make_hand(thumb="up"))

    def test_thumbs_up_at_distance_is_not_fist(self) -> None:
        self.assert_gesture(THUMBS_UP, scale_hand(make_hand(thumb="up"), 0.30))

    def test_thumbs_down(self) -> None:
        self.assert_gesture(THUMBS_DOWN, make_hand(thumb="down"))

    def test_open_palm_at_distance(self) -> None:
        hand = make_hand(("index", "middle", "ring", "pinky"), "open")
        self.assert_gesture(OPEN_PALM, scale_hand(hand, 0.30), "Right")

    def test_spiderman(self) -> None:
        self.assert_gesture(SPIDERMAN, make_hand(("index", "pinky")))

    def test_pinch(self) -> None:
        self.assert_gesture(PINCH, make_pinch())

    def test_unknown(self) -> None:
        self.assert_gesture(UNKNOWN, make_hand(("middle",)))


class GestureEventTests(unittest.TestCase):
    def test_stabilized_lifecycle(self) -> None:
        bus = EventBus()
        module = GestureRecognitionModule(
            bus,
            confirmation_frames=3,
            missing_frames=2,
            held_interval_seconds=0.0,
        )
        received = {name: [] for name in ("started", "held", "changed", "ended")}
        for event_name in received:
            bus.subscribe(f"gesture.{event_name}", received[event_name].append)
        module.start()

        open_hand = {
            "handedness": "Right",
            "confidence": 0.95,
            "landmarks": make_hand(
                ("index", "middle", "ring", "pinky"),
                "open",
            ),
        }
        fist_hand = {
            "handedness": "Right",
            "confidence": 0.95,
            "landmarks": make_hand(),
        }

        for timestamp in (1.0, 2.0):
            bus.publish("hand.detected", {"timestamp": timestamp, "hands": [open_hand]})
        self.assertEqual([], received["started"])

        bus.publish("hand.detected", {"timestamp": 3.0, "hands": [open_hand]})
        self.assertEqual(1, len(received["started"]))
        self.assertEqual(OPEN_PALM, received["started"][0]["gesture"])

        bus.publish("hand.detected", {"timestamp": 4.0, "hands": [open_hand]})
        self.assertEqual(1, len(received["held"]))

        for timestamp in (5.0, 6.0, 7.0):
            bus.publish("hand.detected", {"timestamp": timestamp, "hands": [fist_hand]})
        self.assertEqual(1, len(received["changed"]))
        self.assertEqual(FIST, received["changed"][0]["gesture"])
        self.assertEqual(OPEN_PALM, received["changed"][0]["previous_gesture"])

        bus.publish("hand.lost", {"timestamp": 8.0})
        self.assertEqual(1, len(received["ended"]))
        payload = received["ended"][0]
        for field_name in (
            "gesture",
            "handedness",
            "confidence",
            "duration",
            "position",
            "timestamp",
        ):
            self.assertIn(field_name, payload)
        self.assertIn("normalized", payload["position"])
        self.assertIn("pixel", payload["position"])
        self.assertGreater(payload["confidence"], 0.0)

        module.close()


if __name__ == "__main__":
    unittest.main()
