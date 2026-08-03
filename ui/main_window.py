from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QMenu,
    QPushButton, QStackedWidget, QStyle, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from ui.event_bridge import EventBridge
from core.runtime_paths import application_root, asset_path
from platforms.windows.startup_manager import set_start_with_windows
from ui.pages.activity_page import ActionsPage, ActivityPage, SettingsPage
from ui.pages.ai_page import AIPage
from ui.pages.camera_page import CameraPage
from ui.pages.home_page import HomePage


class MainWindow(QMainWindow):
    NAVIGATION = (
        ("Inicio", "home"), ("Cámara", "camera"), ("IA", "ai"),
        ("Gestos", "gestures"), ("Mouse", "mouse"),
        ("Presencia", "presence"), ("Acciones", "actions"),
        ("Configuración", "settings"),
    )

    def __init__(
        self,
        event_bus: Any,
        registry: Any,
        modules: dict[str, Any],
        settings: Any = None,
        gesture_mapper: Any = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Room OS")
        self.setMinimumSize(980, 620)
        self.resize(1180, 680)
        self._event_bus = event_bus
        self._modules = modules
        self._settings = settings
        self._gesture_mapper = gesture_mapper
        self._force_quit = False
        self._tray_notice_shown = False

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        shell.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        shell.addWidget(self.stack, 1)
        self._pages: dict[str, QWidget] = {}
        self._create_pages(registry)

        self.bridge = EventBridge(event_bus)
        self.bridge.frame_ready.connect(self._on_frame)
        self.bridge.event_received.connect(self._on_event)
        self._nav_buttons[0].setChecked(True)
        self.stack.setCurrentWidget(self._pages["home"])
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)
        available = self.screen().availableGeometry()
        self.move(available.center() - self.rect().center())
        self._create_tray()

    def _create_tray(self) -> None:
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray_icon = QIcon(str(asset_path("room_os_tray.png")))
        if tray_icon.isNull():
            tray_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        self.tray = QSystemTrayIcon(tray_icon, self)
        self.tray.setToolTip("Room OS")
        menu = QMenu()
        show_action = QAction("Abrir Room OS", self)
        show_action.triggered.connect(self._restore_window)
        mouse_action = QAction("Alternar modo mouse", self)
        mouse_action.triggered.connect(
            lambda: self.mouse_mode_toggle.setChecked(
                not self.mouse_mode_toggle.isChecked()
            )
        )
        exit_action = QAction("Salir", self)
        exit_action.triggered.connect(self._quit_from_tray)
        menu.addAction(show_action)
        menu.addAction(mouse_action)
        menu.addSeparator()
        menu.addAction(exit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self._restore_window()
            if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None
        )
        self.tray.show()

    def _restore_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self) -> None:
        self._force_quit = True
        self.close()
        QApplication.quit()

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(196)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 22, 16, 18)
        layout.setSpacing(5)
        identity = QHBoxLayout()
        identity.setSpacing(10)
        logo = QLabel()
        logo.setFixedSize(34, 34)
        logo.setPixmap(
            QPixmap(str(asset_path("room_os_logo.png"))).scaled(
                32, 32,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        identity.addWidget(logo)
        labels = QVBoxLayout()
        labels.setSpacing(0)
        brand = QLabel("ROOM OS")
        brand.setObjectName("brand")
        labels.addWidget(brand)
        byline = QLabel("Visual workspace")
        byline.setObjectName("muted")
        labels.addWidget(byline)
        identity.addLayout(labels)
        layout.addLayout(identity)
        layout.addSpacing(22)
        self._nav_buttons: list[QPushButton] = []
        for label, key in self.NAVIGATION:
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, page=key: self.show_page(page))
            layout.addWidget(button)
            self._nav_buttons.append(button)
        layout.addStretch()
        self.sidebar_state = QLabel("●  Sistema iniciando")
        self.sidebar_state.setObjectName("muted")
        layout.addWidget(self.sidebar_state)
        return sidebar

    def _create_pages(self, registry: Any) -> None:
        home = HomePage()
        toggles = {
            "fps": (True, lambda value: None),
            "hands": (True, self._modules["hands"].set_draw_enabled),
            "gestures": (True, self._modules["gestures"].set_draw_enabled),
            "faces": (False, self._modules["faces"].set_draw_enabled),
            "presence": (False, self._modules["presence"].set_draw_enabled),
            "mouse": (False, self._modules["mouse"].set_draw_enabled if self._modules.get("mouse") else lambda value: None),
        }
        camera = CameraPage(toggles)
        ai = AIPage(self._event_bus, lambda: camera.latest_frame)
        gestures = ActivityPage("Gestos", "Reconocimiento estable de señas de ambas manos.", "No hay un gesto confirmado.")
        mouse = ActivityPage("Mouse", "Estado y calibración del control virtual.", "Mouse virtual listo para recibir eventos.")
        self.mouse_mode_toggle = QCheckBox("Modo mouse exclusivo")
        if self._modules.get("mouse") is not None:
            self.mouse_mode_toggle.setChecked(self._modules["mouse"].enabled)
            self.mouse_mode_toggle.toggled.connect(self._modules["mouse"].set_enabled)
            calibrate_button = QPushButton("Calibrar en cámara")
            calibrate_button.clicked.connect(
                lambda: self._start_mouse_calibration(camera)
            )
            mouse.add_control(calibrate_button)
        else:
            self.mouse_mode_toggle.setEnabled(False)
        mouse.add_control(self.mouse_mode_toggle)
        presence = ActivityPage("Presencia", "Detección local de personas e identidad.", "Esperando observaciones de la cámara.")
        mapping = (
            self._settings.get("gesture_actions", {})
            if self._settings is not None else {}
        )
        actions = ActionsPage(registry, mapping, self._save_gesture_mapping)
        settings_page = SettingsPage(
            self._settings,
            self._save_application_settings,
            self._reset_first_run,
        )
        self._pages = {
            "home": home, "camera": camera, "ai": ai, "gestures": gestures,
            "mouse": mouse, "presence": presence, "actions": actions,
            "settings": settings_page,
        }
        for _, key in self.NAVIGATION:
            self.stack.addWidget(self._pages[key])

    def _save_gesture_mapping(self, mapping: dict[str, str]) -> None:
        if self._settings is not None:
            self._settings.update(gesture_actions=mapping)
        if self._gesture_mapper is not None:
            self._gesture_mapper.set_gesture_map(mapping)

    def _save_application_settings(self, start_with_windows: bool, close_to_tray: bool) -> None:
        if self._settings is None:
            return
        set_start_with_windows(start_with_windows, application_root())
        self._settings.update(
            start_with_windows=start_with_windows,
            close_to_tray=close_to_tray,
        )

    def _reset_first_run(self) -> None:
        if self._settings is not None:
            self._settings.update(setup_complete=False)

    def _start_mouse_calibration(self, camera: CameraPage) -> None:
        mouse = self._modules.get("mouse")
        if mouse is None:
            return
        mouse.set_enabled(True, reason="ui_calibration")
        camera.checks["mouse"].setChecked(True)
        mouse.start_calibration()
        self.show_page("camera")

    def show_page(self, key: str) -> None:
        self.stack.setCurrentWidget(self._pages[key])
        selected = [item[1] for item in self.NAVIGATION].index(key)
        for index, button in enumerate(self._nav_buttons):
            button.setChecked(index == selected)

    def _on_frame(self, frame: Any, fps: float) -> None:
        self._pages["camera"].set_frame(frame, fps)
        home: HomePage = self._pages["home"]  # type: ignore[assignment]
        home.update_status("camera", f"{fps:.1f} FPS")
        self.sidebar_state.setText("●  Sistema activo")

    def _on_event(self, name: str, payload: Any) -> None:
        data = payload if isinstance(payload, dict) else {}
        home: HomePage = self._pages["home"]  # type: ignore[assignment]
        self._pages["ai"].handle_event(name, payload)
        if name == "camera.error":
            message = str(data.get("error") or "Cámara no disponible")
            retry = float(data.get("retry_seconds") or 0)
            suffix = f" Reintentando en {retry:.0f} s…" if retry else ""
            self._pages["camera"].set_error(message + suffix)
            home.update_status("camera", "Reconectando")
        elif name.startswith("vision_ai."):
            states = {"vision_ai.ready": "Lista", "vision_ai.started": "Analizando", "vision_ai.completed": "Lista", "vision_ai.failed": "Error", "vision_ai.unavailable": "No disponible", "vision_ai.cancelled": "Lista", "vision_ai.rate_limited": "En espera"}
            if name in states:
                home.update_status("ai", states[name])
        elif name.startswith("gesture."):
            gesture = str(data.get("gesture") or "Ninguno")
            hand = str(data.get("handedness") or "")
            text = f"{gesture} · {hand}" if hand else gesture
            home.update_status("gesture", gesture if name != "gesture.ended" else "Ninguno")
            self._pages["gestures"].set_summary(text)
            if name != "gesture.held":
                self._pages["gestures"].add_event(f"{name.split('.')[-1]} · {text}")
        elif name.startswith("presence."):
            state = str(data.get("state") or ("Presente" if name != "presence.exited" else "Vacío"))
            translated = {
                "EMPTY": "Vacío", "PRESENT": "Presente",
                "MULTIPLE_PEOPLE": "Varias personas",
                "TEMPORARILY_LOST": "Temporalmente perdido",
            }.get(state, state.replace("_", " ").title())
            home.update_status("presence", translated)
            self._pages["presence"].set_summary(translated)
            if name != "presence.updated":
                self._pages["presence"].add_event(name.split(".")[-1].replace("_", " ").title())
        elif name.startswith("face."):
            identity = str(data.get("display_name") or data.get("identity") or "Desconocido")
            self._pages["presence"].add_event(f"Rostro · {identity}")
        elif name.startswith("virtual_mouse."):
            state = name.split(".")[-1].replace("_", " ").title()
            if name in {"virtual_mouse.enabled", "virtual_mouse.disabled"}:
                self.mouse_mode_toggle.blockSignals(True)
                self.mouse_mode_toggle.setChecked(name == "virtual_mouse.enabled")
                self.mouse_mode_toggle.blockSignals(False)
            self._pages["mouse"].set_summary(state)
            self._pages["mouse"].add_event(state)

    def closeEvent(self, event) -> None:
        close_to_tray = bool(
            self._settings is not None
            and self._settings.get("close_to_tray", False)
        )
        if self.tray is not None and close_to_tray and not self._force_quit:
            self.hide()
            event.ignore()
            if not self._tray_notice_shown:
                self.tray.showMessage(
                    "Room OS sigue activo",
                    "Puedes abrirlo o salir desde el icono de la bandeja.",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )
                self._tray_notice_shown = True
            return
        self.bridge.close()
        if self.tray is not None:
            self.tray.hide()
        event.accept()
