"""Perfiles personales de gestos basados únicamente en landmarks."""

from __future__ import annotations

import json
import logging
import math
import shutil
import threading
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

from core.runtime_paths import application_data_dir


logger = logging.getLogger(__name__)


class GestureProfileStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or application_data_dir() / "gesture_profiles.json"
        self._lock = threading.RLock()
        self._profiles = self._load()

    @staticmethod
    def extract_features(landmarks: list[dict[str, Any]], handedness: str) -> tuple[float, ...]:
        if len(landmarks) != 21:
            raise ValueError("Se requieren los 21 puntos de la mano")
        ordered = sorted(landmarks, key=lambda item: int(item["id"]))
        wrist = ordered[0]["normalized"]
        middle_mcp = ordered[9]["normalized"]
        scale = max(
            math.hypot(
                float(middle_mcp["x"]) - float(wrist["x"]),
                float(middle_mcp["y"]) - float(wrist["y"]),
            ),
            1e-6,
        )
        mirror = -1.0 if str(handedness).lower() == "left" else 1.0
        features: list[float] = []
        for item in ordered:
            point = item["normalized"]
            features.extend(
                (
                    mirror * (float(point["x"]) - float(wrist["x"])) / scale,
                    (float(point["y"]) - float(wrist["y"])) / scale,
                )
            )
        return tuple(features)

    def train(self, gesture: str, handedness: str, samples: list[list[dict[str, Any]]]) -> dict[str, Any]:
        if len(samples) < 12:
            raise ValueError("Se necesitan al menos 12 muestras válidas")
        vectors = [self.extract_features(sample, handedness) for sample in samples]
        columns = tuple(zip(*vectors))
        center = tuple(float(median(column)) for column in columns)
        distances = [self._distance(vector, center) for vector in vectors]
        radius = max(0.10, float(median(distances)) * 3.5)
        key = self._key(gesture, handedness)
        profile = {
            "gesture": str(gesture),
            "handedness": str(handedness),
            "sample_count": len(vectors),
            "center": list(center),
            "radius": radius,
        }
        with self._lock:
            self._profiles[key] = profile
            self._save_locked()
        return dict(profile)

    def match(self, landmarks: list[dict[str, Any]], handedness: str) -> tuple[str, float] | None:
        try:
            vector = self.extract_features(landmarks, handedness)
        except (KeyError, TypeError, ValueError):
            return None
        with self._lock:
            profiles = tuple(self._profiles.values())
        best: tuple[str, float] | None = None
        for profile in profiles:
            if str(profile.get("handedness")) != str(handedness):
                continue
            center = tuple(float(value) for value in profile.get("center", []))
            radius = max(float(profile.get("radius", 0.0)), 1e-6)
            if len(center) != len(vector):
                continue
            distance = self._distance(vector, center)
            confidence = max(0.0, 1.0 - distance / radius)
            if confidence >= 0.72 and (best is None or confidence > best[1]):
                best = (str(profile["gesture"]), confidence)
        return best

    def list_profiles(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(profile) for profile in self._profiles.values()]

    @staticmethod
    def _distance(first: tuple[float, ...], second: tuple[float, ...]) -> float:
        return math.sqrt(sum((a - b) ** 2 for a, b in zip(first, second)) / len(first))

    @staticmethod
    def _key(gesture: str, handedness: str) -> str:
        return f"{handedness}:{gesture}"

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.is_file():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError("Los perfiles deben ser un objeto JSON")
            return data
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            try:
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                backup = self.path.with_name(
                    f"{self.path.stem}.corrupt-{timestamp}{self.path.suffix}"
                )
                shutil.copy2(self.path, backup)
                logger.error("Perfiles dañados preservados en %s: %s", backup, error)
            except OSError:
                logger.exception("No se pudieron preservar los perfiles dañados")
            return {}

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(self._profiles, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
