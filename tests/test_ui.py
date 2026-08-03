import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from core.event_bus import EventBus
from core.action_registry import ActionRegistry
from core.settings_store import SettingsStore
from core.single_instance import SingleInstanceGuard
from ui.main_window import MainWindow
from ui.pages.ai_page import AIPage


class AIPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_submit_sends_the_previewed_frame_without_blocking(self):
        bus = EventBus()
        frame = np.zeros((24, 32, 3), dtype=np.uint8)
        requests = []
        bus.subscribe("vision_ai.answer_question", requests.append)
        page = AIPage(bus, lambda: frame.copy())
        page.prompt.setPlainText("¿Qué ves?")

        page.submit()

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["question"], "¿Qué ves?")
        np.testing.assert_array_equal(requests[0]["image"], frame)
        self.assertTrue(page.stop.isEnabled())
        page.close()

    def test_provider_details_are_hidden_from_normal_chat(self):
        message = AIPage._friendly_error(
            "503 UNAVAILABLE {'message': 'high demand', 'status': 'UNAVAILABLE'}"
        )
        self.assertNotIn("{'message'", message)
        self.assertIn("temporalmente", message)

    def test_chat_escapes_untrusted_html(self):
        page = AIPage(EventBus(), lambda: None)
        page._append_message("Usuario", "<script>alert(1)</script>", "#172B4D")
        source = page.chat.toHtml()
        self.assertNotIn("<script>", source.lower())
        self.assertIn("&lt;script&gt;", source.lower())
        page.close()

    def test_oversized_question_is_not_published(self):
        bus = EventBus()
        requests = []
        bus.subscribe("vision_ai.answer_question", requests.append)
        page = AIPage(bus, lambda: np.zeros((8, 8, 3), dtype=np.uint8))
        page.prompt.setPlainText("x" * 1001)
        page.submit()
        self.assertEqual([], requests)
        self.assertIn("1000", page.state.text())
        page.close()


class MainWindowStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_opens_with_completed_first_run_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = SettingsStore(Path(directory) / "settings.json")
            settings.update(
                setup_complete=True,
                gesture_actions={"OPEN_PALM": "apps.open_codex"},
            )
            modules = {
                name: MagicMock(enabled=False)
                for name in ("hands", "gestures", "mouse", "presence", "faces", "ai")
            }
            window = MainWindow(
                EventBus(), ActionRegistry(auto_discover=False), modules,
                settings=settings,
            )

            self.assertEqual(window.windowTitle(), "Room OS")
            self.assertIn("actions", window._pages)
            self.assertIn("settings", window._pages)
            window._force_quit = True
            window.close()

    def test_second_instance_requests_activation(self):
        first = SingleInstanceGuard()
        second = SingleInstanceGuard()
        activated = []
        first.set_activation_handler(lambda: activated.append(True))
        try:
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            self.app.processEvents()
            self.assertTrue(activated)
        finally:
            second.close()
            first.close()


if __name__ == "__main__":
    unittest.main()
