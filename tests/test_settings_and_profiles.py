import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import runtime_paths
from core.gesture_profiles import GestureProfileStore
from core.settings_store import SettingsStore


def sample_landmarks(offset: float = 0.0):
    landmarks = []
    for index in range(21):
        landmarks.append(
            {
                "id": index,
                "normalized": {
                    "x": 0.4 + (index % 4) * 0.025 + offset,
                    "y": 0.7 - index * 0.012,
                    "z": 0.0,
                },
                "pixel": {"x": 0, "y": 0},
            }
        )
    return landmarks


class SettingsStoreTests(unittest.TestCase):
    def test_packaged_assets_resolve_from_pyinstaller_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(runtime_paths.sys, "frozen", True, create=True), patch.object(
                runtime_paths.sys, "_MEIPASS", directory, create=True
            ):
                self.assertEqual(
                    Path(directory) / "assets" / "room_os_logo.png",
                    runtime_paths.asset_path("room_os_logo.png"),
                )

    def test_first_run_and_mapping_persist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            store = SettingsStore(path)
            self.assertFalse(store.get("setup_complete"))
            store.update(
                setup_complete=True,
                gesture_actions={"PEACE": "media.play_pause"},
            )
            loaded = SettingsStore(path)
            self.assertTrue(loaded.get("setup_complete"))
            self.assertEqual(
                {"PEACE": "media.play_pause"},
                loaded.get("gesture_actions"),
            )

    def test_corrupt_settings_are_preserved_and_defaults_are_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text("{not valid json", encoding="utf-8")

            store = SettingsStore(path)

            self.assertFalse(store.get("setup_complete"))
            backups = list(path.parent.glob("settings.corrupt-*.json"))
            self.assertEqual(1, len(backups))
            self.assertEqual(
                "{not valid json", backups[0].read_text(encoding="utf-8")
            )


class GestureProfileStoreTests(unittest.TestCase):
    def test_training_stores_landmarks_without_images_and_matches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            store = GestureProfileStore(path)
            samples = [sample_landmarks(index * 0.0001) for index in range(20)]
            profile = store.train("PEACE", "Right", samples)
            self.assertEqual(20, profile["sample_count"])
            self.assertNotIn("image", path.read_text(encoding="utf-8"))
            match = GestureProfileStore(path).match(sample_landmarks(), "Right")
            self.assertIsNotNone(match)
            self.assertEqual("PEACE", match[0])

    def test_profiles_are_separate_for_each_hand(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = GestureProfileStore(Path(directory) / "profiles.json")
            store.train("FIST", "Left", [sample_landmarks() for _ in range(12)])
            self.assertIsNone(store.match(sample_landmarks(), "Right"))


if __name__ == "__main__":
    unittest.main()
