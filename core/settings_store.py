"""Preferencias persistentes y atómicas de Room OS."""

from __future__ import annotations

import json
import logging
import shutil
import threading
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from config import GESTURE_ACTION_MAP
from core.runtime_paths import application_data_dir


logger = logging.getLogger(__name__)


DEFAULT_SETTINGS: dict[str, Any] = {
    "version": 1,
    "setup_complete": False,
    "gesture_actions": dict(GESTURE_ACTION_MAP),
    "start_with_windows": False,
    "launch_minimized": False,
    "close_to_tray": False,
}


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or application_data_dir() / "settings.json"
        self._lock = threading.RLock()
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        data = deepcopy(DEFAULT_SETTINGS)
        if not self.path.is_file():
            return data
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if not isinstance(loaded, dict):
                raise ValueError("La configuración debe ser un objeto JSON")
            data.update(loaded)
            if isinstance(loaded.get("gesture_actions"), dict):
                data["gesture_actions"] = {
                    str(key): str(value)
                    for key, value in loaded["gesture_actions"].items()
                    if value
                }
            else:
                data["gesture_actions"] = dict(DEFAULT_SETTINGS["gesture_actions"])
            for key in (
                "setup_complete", "start_with_windows", "launch_minimized",
                "close_to_tray",
            ):
                if not isinstance(data.get(key), bool):
                    data[key] = DEFAULT_SETTINGS[key]
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            self._preserve_corrupt_file(error)
            return data
        return data

    def _preserve_corrupt_file(self, error: Exception) -> None:
        try:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = self.path.with_name(
                f"{self.path.stem}.corrupt-{timestamp}{self.path.suffix}"
            )
            shutil.copy2(self.path, backup)
            logger.error("Configuración dañada preservada en %s: %s", backup, error)
        except OSError:
            logger.exception("No se pudo preservar la configuración dañada")

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return deepcopy(self._data.get(key, default))

    def update(self, **values: Any) -> None:
        with self._lock:
            self._data.update(deepcopy(values))
            self._save_locked()

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
