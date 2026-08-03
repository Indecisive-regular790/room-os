"""Base local de perfiles y embeddings faciales."""

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import cv2
import numpy as np

from services.face_embedding import EMBEDDING_METHOD


_PROFILE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class FaceDatabaseError(RuntimeError):
    """Error de validación o almacenamiento de un perfil facial."""


class FaceDatabase:
    """Guarda perfiles en disco sin servicios externos ni datos en config.py."""

    def __init__(self, root_path: str | Path) -> None:
        path = Path(root_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[1] / path
        self.root_path = path.resolve()

    @staticmethod
    def validate_profile_name(profile_name: str) -> str:
        profile_name = str(profile_name).strip()
        if not _PROFILE_PATTERN.fullmatch(profile_name):
            raise FaceDatabaseError(
                "El perfil solo puede contener letras, números, guion y guion bajo"
            )
        return profile_name

    def profile_path(self, profile_name: str) -> Path:
        valid_name = self.validate_profile_name(profile_name)
        return self.root_path / valid_name

    def has_profile(self, profile_name: str) -> bool:
        profile_path = self.profile_path(profile_name)
        return (profile_path / "metadata.json").is_file() and (
            profile_path / "embeddings.npy"
        ).is_file()

    def list_profiles(self) -> tuple[str, ...]:
        if not self.root_path.is_dir():
            return ()
        return tuple(
            sorted(
                path.name
                for path in self.root_path.iterdir()
                if path.is_dir() and self.has_profile(path.name)
            )
        )

    def load_embeddings(self, profile_name: str) -> np.ndarray:
        if not self.has_profile(profile_name):
            raise FaceDatabaseError(f"No existe el perfil '{profile_name}'")
        embeddings = np.load(
            self.profile_path(profile_name) / "embeddings.npy",
            allow_pickle=False,
        )
        if embeddings.ndim != 2 or embeddings.shape[0] < 1:
            raise FaceDatabaseError(f"El perfil '{profile_name}' no tiene embeddings")
        return embeddings.astype(np.float32, copy=False)

    def load_all(self) -> dict[str, np.ndarray]:
        return {profile: self.load_embeddings(profile) for profile in self.list_profiles()}

    def load_metadata(self, profile_name: str) -> dict[str, Any]:
        metadata_path = self.profile_path(profile_name) / "metadata.json"
        if not metadata_path.is_file():
            raise FaceDatabaseError(f"No existe metadata para '{profile_name}'")
        return json.loads(metadata_path.read_text(encoding="utf-8"))

    def save_profile(
        self,
        profile_name: str,
        display_name: str,
        embeddings: Iterable[np.ndarray],
        images: Optional[Iterable[Any]] = None,
    ) -> Path:
        profile_name = self.validate_profile_name(profile_name)
        matrix = np.asarray(list(embeddings), dtype=np.float32)
        if matrix.ndim != 2 or matrix.shape[0] < 3:
            raise FaceDatabaseError("Se requieren al menos tres capturas faciales válidas")

        profile_path = self.profile_path(profile_name)
        profile_path.mkdir(parents=True, exist_ok=True)
        np.save(profile_path / "embeddings.npy", matrix, allow_pickle=False)

        saved_images = 0
        for index, image in enumerate(images or (), start=1):
            image_path = profile_path / f"image_{index:03d}.jpg"
            if cv2.imwrite(str(image_path), image):
                saved_images += 1

        metadata = {
            "profile": profile_name,
            "display_name": str(display_name).strip() or profile_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "embedding_method": EMBEDDING_METHOD,
            "embedding_count": int(matrix.shape[0]),
            "image_count": saved_images,
        }
        (profile_path / "metadata.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return profile_path

    def delete_profile(self, profile_name: str) -> None:
        profile_path = self.profile_path(profile_name)
        if not profile_path.is_dir():
            raise FaceDatabaseError(f"No existe el perfil '{profile_name}'")
        shutil.rmtree(profile_path)
