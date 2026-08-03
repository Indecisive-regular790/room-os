from collections import deque
from datetime import datetime
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QVBoxLayout, QWidget,
)

from ui.components import PageHeader, section_panel


class ActivityPage(QWidget):
    def __init__(self, title: str, subtitle: str, empty_text: str) -> None:
        super().__init__()
        self._items: deque[str] = deque(maxlen=40)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 30)
        layout.setSpacing(18)
        layout.addWidget(PageHeader(title, subtitle))
        self.summary = QLabel(empty_text)
        self.summary.setObjectName("muted")
        self.summary.setWordWrap(True)
        layout.addWidget(section_panel("Estado actual", self.summary))
        self.controls = QHBoxLayout()
        self.controls.addStretch()
        layout.addLayout(self.controls)
        self.history = QListWidget()
        self.history.setAlternatingRowColors(False)
        layout.addWidget(section_panel("Actividad reciente", self.history), 1)

    def add_event(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self._items.appendleft(f"{stamp}   {text}")
        self.history.clear()
        self.history.addItems(list(self._items))

    def set_summary(self, text: str) -> None:
        self.summary.setText(text)

    def add_control(self, widget: QWidget) -> None:
        self.controls.insertWidget(0, widget)


GESTURES = ("OPEN_PALM", "FIST", "POINT", "PEACE", "THUMBS_UP", "THUMBS_DOWN", "PINCH", "SPIDERMAN")
GESTURE_LABELS = {
    "OPEN_PALM": "Palma abierta", "FIST": "Puño", "POINT": "Señalar",
    "PEACE": "Paz", "THUMBS_UP": "Pulgar arriba",
    "THUMBS_DOWN": "Pulgar abajo", "PINCH": "Pinza",
    "SPIDERMAN": "Spiderman",
}


class GestureActionEditor(QWidget):
    def __init__(self, registry: Any, mapping: dict[str, str] | None = None) -> None:
        super().__init__()
        self._combos: dict[str, QComboBox] = {}
        actions = [action for action in registry.list_actions(only_enabled=True) if not action.dangerous]
        form = QFormLayout(self)
        form.setSpacing(10)
        current = mapping or {}
        for gesture in GESTURES:
            combo = QComboBox()
            combo.addItem("Sin acción", "")
            for action in actions:
                combo.addItem(f"{action.name}  ·  {action.id}", action.id)
            selected = combo.findData(current.get(gesture, ""))
            combo.setCurrentIndex(max(0, selected))
            form.addRow(GESTURE_LABELS[gesture], combo)
            self._combos[gesture] = combo

    def mapping(self) -> dict[str, str]:
        return {
            gesture: str(combo.currentData())
            for gesture, combo in self._combos.items()
            if combo.currentData()
        }


class ActionsPage(QWidget):
    def __init__(self, registry: Any, mapping: dict[str, str] | None = None, on_save=None) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 30)
        layout.setSpacing(18)
        layout.addWidget(PageHeader("Acciones", "Catálogo desacoplado de acciones disponibles."))
        self.editor = GestureActionEditor(registry, mapping)
        layout.addWidget(section_panel("Asignaciones de gestos", self.editor))
        save = QPushButton("Guardar asignaciones")
        save.setObjectName("primary")
        self.status = QLabel("Las acciones peligrosas no pueden asignarse a un gesto.")
        self.status.setObjectName("muted")
        row = QHBoxLayout()
        row.addWidget(self.status)
        row.addStretch()
        row.addWidget(save)
        layout.addLayout(row)
        if on_save is not None:
            save.clicked.connect(lambda: self._save(on_save))
        listing = QListWidget()
        for action in registry.list_actions():
            state = "Activa" if action.enabled else "Desactivada"
            listing.addItem(f"{action.id}   ·   {state}")
        layout.addWidget(section_panel("Catálogo disponible", listing), 1)

    def _save(self, callback) -> None:
        callback(self.editor.mapping())
        self.status.setText("Asignaciones guardadas.")


class SettingsPage(QWidget):
    def __init__(self, settings: Any, on_save=None, on_reset=None) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 30)
        layout.setSpacing(18)
        layout.addWidget(PageHeader("Configuración", "Inicio, bandeja y asistente de configuración."))
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        self.start_with_windows = QCheckBox("Iniciar Room OS con Windows")
        self.close_to_tray = QCheckBox("Mantener Room OS en la bandeja al cerrar")
        if settings is not None:
            self.start_with_windows.setChecked(settings.get("start_with_windows", False))
            self.close_to_tray.setChecked(settings.get("close_to_tray", False))
        body_layout.addWidget(self.start_with_windows)
        body_layout.addWidget(self.close_to_tray)
        layout.addWidget(section_panel("Comportamiento", body))
        row = QHBoxLayout()
        reset = QPushButton("Ejecutar asistente en el próximo inicio")
        save = QPushButton("Guardar configuración")
        save.setObjectName("primary")
        row.addWidget(reset)
        row.addStretch()
        row.addWidget(save)
        layout.addLayout(row)
        self.status = QLabel("Los cambios de inicio no requieren permisos de administrador.")
        self.status.setObjectName("muted")
        layout.addWidget(self.status)
        layout.addStretch()
        if on_save is not None:
            save.clicked.connect(lambda: self._save(on_save))
        if on_reset is not None:
            reset.clicked.connect(lambda: self._reset(on_reset))

    def _save(self, callback) -> None:
        callback(self.start_with_windows.isChecked(), self.close_to_tray.isChecked())
        self.status.setText("Configuración guardada.")

    def _reset(self, callback) -> None:
        callback()
        self.status.setText("El asistente aparecerá la próxima vez que abras Room OS.")
