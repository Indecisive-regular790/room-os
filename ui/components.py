"""Componentes pequeños compartidos por las vistas."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("pageSubtitle")
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)


class StatusCard(QFrame):
    def __init__(self, label: str, value: str = "Esperando") -> None:
        super().__init__()
        self.setObjectName("panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 15, 18, 15)
        layout.setSpacing(5)
        caption = QLabel(label.upper())
        caption.setObjectName("eyebrow")
        self.value = QLabel(value)
        self.value.setObjectName("metric")
        layout.addWidget(caption)
        layout.addWidget(self.value)

    def set_value(self, value: str) -> None:
        self.value.setText(value)


def section_panel(title: str, body: QWidget) -> QFrame:
    panel = QFrame()
    panel.setObjectName("panel")
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(18, 16, 18, 18)
    layout.setSpacing(12)
    heading = QLabel(title)
    heading.setObjectName("sectionTitle")
    layout.addWidget(heading)
    layout.addWidget(body)
    return panel


def empty_state(title: str, description: str) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.setSpacing(8)
    heading = QLabel(title)
    heading.setObjectName("metric")
    heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
    detail = QLabel(description)
    detail.setObjectName("muted")
    detail.setWordWrap(True)
    detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
    layout.addWidget(heading)
    layout.addWidget(detail)
    return widget
