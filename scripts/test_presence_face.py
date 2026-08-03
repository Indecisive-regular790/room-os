"""Prueba manual de presencia y rostros sin acciones ni automatizaciones."""

import argparse
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
from modules.face_recognition import FaceRecognizer  # noqa: E402
from modules.presence_detection import PresenceDetector  # noqa: E402


logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--presence-only",
        action="store_true",
        help="Desactiva reconocimiento y conserva únicamente presencia",
    )
    args = parser.parse_args()
    configure_logging(LOG_LEVEL)
    bus = EventBus()
    last_event = {"text": "ninguno"}

    def remember(event_name: str):
        def callback(payload: Any) -> None:
            if isinstance(payload, dict):
                identity = payload.get("identity", "")
                last_event["text"] = f"{event_name} {identity}".strip()
        return callback

    watched_events = (
        "presence.entered",
        "presence.exited",
        "presence.temporarily_lost",
        "presence.restored",
        "presence.multiple_people",
        "face.recognized",
        "face.unknown",
        "face.lost",
    )
    callbacks = {}
    for event_name in watched_events:
        callbacks[event_name] = remember(event_name)
        bus.subscribe(event_name, callbacks[event_name])

    def draw_help(event_data: Any) -> None:
        if not isinstance(event_data, dict) or event_data.get("frame") is None:
            return
        frame = event_data["frame"]
        cv2.putText(
            frame,
            f"Último evento: {last_event['text']}",
            (20, 228),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.54,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            "Prueba: vacío, entrada/salida, cara cubierta, dos personas y distinta luz | Q cerrar",
            (20, 256),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (220, 220, 220),
            1,
            cv2.LINE_AA,
        )

    bus.subscribe("camera.frame", draw_help)
    camera = CameraModule(event_bus=bus, window_name="Room OS - Prueba presencia")
    presence = PresenceDetector(bus)
    face = FaceRecognizer(bus, enabled=not args.presence_only)
    try:
        presence.start()
        face.start()
        camera.run()
    except CameraNotFoundError as error:
        logger.error("%s", error)
        return 1
    finally:
        camera.close()
        face.close()
        presence.close()
        bus.unsubscribe("camera.frame", draw_help)
        for event_name, callback in callbacks.items():
            bus.unsubscribe(event_name, callback)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
