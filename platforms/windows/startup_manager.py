"""Inicio opcional de Room OS con la sesión del usuario."""

from __future__ import annotations

import os
from pathlib import Path


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Room OS"


def set_start_with_windows(enabled: bool, project_root: Path) -> None:
    if os.name != "nt":
        return
    import winreg

    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        RUN_KEY,
        0,
        winreg.KEY_SET_VALUE,
    ) as key:
        if enabled:
            executable = project_root / "Room OS.exe"
            if executable.is_file():
                command = f'"{executable}"'
            else:
                script = project_root / "scripts" / "start_room_os.ps1"
                command = (
                    'powershell.exe -NoProfile -WindowStyle Hidden '
                    f'-ExecutionPolicy Bypass -File "{script}"'
                )
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass


def is_start_with_windows_enabled() -> bool:
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
        return True
    except FileNotFoundError:
        return False
