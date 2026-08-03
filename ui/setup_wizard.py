"""Asistente seguro mostrado antes de activar automatizaciones."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
    QPushButton, QVBoxLayout, QWizard, QWizardPage,
)

from core.gesture_profiles import GestureProfileStore
from core.runtime_paths import asset_path
from core.settings_store import SettingsStore
from platforms.windows.startup_manager import set_start_with_windows
from ui.event_bridge import EventBridge
from ui.pages.activity_page import GESTURES, GESTURE_LABELS, GestureActionEditor
from ui.pages.camera_page import frame_to_pixmap


class WizardSidebar(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("wizardSidebar")
        self.setFixedWidth(218)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 34, 22, 28)
        layout.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(
            QPixmap(str(asset_path("room_os_logo.png"))).scaled(
                58, 58,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        layout.addWidget(logo)
        brand = QLabel("ROOM OS")
        brand.setObjectName("wizardBrand")
        layout.addWidget(brand)
        caption = QLabel("Configuración inicial")
        caption.setObjectName("wizardCaption")
        layout.addWidget(caption)
        layout.addSpacing(24)
        self.steps: list[QLabel] = []
        for number, title in enumerate((
            "Bienvenida", "Acciones", "Gestos", "Mouse", "Finalizar",
        ), start=1):
            label = QLabel(f"{number:02d}   {title}")
            label.setObjectName("wizardStep")
            layout.addWidget(label)
            self.steps.append(label)
        layout.addStretch()
        privacy = QLabel("Tus perfiles se guardan solamente en este equipo.")
        privacy.setObjectName("wizardCaption")
        privacy.setWordWrap(True)
        layout.addWidget(privacy)

    def set_current_step(self, page_id: int) -> None:
        for index, label in enumerate(self.steps):
            label.setObjectName(
                "wizardStepActive" if index == page_id else "wizardStep"
            )
            label.style().unpolish(label)
            label.style().polish(label)


class WelcomePage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Configura Room OS antes de empezar")
        self.setSubTitle("Ningún gesto ejecutará acciones mientras este asistente esté abierto.")
        layout = QVBoxLayout(self)
        text = QLabel(
            "En los siguientes pasos podrás asignar acciones, registrar cómo haces "
            "tus gestos y calibrar el mouse. Las imágenes no se guardan: el "
            "entrenamiento conserva únicamente coordenadas normalizadas."
        )
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addSpacing(20)
        steps = (
            "1   Elegir qué puede hacer cada gesto",
            "2   Registrar la forma de tus manos",
            "3   Calibrar el área y la postura del mouse",
            "4   Configurar inicio y bandeja de Windows",
            "5   Revisar todo antes de activar acciones",
        )
        for step in steps:
            label = QLabel(step)
            label.setObjectName("sectionTitle")
            layout.addWidget(label)
        layout.addStretch()


class ActionSetupPage(QWizardPage):
    def __init__(self, registry: Any, mapping: dict[str, str]) -> None:
        super().__init__()
        self.setTitle("Asigna gestos a acciones")
        self.setSubTitle("Puedes dejar cualquier gesto sin acción y cambiarlo después.")
        layout = QVBoxLayout(self)
        self.editor = GestureActionEditor(registry, mapping)
        layout.addWidget(self.editor)


class GestureTrainingPage(QWizardPage):
    TARGET_SAMPLES = 30

    def __init__(self, profile_store: GestureProfileStore) -> None:
        super().__init__()
        self.setTitle("Entrena tus gestos")
        self.setSubTitle("Registra cada gesto con una mano a la vez y desde un ángulo cómodo.")
        self._profiles = profile_store
        self._recording = False
        self._samples: list[list[dict[str, Any]]] = []

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.gesture = QComboBox()
        for gesture in GESTURES:
            self.gesture.addItem(GESTURE_LABELS[gesture], gesture)
        self.hand = QComboBox()
        self.hand.addItem("Mano derecha", "Right")
        self.hand.addItem("Mano izquierda", "Left")
        self.record = QPushButton("Registrar 30 muestras")
        self.record.setObjectName("primary")
        controls.addWidget(self.gesture)
        controls.addWidget(self.hand)
        controls.addWidget(self.record)
        layout.addLayout(controls)
        self.preview = QLabel("Esperando cámara…")
        self.preview.setObjectName("video")
        self.preview.setMinimumHeight(260)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.preview, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, self.TARGET_SAMPLES)
        layout.addWidget(self.progress)
        self.status = QLabel("Selecciona un gesto y pulsa Registrar.")
        self.status.setObjectName("muted")
        layout.addWidget(self.status)
        self.record.clicked.connect(self._start_recording)

    def _start_recording(self) -> None:
        self._samples = []
        self._recording = True
        self.progress.setValue(0)
        self.status.setText("Mantén el gesto y muévelo ligeramente dentro del encuadre.")

    def set_frame(self, frame: Any, fps: float) -> None:
        pixmap = frame_to_pixmap(frame).scaled(
            self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(pixmap)

    def handle_event(self, name: str, payload: Any) -> None:
        if not self._recording or name != "hand.detected" or not isinstance(payload, dict):
            return
        selected_hand = str(self.hand.currentData())
        hand = next(
            (item for item in payload.get("hands", []) if item.get("handedness") == selected_hand),
            None,
        )
        if hand is None or len(hand.get("landmarks", [])) != 21:
            self.status.setText(f"Muestra únicamente la mano {selected_hand}.")
            return
        self._samples.append(hand["landmarks"])
        self.progress.setValue(len(self._samples))
        if len(self._samples) < self.TARGET_SAMPLES:
            return
        self._recording = False
        try:
            profile = self._profiles.train(
                str(self.gesture.currentData()), selected_hand, self._samples
            )
            self.status.setText(
                f"Perfil guardado: {profile['gesture']} · {profile['sample_count']} muestras."
            )
        except ValueError as error:
            self.status.setText(str(error))


class MouseCalibrationPage(QWizardPage):
    def __init__(self, mouse: Any) -> None:
        super().__init__()
        self.setTitle("Calibra el mouse")
        self.setSubTitle("Levanta solo el índice y lleva el punto amarillo a cada objetivo azul.")
        self._mouse = mouse
        layout = QVBoxLayout(self)
        self.preview = QLabel("Esperando cámara…")
        self.preview.setObjectName("video")
        self.preview.setMinimumHeight(330)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.preview, 1)
        row = QHBoxLayout()
        self.status = QLabel("La calibración es opcional y puede repetirse después.")
        self.status.setObjectName("muted")
        self.start = QPushButton("Iniciar calibración")
        self.start.setObjectName("primary")
        self.start.setEnabled(mouse is not None)
        row.addWidget(self.status)
        row.addStretch()
        row.addWidget(self.start)
        layout.addLayout(row)
        self.start.clicked.connect(self._start)

    def _start(self) -> None:
        self._mouse.set_draw_enabled(True)
        self._mouse.set_enabled(True, reason="first_run_calibration")
        self._mouse.start_calibration()
        self.status.setText("Calibración en curso. Mantén únicamente el índice levantado.")

    def set_frame(self, frame: Any, fps: float) -> None:
        pixmap = frame_to_pixmap(frame).scaled(
            self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(pixmap)

    def handle_event(self, name: str, payload: Any) -> None:
        if name == "virtual_mouse.calibration_completed":
            self.status.setText("Calibración guardada correctamente.")
        elif name == "virtual_mouse.calibration_cancelled":
            self.status.setText("Calibración cancelada. Puedes intentarlo de nuevo.")


class StartupPage(QWizardPage):
    def __init__(self, start_enabled: bool, close_to_tray: bool) -> None:
        super().__init__()
        self.setTitle("Listo para comenzar")
        self.setSubTitle("Estas opciones pueden cambiarse más adelante.")
        layout = QVBoxLayout(self)
        self.start_with_windows = QCheckBox("Iniciar Room OS con Windows")
        self.start_with_windows.setChecked(start_enabled)
        layout.addWidget(self.start_with_windows)
        self.close_to_tray = QCheckBox("Mantener Room OS en la bandeja al cerrar la ventana")
        self.close_to_tray.setChecked(close_to_tray)
        layout.addWidget(self.close_to_tray)
        note = QLabel(
            "Room OS iniciará con el mouse apagado. Las acciones peligrosas nunca "
            "se pueden asignar directamente a un gesto."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addSpacing(18)
        for item in (
            "✓ La configuración se guardará localmente",
            "✓ El mouse permanecerá apagado al iniciar",
            "✓ Podrás editar las asignaciones desde Acciones",
            "✓ Room OS podrá repararse desde su lanzador",
        ):
            summary = QLabel(item)
            summary.setObjectName("sectionTitle")
            layout.addWidget(summary)
        layout.addStretch()


class FirstRunWizard(QWizard):
    def __init__(
        self,
        event_bus: Any,
        registry: Any,
        settings: SettingsStore,
        profiles: GestureProfileStore,
        mouse: Any,
        project_root: Path,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Configuración inicial de Room OS")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage)
        self.setOption(QWizard.WizardOption.NoBackButtonOnLastPage)
        self.setPixmap(
            QWizard.WizardPixmap.LogoPixmap,
            QPixmap(str(asset_path("room_os_logo.png"))).scaled(
                54, 54,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ),
        )
        self.setButtonText(QWizard.WizardButton.BackButton, "Atrás")
        self.setButtonText(QWizard.WizardButton.NextButton, "Siguiente")
        self.setButtonText(QWizard.WizardButton.CancelButton, "Cancelar")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Terminar")
        self.resize(980, 650)
        self.setMinimumSize(900, 600)
        self.sidebar = WizardSidebar()
        self.setSideWidget(self.sidebar)
        self._settings = settings
        self._mouse = mouse
        self._project_root = project_root
        self.actions_page = ActionSetupPage(
            registry, settings.get("gesture_actions", {})
        )
        self.training_page = GestureTrainingPage(profiles)
        self.mouse_page = MouseCalibrationPage(mouse)
        self.startup_page = StartupPage(
            settings.get("start_with_windows", False),
            settings.get("close_to_tray", False),
        )
        self.addPage(WelcomePage())
        self.addPage(self.actions_page)
        self.addPage(self.training_page)
        self.addPage(self.mouse_page)
        self.addPage(self.startup_page)
        self.currentIdChanged.connect(self.sidebar.set_current_step)
        self.sidebar.set_current_step(0)
        self._bridge = EventBridge(event_bus)
        self._bridge.frame_ready.connect(self.training_page.set_frame)
        self._bridge.frame_ready.connect(self.mouse_page.set_frame)
        self._bridge.event_received.connect(self.training_page.handle_event)
        self._bridge.event_received.connect(self.mouse_page.handle_event)

    def accept(self) -> None:
        start_enabled = self.startup_page.start_with_windows.isChecked()
        try:
            set_start_with_windows(start_enabled, self._project_root)
        except OSError as error:
            QMessageBox.warning(self, "Inicio con Windows", str(error))
            return
        if self._mouse is not None:
            self._mouse.set_enabled(False, reason="setup_complete")
            self._mouse.set_draw_enabled(False)
        self._settings.update(
            setup_complete=True,
            gesture_actions=self.actions_page.editor.mapping(),
            start_with_windows=start_enabled,
            close_to_tray=self.startup_page.close_to_tray.isChecked(),
        )
        self._bridge.close()
        super().accept()

    def reject(self) -> None:
        if self._mouse is not None:
            self._mouse.set_enabled(False, reason="setup_cancelled")
        self._bridge.close()
        super().reject()
