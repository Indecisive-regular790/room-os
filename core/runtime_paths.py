"""Rutas estables tanto en desarrollo como en la aplicación empaquetada."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def application_root() -> Path:
    """Devuelve la carpeta del proyecto o la carpeta que contiene el .exe."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def application_data_dir() -> Path:
    """Carpeta persistente independiente de actualizaciones del ejecutable."""
    override = os.environ.get("ROOM_OS_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, "frozen", False):
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "Room OS" / "data"
    return application_root() / "data"


def asset_path(*parts: str) -> Path:
    """Resuelve un recurso visual dentro del proyecto o del paquete."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).joinpath("assets", *parts)
    return application_root().joinpath("assets", *parts)


def migrate_legacy_data() -> list[Path]:
    """Copia datos antiguos a la ubicación estable sin sobrescribir archivos."""
    destination = application_data_dir()
    destination.mkdir(parents=True, exist_ok=True)
    if not getattr(sys, "frozen", False):
        return []

    migrated: list[Path] = []
    legacy_roots = (
        application_root() / "data",
        application_root() / "_internal" / "data",
    )
    for legacy in legacy_roots:
        if not legacy.is_dir() or legacy.resolve() == destination.resolve():
            continue
        for source in legacy.rglob("*"):
            if not source.is_file():
                continue
            relative = source.relative_to(legacy)
            target = destination / relative
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            migrated.append(target)
    return migrated
