"""Prueba manual segura del mouse virtual sin ejecutar acciones de aplicaciones."""

import logging
import sys
from pathlib import Path
from typing import Any

import cv2


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import LOG_LEVEL  # noqa: E402
from core.event_bus import EventBus  # noqa: E402
from core.logger import configure_logging  # noqa: E402
from modules.camera import CameraModule, CameraNotFoundError  # noqa: E402
from modules.gesture_recognition import GestureRecognitionModule  # noqa: E402
from modules.hand_tracking import HandTrackingModule  # noqa: E402
from modules.virtual_mouse import VirtualMouse  # noqa: E402


logger = logging.getLogger(__name__)


def draw_instructions(event_data: Any) -> None:
    if not isinstance(event_data, dict) or event_data.get("frame") is None:
        return
    frame = event_data["frame"]
    lines = (
        "Indice: mover | pellizco pulgar-indice: clic/arrastre",
        "Pulgar-medio: clic derecho | indice+medio sostenidos: scroll",
        "F8: activar/desactivar | F9: calibrar | ESC: liberar | Q: cerrar",
        "Modo seguro: los gestos NO abren aplicaciones",
    )
    for index, line in enumerate(lines):
        cv2.putText(
            frame,
            line,
            (20, 75 + index * 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )


def main() -> int:
    configure_logging(LOG_LEVEL)
    bus = EventBus()
    camera = CameraModule(event_bus=bus, window_name="Room OS - Prueba mouse")
    hand_tracking = HandTrackingModule(bus)
    gesture_recognition = GestureRecognitionModule(bus)
    virtual_mouse = VirtualMouse(bus)

    bus.subscribe("camera.frame", draw_instructions)
    try:
        hand_tracking.start()
        gesture_recognition.start()
        virtual_mouse.start()
        camera.run()
    except CameraNotFoundError as error:
        logger.error("%s", error)
        return 1
    except KeyboardInterrupt:
        logger.info("Prueba interrumpida")
    finally:
        camera.close()
        virtual_mouse.close()
        gesture_recognition.close()
        hand_tracking.close()
        bus.unsubscribe("camera.frame", draw_instructions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
