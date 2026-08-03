"""Localización, enfoque y apertura segura de aplicaciones permitidas."""

import glob
import os
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Optional

import psutil

from platforms.windows.window_control import WindowsWindowControl


class WindowsAppControlError(RuntimeError):
    """Error base al controlar una aplicación."""


class AppNotAllowedError(WindowsAppControlError):
    """Indica que una aplicación no pertenece a la lista blanca."""


class AppNotInstalledError(WindowsAppControlError):
    """Indica que no se encontró un ejecutable permitido."""


DEFAULT_APP_CANDIDATES: dict[str, tuple[str, ...]] = {
    "browser": (
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
        r"%ProgramFiles%\Mozilla Firefox\firefox.exe",
    ),
    "vscode": (
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
        r"%ProgramFiles%\Microsoft VS Code\Code.exe",
    ),
    "terminal": (
        r"%LOCALAPPDATA%\Microsoft\WindowsApps\wt.exe",
        r"%WINDIR%\System32\WindowsPowerShell\v1.0\powershell.exe",
    ),
    "spotify": (r"%APPDATA%\Spotify\Spotify.exe",),
    "discord": (r"%LOCALAPPDATA%\Discord\app-*\Discord.exe",),
    "codex": (
        r"%LOCALAPPDATA%\Programs\Codex\Codex.exe",
        r"%LOCALAPPDATA%\Codex\Codex.exe",
        r"C:\Program Files\WindowsApps\OpenAI.Codex_*\app\Codex.exe",
    ),
    "claude": (
        r"%LOCALAPPDATA%\Programs\Claude\Claude.exe",
        r"%LOCALAPPDATA%\AnthropicClaude\Claude.exe",
    ),
    "apple_music": (),
}

APP_PROCESS_NAMES: dict[str, tuple[str, ...]] = {
    "browser": ("msedge.exe", "chrome.exe", "firefox.exe"),
    "vscode": ("code.exe",),
    "terminal": ("windowsterminal.exe", "powershell.exe"),
    "spotify": ("spotify.exe",),
    "discord": ("discord.exe",),
    "codex": ("chatgpt.exe",),
    "claude": ("claude.exe",),
    "apple_music": ("applemusic.exe",),
}


class WindowsAppControl:
    """Abre solo aplicaciones declaradas, usando rutas preconfiguradas o conocidas."""

    def __init__(
        self,
        allowed_apps: Iterable[str],
        configured_paths: Optional[Mapping[str, str | Iterable[str]]] = None,
        launch_ids: Optional[Mapping[str, str]] = None,
        prevent_duplicates: bool = True,
        window_control: WindowsWindowControl | None = None,
    ) -> None:
        self._allowed_apps = frozenset(str(app) for app in allowed_apps)
        self._configured_paths = dict(configured_paths or {})
        self._launch_ids = dict(launch_ids or {})
        self._prevent_duplicates = bool(prevent_duplicates)
        self._window_control = window_control or WindowsWindowControl()

    def open_app(self, app_key: str) -> dict[str, Any]:
        """Abre una clave fija de la lista blanca; no acepta rutas en eventos."""
        if app_key not in self._allowed_apps:
            raise AppNotAllowedError(
                f"La aplicación '{app_key}' no está en ALLOWED_APPS"
            )

        running_process_ids = self._find_running_processes(app_key)
        if running_process_ids and self._prevent_duplicates:
            focused = any(
                self._window_control.focus_process(process_id)
                for process_id in running_process_ids
            )
            return {
                "message": (
                    f"La aplicación '{app_key}' ya estaba abierta; "
                    "se intentó enfocarla"
                ),
                "metadata": {
                    "app": app_key,
                    "already_running": True,
                    "focused": focused,
                    "process_ids": running_process_ids,
                },
            }

        executable = self.locate_app(app_key)
        if executable is None:
            launch_id = self._launch_ids.get(app_key)
            if launch_id:
                process = subprocess.Popen(
                    ["explorer.exe", f"shell:AppsFolder\\{launch_id}"],
                    close_fds=True,
                )
                return {
                    "message": f"Aplicación '{app_key}' abierta desde Microsoft Store",
                    "metadata": {
                        "app": app_key,
                        "already_running": False,
                        "process_id": process.pid,
                        "launch_type": "app_user_model_id",
                    },
                }
            raise AppNotInstalledError(
                f"No se encontró una instalación permitida para '{app_key}'"
            )

        process = subprocess.Popen(
            [str(executable)],
            cwd=str(executable.parent),
            close_fds=True,
        )
        return {
            "message": f"Aplicación '{app_key}' abierta",
            "metadata": {
                "app": app_key,
                "already_running": False,
                "process_id": process.pid,
                "executable": str(executable),
            },
        }

    def locate_app(self, app_key: str) -> Optional[Path]:
        if app_key not in self._allowed_apps:
            raise AppNotAllowedError(
                f"La aplicación '{app_key}' no está en ALLOWED_APPS"
            )

        candidates = [
            *DEFAULT_APP_CANDIDATES.get(app_key, ()),
            *self._configured_candidates(app_key),
        ]
        for candidate in candidates:
            expanded = os.path.expanduser(os.path.expandvars(candidate))
            matches = glob.glob(expanded)
            for match in matches or [expanded]:
                path = Path(match)
                if path.is_file() and path.suffix.casefold() == ".exe":
                    return path.resolve()
        return None

    def _configured_candidates(self, app_key: str) -> list[str]:
        configured = self._configured_paths.get(app_key, ())
        if isinstance(configured, str):
            return [configured] if configured else []
        return [str(candidate) for candidate in configured if str(candidate)]

    @staticmethod
    def _find_running_processes(app_key: str) -> list[int]:
        allowed_names = {
            name.casefold() for name in APP_PROCESS_NAMES.get(app_key, ())
        }
        process_ids: list[int] = []
        for process in psutil.process_iter(("pid", "name")):
            try:
                name = (process.info.get("name") or "").casefold()
                if name in allowed_names:
                    process_ids.append(int(process.info["pid"]))
            except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
        return process_ids
