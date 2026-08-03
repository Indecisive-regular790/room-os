"""Punto de entrada de Room OS."""

import logging
import os
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from config import ACTION_ENABLED, LOG_LEVEL, WINDOWS_ENABLED
from core.action_engine import ActionEngine
from core.action_registry import ActionRegistry
from core.event_bus import EventBus
from core.gesture_action_mapper import GestureActionMapper
from core.gesture_profiles import GestureProfileStore
from core.logger import configure_logging
from core.runtime_paths import application_data_dir, application_root, migrate_legacy_data
from core.single_instance import SingleInstanceGuard
from core.settings_store import SettingsStore
from modules.camera import CameraModule, CameraNotFoundError
from modules.face_recognition import FaceRecognizer
from modules.gesture_recognition import GestureRecognitionModule
from modules.hand_tracking import HandTrackingModule
from modules.presence_detection import PresenceDetector
from modules.virtual_mouse import VirtualMouse
from modules.visual_intelligence import VisualIntelligence
from services.gemini_client import GeminiClient
from services.vision_ai_service import VisionAIService
from ui.main_window import MainWindow
from ui.setup_wizard import FirstRunWizard
from ui.splash import StartupSplash
from ui.theme import apply_theme


logger = logging.getLogger(__name__)


def main() -> int:
    """Inicia Room OS y ejecuta el módulo de cámara."""
    migrated = migrate_legacy_data()
    configure_logging(LOG_LEVEL)
    logger.info("Iniciando Room OS")
    if migrated:
        logger.info("Datos antiguos migrados: %d archivos", len(migrated))

    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName("Room OS")
    application.setApplicationDisplayName("Room OS")
    application.setStyle("Fusion")
    font_family = apply_theme(application)
    logger.info("Tipografía activa: %s", font_family)

    instance_guard = SingleInstanceGuard()
    if not instance_guard.acquire():
        logger.info("Room OS ya estaba abierto; se solicitó restaurar la ventana")
        return 0

    def activate_current_window() -> None:
        active = application.activeWindow()
        if active is not None:
            active.showNormal()
            active.raise_()
            active.activateWindow()

    instance_guard.set_activation_handler(activate_current_window)
    try:
        splash = StartupSplash()
    except Exception as error:
        logger.exception("No se pudo crear la pantalla de arranque")
        QMessageBox.critical(
            None, "Room OS no pudo iniciar",
            f"No se pudo preparar la interfaz.\n\nDetalle: {error}",
        )
        instance_guard.close()
        return 1
    splash.show_status("Preparando Room OS…")
    splash.show()
    application.processEvents()

    event_bus = EventBus()
    project_root = application_root()
    camera = None
    visual_intelligence = None
    face_recognizer = None
    presence_detector = None
    virtual_mouse = None
    gesture_actions = None
    gesture_recognition = None
    hand_tracking = None
    action_engine = None
    return_code = 0

    try:
        splash.show_status("Cargando configuración y módulos…")
        application.processEvents()
        settings = SettingsStore()
        gesture_profiles = GestureProfileStore()
        windows_active = WINDOWS_ENABLED and os.name == "nt"
        action_registry = ActionRegistry(
            auto_discover=windows_active,
            enabled_config=ACTION_ENABLED,
        )
        action_engine = ActionEngine(event_bus, action_registry)
        hand_tracking = HandTrackingModule(event_bus)
        gesture_recognition = GestureRecognitionModule(
            event_bus, profile_store=gesture_profiles
        )
        gesture_actions = GestureActionMapper(
            event_bus,
            gesture_map=settings.get("gesture_actions", {}),
        )
        virtual_mouse = (
            VirtualMouse(event_bus, enabled=False, draw_overlay=False)
            if windows_active else None
        )
        presence_detector = PresenceDetector(event_bus, draw_overlay=False)
        face_recognizer = FaceRecognizer(event_bus, draw_overlay=False)
        gemini_client = GeminiClient()
        vision_ai_service = VisionAIService(gemini_client)
        visual_intelligence = VisualIntelligence(
            event_bus, vision_ai_service, draw_overlay=False
        )
        camera = CameraModule(event_bus=event_bus, show_window=False)
        logger.info(
            "Plataforma Windows: %s | acciones registradas: %d",
            "activa" if windows_active else "inactiva",
            len(action_registry),
        )

        splash.show_status("Iniciando cámara y reconocimiento local…")
        application.processEvents()
        action_engine.start()
        visual_intelligence.start()
        hand_tracking.start()
        gesture_recognition.start()
        if virtual_mouse is not None:
            virtual_mouse.start()
        presence_detector.start()
        face_recognizer.start()
        if face_recognizer.enabled and face_recognizer.has_registered_profiles:
            logger.info("Hay al menos un perfil facial local registrado")
        elif face_recognizer.enabled:
            logger.warning(
                "Reconocimiento facial activo sin perfiles; "
                "ejecuta scripts/register_face.py"
            )
        camera.start_background()
        if not settings.get("setup_complete", False):
            splash.close()
            wizard = FirstRunWizard(
                event_bus,
                action_registry,
                settings,
                gesture_profiles,
                virtual_mouse,
                project_root,
            )
            if wizard.exec() != FirstRunWizard.DialogCode.Accepted:
                logger.info("Configuración inicial cancelada")
                return_code = 0
                return return_code
            gesture_actions.set_gesture_map(settings.get("gesture_actions", {}))

        gesture_actions.start()
        window = MainWindow(
            event_bus,
            action_registry,
            {
                "hands": hand_tracking,
                "gestures": gesture_recognition,
                "mouse": virtual_mouse,
                "presence": presence_detector,
                "faces": face_recognizer,
                "ai": visual_intelligence,
            },
            settings=settings,
            gesture_mapper=gesture_actions,
        )
        instance_guard.set_activation_handler(window._restore_window)
        if settings.get("launch_minimized", False):
            window.showMinimized()
        else:
            window.show()
        splash.finish(window)
        return_code = application.exec()
    except KeyboardInterrupt:
        logger.info("Cierre solicitado desde el teclado")
    except Exception as error:
        logger.exception("Room OS se cerró por un error inesperado")
        splash.close()
        QMessageBox.critical(
            None,
            "Room OS no pudo iniciar",
            "Ocurrió un error al iniciar Room OS. Tus datos no se modificaron.\n\n"
            f"Detalle: {error}\n\n"
            f"Registro: {application_data_dir() / 'logs' / 'room_os.log'}",
        )
        return_code = 1
    finally:
        if camera is not None:
            camera.close()
        if visual_intelligence is not None:
            visual_intelligence.close()
        if face_recognizer is not None:
            face_recognizer.close()
        if presence_detector is not None:
            presence_detector.close()
        if virtual_mouse is not None:
            virtual_mouse.close()
        if gesture_actions is not None:
            gesture_actions.close()
        if gesture_recognition is not None:
            gesture_recognition.close()
        if hand_tracking is not None:
            hand_tracking.close()
        if action_engine is not None:
            action_engine.close()
        instance_guard.close()

    logger.info("Room OS se cerró correctamente")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
