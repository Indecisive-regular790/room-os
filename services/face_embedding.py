"""Descriptores faciales locales basados en textura LBP normalizada."""

from typing import Any, Optional

import cv2
import numpy as np


EMBEDDING_METHOD = "lbp_grid_v1"


def crop_face(
    frame: Any,
    bounding_box: dict[str, float],
    margin: float = 0.15,
) -> Optional[np.ndarray]:
    """Recorta un rostro usando una caja normalizada y un margen limitado."""
    if frame is None or not hasattr(frame, "shape"):
        return None
    height, width = frame.shape[:2]
    x = float(bounding_box["x"])
    y = float(bounding_box["y"])
    box_width = float(bounding_box["width"])
    box_height = float(bounding_box["height"])
    margin_x = box_width * max(0.0, margin)
    margin_y = box_height * max(0.0, margin)
    left = max(0, int((x - margin_x) * width))
    top = max(0, int((y - margin_y) * height))
    right = min(width, int((x + box_width + margin_x) * width))
    bottom = min(height, int((y + box_height + margin_y) * height))
    if right <= left or bottom <= top:
        return None
    return frame[top:bottom, left:right].copy()


def blur_score(face_image: Any) -> float:
    """Devuelve la varianza del Laplaciano como medida simple de nitidez."""
    gray = _to_gray(face_image)
    if gray is None:
        return 0.0
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def generate_face_embedding(face_image: Any) -> np.ndarray:
    """Genera un descriptor LBP por cuadrícula, ecualizado y normalizado L2."""
    gray = _to_gray(face_image)
    if gray is None or min(gray.shape[:2]) < 16:
        raise ValueError("La región facial es demasiado pequeña")

    normalized = cv2.resize(gray, (128, 128), interpolation=cv2.INTER_AREA)
    normalized = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(
        normalized
    )
    center = normalized[1:-1, 1:-1]
    neighbors = (
        normalized[:-2, :-2],
        normalized[:-2, 1:-1],
        normalized[:-2, 2:],
        normalized[1:-1, 2:],
        normalized[2:, 2:],
        normalized[2:, 1:-1],
        normalized[2:, :-2],
        normalized[1:-1, :-2],
    )
    lbp = np.zeros(center.shape, dtype=np.uint8)
    for bit, neighbor in enumerate(neighbors):
        lbp |= ((neighbor >= center).astype(np.uint8) << bit)

    features = []
    for row_cells in np.array_split(lbp, 4, axis=0):
        for cell in np.array_split(row_cells, 4, axis=1):
            histogram = np.bincount(cell.ravel(), minlength=256).astype(np.float32)
            histogram /= max(float(histogram.sum()), 1.0)
            features.append(histogram)
    embedding = np.concatenate(features).astype(np.float32)
    norm = float(np.linalg.norm(embedding))
    if norm <= 0:
        raise ValueError("No se pudo generar un descriptor facial válido")
    return embedding / norm


def cosine_similarity(first: np.ndarray, second: np.ndarray) -> float:
    first = np.asarray(first, dtype=np.float32).ravel()
    second = np.asarray(second, dtype=np.float32).ravel()
    if first.shape != second.shape or first.size == 0:
        return 0.0
    denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
    if denominator <= 0:
        return 0.0
    return float(np.dot(first, second) / denominator)


def _to_gray(image: Any) -> Optional[np.ndarray]:
    if image is None or not hasattr(image, "shape") or image.size == 0:
        return None
    if len(image.shape) == 2:
        return image.astype(np.uint8, copy=False)
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
