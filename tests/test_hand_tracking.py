import unittest

from core.event_bus import EventBus
from modules.hand_tracking import HandTrackingModule


def landmarks_at(x: float, y: float, count: int = 21):
    return [
        {
            "id": index,
            "normalized": {"x": x, "y": y, "z": 0.0},
            "pixel": {"x": 0, "y": 0},
        }
        for index in range(count)
    ]


class FaceExclusionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = HandTrackingModule(EventBus())
        self.module._on_face_regions(
            {
                "timestamp": 10.0,
                "bounding_boxes": [
                    {"x": 0.35, "y": 0.20, "width": 0.30, "height": 0.40}
                ],
            }
        )

    def test_landmarks_contained_in_face_are_rejected(self) -> None:
        self.assertTrue(
            self.module._is_inside_recent_face(landmarks_at(0.50, 0.40), 10.2)
        )

    def test_real_hand_extending_outside_face_is_kept(self) -> None:
        points = landmarks_at(0.50, 0.40, count=10)
        points.extend(landmarks_at(0.82, 0.70, count=11))
        self.assertFalse(self.module._is_inside_recent_face(points, 10.2))

    def test_stale_face_box_does_not_hide_a_hand(self) -> None:
        self.assertFalse(
            self.module._is_inside_recent_face(landmarks_at(0.50, 0.40), 12.0)
        )


if __name__ == "__main__":
    unittest.main()
