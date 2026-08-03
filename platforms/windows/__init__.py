"""Controles nativos y restringidos para Windows."""

from platforms.windows.app_control import WindowsAppControl
from platforms.windows.media_control import WindowsMediaControl
from platforms.windows.system_control import WindowsSystemControl
from platforms.windows.window_control import WindowsWindowControl


__all__ = [
    "WindowsAppControl",
    "WindowsMediaControl",
    "WindowsSystemControl",
    "WindowsWindowControl",
]
