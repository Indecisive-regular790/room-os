"""Acciones registrables de Room OS, delegadas a capas de plataforma."""

from core.actions.app_actions import (
    CloseActiveWindowAction,
    OpenBrowserAction,
    OpenAppleMusicAction,
    OpenClaudeAction,
    OpenCodexAction,
    OpenDiscordAction,
    OpenSpotifyAction,
    OpenTerminalAction,
    OpenVSCodeAction,
    SwitchWindowAction,
)
from core.actions.media_actions import (
    MediaVolumeDownAction,
    MediaVolumeUpAction,
    MuteMediaAction,
    NextTrackAction,
    PlayPauseAction,
    PlayMediaAction,
    PauseMediaAction,
    PreviousTrackAction,
    StopMediaAction,
)
from core.actions.system_actions import (
    CancelPowerAction,
    LockSystemAction,
    OpenTaskManagerAction,
    RestartSystemAction,
    ShowDesktopAction,
    ShutdownSystemAction,
    SleepSystemAction,
    SystemVolumeDownAction,
    SystemVolumeUpAction,
    ToggleSystemMuteAction,
)


__all__ = [name for name in globals() if name.endswith("Action")]
