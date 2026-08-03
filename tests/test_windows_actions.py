"""Pruebas seguras y mockeadas de las acciones Windows."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.action_engine import ActionEngine
from core.action_registry import ActionRegistry
from core.actions.app_actions import OpenAppleMusicAction, OpenVSCodeAction
from core.actions.media_actions import PauseMediaAction, PlayMediaAction, PlayPauseAction
from core.actions.system_actions import LockSystemAction, ShutdownSystemAction
from core.event_bus import EventBus
from platforms.windows.app_control import (
    AppNotAllowedError,
    AppNotInstalledError,
    WindowsAppControl,
)
from platforms.windows.media_control import (
    VK_MEDIA_PLAY_PAUSE,
    VK_VOLUME_UP,
    WindowsMediaControl,
)
from platforms.windows.system_control import WindowsSystemControl
from platforms.windows.window_control import WindowsWindowControl


class WindowsSystemActionTests(unittest.TestCase):
    def make_engine(self, action) -> ActionEngine:
        registry = ActionRegistry(auto_discover=False)
        registry.register(action)
        return ActionEngine(EventBus(), registry)

    def test_lock_windows_uses_controller_mock(self) -> None:
        controller = Mock(spec=WindowsSystemControl)
        controller.lock.return_value = {"message": "locked", "metadata": {}}
        engine = self.make_engine(LockSystemAction(controller=controller))

        result = engine.execute("system.lock")

        self.assertTrue(result.success)
        controller.lock.assert_called_once_with()

    def test_shutdown_without_confirmation_is_rejected(self) -> None:
        controller = Mock(spec=WindowsSystemControl)
        engine = self.make_engine(
            ShutdownSystemAction(
                controller=controller,
                allow_shutdown=True,
                delay_seconds=15,
            )
        )

        result = engine.execute("system.shutdown")

        self.assertFalse(result.success)
        self.assertEqual("validation_failed", result.status)
        self.assertEqual("ActionValidationError", result.error_type)
        controller.schedule_shutdown.assert_not_called()

    def test_shutdown_with_confirmation_uses_mock(self) -> None:
        controller = Mock(spec=WindowsSystemControl)
        controller.schedule_shutdown.return_value = {
            "message": "scheduled",
            "metadata": {"delay_seconds": 15},
        }
        engine = self.make_engine(
            ShutdownSystemAction(
                controller=controller,
                allow_shutdown=True,
                delay_seconds=15,
            )
        )

        result = engine.execute("system.shutdown", {"confirmed": True})

        self.assertTrue(result.success)
        controller.schedule_shutdown.assert_called_once_with(15)
        self.assertTrue(result.metadata["dangerous"])

    def test_operating_system_error_is_captured(self) -> None:
        controller = Mock()
        controller.play_pause.side_effect = OSError("native failure")
        engine = self.make_engine(PlayPauseAction(controller=controller))

        result = engine.execute("media.play_pause")

        self.assertFalse(result.success)
        self.assertEqual("OSError", result.error_type)
        self.assertEqual("native failure", result.error_message)


class WindowsMediaControlTests(unittest.TestCase):
    def test_play_action_uses_explicit_play(self) -> None:
        controller = Mock(spec=WindowsMediaControl)
        controller.play.return_value = {"message": "playing", "metadata": {}}

        result = self.make_engine_result(PlayMediaAction(controller=controller))

        self.assertTrue(result.success)
        controller.play.assert_called_once_with()

    def test_pause_action_uses_explicit_pause(self) -> None:
        controller = Mock(spec=WindowsMediaControl)
        controller.pause.return_value = {"message": "paused", "metadata": {}}

        result = self.make_engine_result(PauseMediaAction(controller=controller))

        self.assertTrue(result.success)
        controller.pause.assert_called_once_with()

    @staticmethod
    def make_engine_result(action):
        registry = ActionRegistry(auto_discover=False)
        registry.register(action)
        return ActionEngine(EventBus(), registry).execute(action.id)

    def test_volume_change_uses_configured_step(self) -> None:
        controller = WindowsMediaControl(volume_step=6)
        with patch.object(controller, "send_key") as send_key:
            result = controller.volume_up()

        send_key.assert_called_once_with(VK_VOLUME_UP, 3)
        self.assertEqual(6, result["metadata"]["volume_step"])

    def test_media_key_is_sent(self) -> None:
        controller = WindowsMediaControl()
        with patch.object(controller, "send_key") as send_key:
            controller.play_pause()

        send_key.assert_called_once_with(VK_MEDIA_PLAY_PAUSE)


class WindowsAppControlTests(unittest.TestCase):
    def test_apple_music_action_uses_fixed_allowlisted_key(self) -> None:
        controller = Mock(spec=WindowsAppControl)
        controller.open_app.return_value = {"message": "opened", "metadata": {}}

        OpenAppleMusicAction(controller=controller).execute()

        controller.open_app.assert_called_once_with("apple_music")

    def test_allowed_application_is_opened(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            executable = Path(temporary_directory) / "Code.exe"
            executable.touch()
            window_control = Mock(spec=WindowsWindowControl)
            controller = WindowsAppControl(
                allowed_apps=("vscode",),
                configured_paths={"vscode": [str(executable)]},
                window_control=window_control,
            )

            with (
                patch.object(controller, "_find_running_processes", return_value=[]),
                patch("platforms.windows.app_control.subprocess.Popen") as popen,
            ):
                popen.return_value.pid = 1234
                result = controller.open_app("vscode")

            popen.assert_called_once()
            self.assertEqual(1234, result["metadata"]["process_id"])

    def test_application_not_in_allowlist_is_rejected(self) -> None:
        controller = WindowsAppControl(allowed_apps=("vscode",))

        with self.assertRaises(AppNotAllowedError):
            controller.open_app("discord")

    def test_application_not_installed_returns_clear_error(self) -> None:
        controller = WindowsAppControl(allowed_apps=("missing",))
        with patch.object(controller, "_find_running_processes", return_value=[]):
            with self.assertRaises(AppNotInstalledError):
                controller.open_app("missing")

    def test_store_application_uses_fixed_launch_id(self) -> None:
        controller = WindowsAppControl(
            allowed_apps=("claude",),
            launch_ids={"claude": "Claude_fixed!Claude"},
        )
        with (
            patch.object(controller, "_find_running_processes", return_value=[]),
            patch.object(controller, "locate_app", return_value=None),
            patch("platforms.windows.app_control.subprocess.Popen") as popen,
        ):
            popen.return_value.pid = 456
            result = controller.open_app("claude")

        popen.assert_called_once_with(
            ["explorer.exe", r"shell:AppsFolder\Claude_fixed!Claude"],
            close_fds=True,
        )
        self.assertEqual("app_user_model_id", result["metadata"]["launch_type"])

    def test_duplicate_application_is_focused_not_opened(self) -> None:
        window_control = Mock(spec=WindowsWindowControl)
        window_control.focus_process.return_value = True
        controller = WindowsAppControl(
            allowed_apps=("vscode",),
            prevent_duplicates=True,
            window_control=window_control,
        )

        with (
            patch.object(controller, "_find_running_processes", return_value=[321]),
            patch("platforms.windows.app_control.subprocess.Popen") as popen,
        ):
            result = controller.open_app("vscode")

        popen.assert_not_called()
        window_control.focus_process.assert_called_once_with(321)
        self.assertTrue(result["metadata"]["already_running"])
        self.assertTrue(result["metadata"]["focused"])

    def test_app_action_never_reads_path_from_event_context(self) -> None:
        controller = Mock(spec=WindowsAppControl)
        controller.open_app.return_value = {"message": "opened", "metadata": {}}
        action = OpenVSCodeAction(controller=controller)

        action.execute({"path": r"C:\untrusted\payload.exe"})

        controller.open_app.assert_called_once_with("vscode")


if __name__ == "__main__":
    unittest.main()
