"""Pruebas de presencia sin usar cámara real."""

import time
import unittest
from unittest.mock import Mock

import numpy as np

from core.event_bus import EventBus
from modules.presence_detection import PresenceDetector, PresenceState


def box(x: float = 0.2, confidence: float = 0.9) -> dict[str, float]:
    return {
        "x": x,
        "y": 0.2,
        "width": 0.2,
        "height": 0.3,
        "confidence": confidence,
    }


class PresenceStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bus = EventBus()
        self.detector = PresenceDetector(
            self.bus,
            detector=Mock(),
            enter_frames=2,
            exit_timeout_seconds=2.0,
        )
        self.events: dict[str, list[dict]] = {}
        for name in (
            "entered",
            "exited",
            "updated",
            "multiple_people",
            "temporarily_lost",
            "restored",
        ):
            self.events[name] = []
            self.bus.subscribe(f"presence.{name}", self.events[name].append)

    def observe(self, boxes: list[dict], timestamp: float, frame_id: int) -> None:
        self.detector._process_observation(boxes, timestamp, frame_id)

    def test_person_enters_after_consecutive_frames(self) -> None:
        self.observe([box()], 1.0, 1)
        self.assertEqual(PresenceState.EMPTY, self.detector.state)
        self.observe([box()], 1.1, 2)

        self.assertEqual(PresenceState.PERSON_PRESENT, self.detector.state)
        self.assertEqual(1, len(self.events["entered"]))
        self.assertEqual(1, self.events["entered"][0]["person_count"])

    def test_brief_loss_restores_without_exit(self) -> None:
        self.observe([box()], 1.0, 1)
        self.observe([box()], 1.1, 2)
        self.observe([], 1.5, 3)

        self.assertEqual(PresenceState.TEMPORARILY_LOST, self.detector.state)
        self.assertEqual(1, len(self.events["temporarily_lost"]))
        self.assertEqual([], self.events["exited"])

        self.observe([box()], 1.7, 4)
        self.assertEqual(PresenceState.PERSON_PRESENT, self.detector.state)
        self.assertEqual(1, len(self.events["restored"]))

    def test_person_exits_after_timeout(self) -> None:
        self.observe([box()], 1.0, 1)
        self.observe([box()], 1.1, 2)
        self.observe([], 1.5, 3)
        self.observe([], 3.2, 4)

        self.assertEqual(PresenceState.EMPTY, self.detector.state)
        self.assertEqual(1, len(self.events["exited"]))
        self.assertEqual(1, len(self.detector.get_history()))

    def test_multiple_people_event(self) -> None:
        self.observe([box()], 1.0, 1)
        self.observe([box()], 1.1, 2)
        self.observe([box(0.1), box(0.6)], 1.2, 3)

        self.assertEqual(PresenceState.MULTIPLE_PEOPLE, self.detector.state)
        self.assertEqual(1, len(self.events["multiple_people"]))
        self.assertEqual(2, self.events["multiple_people"][0]["person_count"])

    def test_updated_event_is_throttled(self) -> None:
        self.observe([box()], 1.0, 1)
        self.observe([box()], 1.1, 2)
        self.observe([box()], 1.2, 3)
        self.assertEqual(1, len(self.events["updated"]))


class PresenceWorkerTests(unittest.TestCase):
    def test_queue_keeps_latest_frame(self) -> None:
        detector = PresenceDetector(EventBus(), detector=Mock())
        first = (np.zeros((4, 4, 3), dtype=np.uint8), 1.0, 1)
        second = (np.ones((4, 4, 3), dtype=np.uint8), 2.0, 2)
        detector._enqueue_latest(first)
        detector._enqueue_latest(second)
        queued = detector._queue.get_nowait()
        detector._queue.task_done()
        self.assertEqual(2, queued[2])

    def test_disabled_presence_has_no_worker(self) -> None:
        detector = PresenceDetector(EventBus(), detector=Mock(), enabled=False)
        detector.start()
        self.assertIsNone(detector._thread)
        detector.close()

    def test_worker_closes(self) -> None:
        backend = Mock()
        backend.detect.return_value = []
        detector = PresenceDetector(
            EventBus(),
            detector=backend,
            process_every_n_frames=1,
        )
        detector.start()
        detector._enqueue_latest((np.zeros((8, 8, 3), dtype=np.uint8), time.perf_counter(), 1))
        detector.close()
        self.assertIsNone(detector._thread)


if __name__ == "__main__":
    unittest.main()
