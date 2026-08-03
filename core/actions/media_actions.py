"""Acciones multimedia reales mediante teclas nativas de Windows."""

from typing import Any, Optional

from config import VOLUME_STEP
from core.actions.base_action import BaseAction
from platforms.windows.media_control import WindowsMediaControl


def _media_controller() -> WindowsMediaControl:
    return WindowsMediaControl(volume_step=VOLUME_STEP)


class PlayMediaAction(BaseAction):
    def __init__(self, controller: WindowsMediaControl | None = None) -> None:
        super().__init__("media.play", "Play media", "Inicia la reproducción.")
        self._controller = controller or _media_controller()

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.play()


class PauseMediaAction(BaseAction):
    def __init__(self, controller: WindowsMediaControl | None = None) -> None:
        super().__init__("media.pause", "Pause media", "Pausa la reproducción.")
        self._controller = controller or _media_controller()

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.pause()


class PlayPauseAction(BaseAction):
    def __init__(self, controller: WindowsMediaControl | None = None) -> None:
        super().__init__("media.play_pause", "Play or pause media", "Alterna reproducción.")
        self._controller = controller or _media_controller()

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.play_pause()


class NextTrackAction(BaseAction):
    def __init__(self, controller: WindowsMediaControl | None = None) -> None:
        super().__init__("media.next_track", "Next media track", "Avanza de pista.")
        self._controller = controller or _media_controller()

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.next_track()


class PreviousTrackAction(BaseAction):
    def __init__(self, controller: WindowsMediaControl | None = None) -> None:
        super().__init__("media.previous_track", "Previous media track", "Retrocede de pista.")
        self._controller = controller or _media_controller()

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.previous_track()


class StopMediaAction(BaseAction):
    def __init__(self, controller: WindowsMediaControl | None = None) -> None:
        super().__init__("media.stop", "Stop media", "Detiene la reproducción.")
        self._controller = controller or _media_controller()

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.stop()


class MuteMediaAction(BaseAction):
    def __init__(self, controller: WindowsMediaControl | None = None) -> None:
        super().__init__("media.mute", "Mute media", "Alterna el silencio del sistema.")
        self._controller = controller or _media_controller()

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.toggle_mute()


class MediaVolumeUpAction(BaseAction):
    def __init__(self, controller: WindowsMediaControl | None = None) -> None:
        super().__init__("media.volume_up", "Media volume up", "Sube el volumen.")
        self._controller = controller or _media_controller()

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.volume_up()


class MediaVolumeDownAction(BaseAction):
    def __init__(self, controller: WindowsMediaControl | None = None) -> None:
        super().__init__("media.volume_down", "Media volume down", "Baja el volumen.")
        self._controller = controller or _media_controller()

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.volume_down()
