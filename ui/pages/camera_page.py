from collections.abc import Callable

import cv2
import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy,
    QVBoxLayout, QWidget,
)

from ui.components import PageHeader


def frame_to_pixmap(frame: np.ndarray) -> QPixmap:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    height, width, channels = rgb.shape
    image = QImage(rgb.data, width, height, channels * width, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(image.copy())


class CameraPage(QWidget):
    def __init__(self, toggles: dict[str, tuple[bool, Callable[[bool], None]]]) -> None:
        super().__init__()
        self._pixmap: QPixmap | None = None
        self._latest_frame: np.ndarray | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 30)
        layout.setSpacing(18)
        layout.addWidget(PageHeader("Cámara", "Vista en vivo y capas de diagnóstico."))

        content = QHBoxLayout()
        content.setSpacing(16)
        video_panel = QFrame()
        video_panel.setObjectName("panel")
        video_layout = QVBoxLayout(video_panel)
        video_layout.setContentsMargins(12, 12, 12, 12)
        self.video = QLabel("Conectando con la cámara…")
        self.video.setObjectName("video")
        self.video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video.setMinimumSize(480, 270)
        self.video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.fps = QLabel("0.0 FPS")
        self.fps.setObjectName("fpsBadge")
        self.fps.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.fps.setFixedWidth(78)
        video_layout.addWidget(self.video, 1)
        video_layout.addWidget(self.fps, 0, Qt.AlignmentFlag.AlignRight)
        content.addWidget(video_panel, 1)

        controls = QFrame()
        controls.setObjectName("panel")
        controls.setFixedWidth(224)
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(18, 18, 18, 18)
        controls_layout.setSpacing(15)
        title = QLabel("Capas visibles")
        title.setObjectName("sectionTitle")
        controls_layout.addWidget(title)
        labels = {
            "fps": "FPS", "hands": "Puntos de manos", "gestures": "Gestos",
            "faces": "Rostros", "presence": "Presencia", "mouse": "Mouse virtual",
        }
        self.checks: dict[str, QCheckBox] = {}
        for key, (checked, callback) in toggles.items():
            check = QCheckBox(labels[key])
            check.setChecked(checked)
            check.toggled.connect(callback)
            if key == "fps":
                check.toggled.connect(self.fps.setVisible)
            controls_layout.addWidget(check)
            self.checks[key] = check
        controls_layout.addStretch()
        hint = QLabel("Estas opciones cambian la vista, no detienen el procesamiento.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        controls_layout.addWidget(hint)
        content.addWidget(controls)
        layout.addLayout(content, 1)

    @property
    def latest_frame(self) -> np.ndarray | None:
        return None if self._latest_frame is None else self._latest_frame.copy()

    def set_frame(self, frame: np.ndarray, fps: float) -> None:
        self._latest_frame = frame.copy()
        self._pixmap = frame_to_pixmap(frame)
        self.fps.setText(f"{fps:.1f} FPS")
        self._fit_pixmap()

    def set_error(self, message: str) -> None:
        self.video.setText(message)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_pixmap()

    def _fit_pixmap(self) -> None:
        if self._pixmap is not None:
            self.video.setPixmap(self._pixmap.scaled(
                self.video.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
