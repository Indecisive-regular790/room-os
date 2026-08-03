"""Pantalla de arranque propia de Room OS."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QSplashScreen

from core.runtime_paths import asset_path


class StartupSplash(QSplashScreen):
    def __init__(self) -> None:
        canvas = QPixmap(520, 260)
        canvas.fill(QColor("#F5F7FA"))
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor("#DDE3EA"))
        painter.drawRoundedRect(1, 1, 517, 257, 14, 14)
        logo = QPixmap(str(asset_path("room_os_logo.png"))).scaled(
            104, 104,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap(42, 58, logo)
        painter.setPen(QColor("#172B4D"))
        title_font = painter.font()
        title_font.setFamily("Inter")
        title_font.setPointSize(24)
        title_font.setWeight(QFont.Weight.Bold)
        painter.setFont(title_font)
        painter.drawText(174, 98, "ROOM OS")
        painter.setPen(QColor("#647084"))
        body_font = painter.font()
        body_font.setPointSize(10)
        body_font.setWeight(QFont.Weight.Normal)
        painter.setFont(body_font)
        painter.drawText(176, 126, "Entorno visual local")
        painter.end()
        super().__init__(canvas, Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("startupSplash")

    def show_status(self, message: str) -> None:
        self.showMessage(
            message,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
            QColor("#416FA6"),
        )
