"""Pruebas del reconocimiento facial local con embeddings simulados."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np

from core.event_bus import EventBus
from modules.face_recognition import FaceRecognizer, PENDING, UNKNOWN
from services.face_database import FaceDatabase


AUTHORIZED_VECTOR = np.array([1.0, 0.0, 0.0], dtype=np.float32)
UNKNOWN_VECTOR = np.array([0.0, 1.0, 0.0], dtype=np.float32)


class FakeDatabase:
    def __init__(self) -> None:
        self.profiles = {
            "authorized_user": np.stack([AUTHORIZED_VECTOR] * 3),
        }

    def list_profiles(self):
        return tuple(self.profiles)

    def load_all(self):
        return dict(self.profiles)

    def load_metadata(self, profile_name):
        return {"display_name": "Test User"}


def box(x: float) -> dict[str, float]:
    return {"x": x, "y": 0.2, "width": 0.2, "height": 0.3, "confidence": 0.9}


class FaceRecognitionStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bus = EventBus()
        self.recognizer = FaceRecognizer(
            self.bus,
            database=FakeDatabase(),
            confirmation_frames=2,
            lost_timeout_seconds=1.0,
            match_threshold=0.55,
            process_every_n_frames=1,
            authorized_profile="authorized_user",
        )
        self.recognizer._reload_profiles()
        self.events: dict[str, list[dict]] = {}
        for name in (
            "detected",
            "recognized",
            "unknown",
            "lost",
            "identity_changed",
            "authorized_entered",
            "authorized_exited",
        ):
            self.events[name] = []
            self.bus.subscribe(f"face.{name}", self.events[name].append)

    def observe(self, observations, timestamp, frame_id):
        self.recognizer._process_observations(observations, timestamp, frame_id)

    def test_identity_requires_confirmation_frames(self) -> None:
        observation = [{"bounding_box": box(0.1), "embedding": AUTHORIZED_VECTOR}]
        self.observe(observation, 1.0, 1)
        self.assertEqual([], self.events["recognized"])
        track = next(iter(self.recognizer._tracks.values()))
        self.assertEqual(PENDING, track.confirmed_identity)

        self.observe(observation, 1.1, 2)
        self.assertEqual(1, len(self.events["recognized"]))
        self.assertEqual("authorized_user", self.events["recognized"][0]["identity"])
        self.assertEqual(1, len(self.events["authorized_entered"]))

    def test_low_similarity_is_unknown(self) -> None:
        observation = [{"bounding_box": box(0.1), "embedding": UNKNOWN_VECTOR}]
        self.observe(observation, 1.0, 1)
        self.observe(observation, 1.1, 2)

        self.assertEqual(UNKNOWN, self.events["unknown"][0]["identity"])
        self.assertFalse(self.events["unknown"][0]["is_authorized"])

    def test_lost_face_clears_authorized_identity(self) -> None:
        observation = [{"bounding_box": box(0.1), "embedding": AUTHORIZED_VECTOR}]
        self.observe(observation, 1.0, 1)
        self.observe(observation, 1.1, 2)
        self.observe([], 2.2, 3)

        self.assertEqual(1, len(self.events["lost"]))
        self.assertEqual(1, len(self.events["authorized_exited"]))
        self.assertEqual({}, self.recognizer._tracks)

    def test_two_people_keep_separate_tracks_and_identities(self) -> None:
        observations = [
            {"bounding_box": box(0.05), "embedding": AUTHORIZED_VECTOR},
            {"bounding_box": box(0.65), "embedding": UNKNOWN_VECTOR},
        ]
        self.observe(observations, 1.0, 1)
        self.observe(observations, 1.1, 2)

        results = sorted(
            self.recognizer._latest_results,
            key=lambda result: result["track_id"],
        )
        self.assertEqual(2, len(results))
        self.assertEqual({"authorized_user", UNKNOWN}, {r["identity"] for r in results})
        self.assertEqual(2, len({r["track_id"] for r in results}))

    def test_identity_change_is_stabilized(self) -> None:
        authorized = [{"bounding_box": box(0.1), "embedding": AUTHORIZED_VECTOR}]
        unknown = [{"bounding_box": box(0.1), "embedding": UNKNOWN_VECTOR}]
        self.observe(authorized, 1.0, 1)
        self.observe(authorized, 1.1, 2)
        self.observe(unknown, 1.2, 3)
        self.assertEqual("authorized_user", self.recognizer._latest_results[0]["identity"])
        self.observe(unknown, 1.3, 4)
        self.assertEqual(UNKNOWN, self.recognizer._latest_results[0]["identity"])
        self.assertGreaterEqual(len(self.events["identity_changed"]), 2)


class FaceRecognitionWorkerTests(unittest.TestCase):
    def test_disabled_recognition_does_not_process_faces(self) -> None:
        bus = EventBus()
        recognizer = FaceRecognizer(bus, database=FakeDatabase(), enabled=False)
        recognizer.start()
        bus.publish(
            "presence.faces",
            {"frame": np.zeros((100, 100, 3), dtype=np.uint8), "bounding_boxes": [box(0.1)]},
        )
        self.assertIsNone(recognizer._thread)
        self.assertEqual({}, recognizer._tracks)
        recognizer.close()

    def test_queue_discards_old_batches(self) -> None:
        recognizer = FaceRecognizer(EventBus(), database=FakeDatabase())
        recognizer._enqueue_latest(([], 1.0, 1))
        recognizer._enqueue_latest(([], 2.0, 2))
        queued = recognizer._queue.get_nowait()
        recognizer._queue.task_done()
        self.assertEqual(2, queued[2])

    def test_worker_closes_cleanly(self) -> None:
        recognizer = FaceRecognizer(
            EventBus(),
            database=FakeDatabase(),
            embedding_function=Mock(return_value=AUTHORIZED_VECTOR),
            process_every_n_frames=1,
        )
        recognizer.start()
        recognizer.close()
        self.assertIsNone(recognizer._thread)


class FaceDatabasePrivacyTests(unittest.TestCase):
    def test_profile_can_be_saved_without_raw_images(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            database = FaceDatabase(Path(temporary_directory))
            database.save_profile(
                "authorized_user",
                "Test User",
                [AUTHORIZED_VECTOR] * 3,
            )
            profile_path = database.profile_path("authorized_user")
            self.assertTrue((profile_path / "embeddings.npy").is_file())
            self.assertEqual([], list(profile_path.glob("image_*.jpg")))


if __name__ == "__main__":
    unittest.main()
