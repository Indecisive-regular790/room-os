"""Acciones de aplicaciones limitadas a la lista blanca configurada."""

from typing import Any, Optional

from config import (
    ALLOWED_APPS,
    APP_LAUNCH_IDS,
    APP_PATHS,
    PREVENT_DUPLICATE_APPS,
)
from core.actions.base_action import BaseAction
from platforms.windows.app_control import WindowsAppControl
from platforms.windows.window_control import WindowsWindowControl


def _app_controller() -> WindowsAppControl:
    return WindowsAppControl(
        allowed_apps=ALLOWED_APPS,
        configured_paths=APP_PATHS,
        launch_ids=APP_LAUNCH_IDS,
        prevent_duplicates=PREVENT_DUPLICATE_APPS,
    )


class _OpenAppAction(BaseAction):
    app_key = ""

    def __init__(
        self,
        action_id: str,
        name: str,
        description: str,
        controller: WindowsAppControl | None = None,
    ) -> None:
        super().__init__(action_id, name, description)
        self._controller = controller or _app_controller()

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.open_app(self.app_key)


class OpenBrowserAction(_OpenAppAction):
    app_key = "browser"

    def __init__(self, controller: WindowsAppControl | None = None) -> None:
        super().__init__("apps.open_browser", "Open browser", "Abre un navegador permitido.", controller)


class OpenVSCodeAction(_OpenAppAction):
    app_key = "vscode"

    def __init__(self, controller: WindowsAppControl | None = None) -> None:
        super().__init__("apps.open_vscode", "Open Visual Studio Code", "Abre VS Code.", controller)


class OpenTerminalAction(_OpenAppAction):
    app_key = "terminal"

    def __init__(self, controller: WindowsAppControl | None = None) -> None:
        super().__init__("apps.open_terminal", "Open terminal", "Abre una terminal permitida.", controller)


class OpenSpotifyAction(_OpenAppAction):
    app_key = "spotify"

    def __init__(self, controller: WindowsAppControl | None = None) -> None:
        super().__init__("apps.open_spotify", "Open Spotify", "Abre Spotify si está instalado.", controller)


class OpenDiscordAction(_OpenAppAction):
    app_key = "discord"

    def __init__(self, controller: WindowsAppControl | None = None) -> None:
        super().__init__("apps.open_discord", "Open Discord", "Abre Discord si está instalado.", controller)


class OpenCodexAction(_OpenAppAction):
    app_key = "codex"

    def __init__(self, controller: WindowsAppControl | None = None) -> None:
        super().__init__("apps.open_codex", "Open Codex", "Abre Codex si está instalado.", controller)


class OpenClaudeAction(_OpenAppAction):
    app_key = "claude"

    def __init__(self, controller: WindowsAppControl | None = None) -> None:
        super().__init__("apps.open_claude", "Open Claude", "Abre Claude si está instalado.", controller)


class OpenAppleMusicAction(_OpenAppAction):
    app_key = "apple_music"

    def __init__(self, controller: WindowsAppControl | None = None) -> None:
        super().__init__(
            "apps.open_apple_music",
            "Open Apple Music",
            "Abre Apple Music si está instalado.",
            controller,
        )


class CloseActiveWindowAction(BaseAction):
    def __init__(self, controller: WindowsWindowControl | None = None) -> None:
        super().__init__(
            "apps.close_active_window",
            "Close active window",
            "Envía Alt+F4 a la ventana activa.",
        )
        self._controller = controller or WindowsWindowControl()

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.close_active_window()


class SwitchWindowAction(BaseAction):
    def __init__(self, controller: WindowsWindowControl | None = None) -> None:
        super().__init__(
            "apps.switch_window",
            "Switch window",
            "Cambia a la siguiente ventana mediante Alt+Tab.",
        )
        self._controller = controller or WindowsWindowControl()

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.switch_window()
