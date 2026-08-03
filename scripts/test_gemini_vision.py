"""Prueba manual de Gemini Vision sin ejecutar acciones de Room OS."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import CAMERA_MIRROR  # noqa: E402
from services.gemini_client import GeminiClient  # noqa: E402
from services.vision_ai_service import VisionAIService  # noqa: E402


def capture_camera_frame() -> np.ndarray:
    backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
    capture = cv2.VideoCapture(0, backend)
    if not capture.isOpened():
        raise RuntimeError("No se pudo abrir la camara. Cierra primero Room OS.")
    try:
        frame = None
        for _ in range(12):
            success, candidate = capture.read()
            if success:
                frame = candidate
        if frame is None:
            raise RuntimeError("La camara no entrego ningun frame")
        return cv2.flip(frame, 1) if CAMERA_MIRROR else frame
    finally:
        capture.release()


def load_image(path: str) -> np.ndarray:
    image_path = Path(path).expanduser().resolve()
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"No se pudo leer: {image_path}")
    return image


def capture_screen() -> tuple[np.ndarray, str]:
    from PIL import ImageGrab

    return np.asarray(ImageGrab.grab(all_screens=True)), "RGB"


def print_health(service: VisionAIService) -> bool:
    health = service.health_check()
    print(json.dumps(health, indent=2, ensure_ascii=False))
    if not health.get("available"):
        print(f"\n{service.setup_hint}")
    return bool(health.get("available"))


def print_result(call) -> Optional[dict[str, Any]]:
    started = time.perf_counter()
    try:
        result = call()
    except Exception as error:
        print(f"ERROR: {error}")
        return None
    print(f"Modelo: {result.get('model')}")
    print(f"Tiempo: {(time.perf_counter() - started) * 1000:.1f} ms")
    print(f"Dimensiones: {json.dumps(result.get('image_dimensions'))}")
    print(f"Estructurada: {result.get('structured')}")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return result


def analyze_camera(
    service: VisionAIService,
    question: Optional[str] = None,
    mode: str = "describe_scene",
) -> Optional[dict[str, Any]]:
    frame = capture_camera_frame()
    if question:
        return print_result(lambda: service.answer_question(frame, question))
    methods = {
        "describe_scene": service.describe_scene,
        "read_text": service.read_text,
        "inspect_workspace": service.inspect_workspace,
    }
    return print_result(lambda: methods[mode](frame))


def menu(service: VisionAIService) -> int:
    while True:
        print(
            "\n1. Describir camara\n2. Preguntar sobre camara\n3. Leer texto\n"
            "4. Inspeccionar escritorio\n5. Analizar imagen\n6. Analizar pantalla\n"
            "7. Verificar Gemini\n8. Limpiar historial\n9. Salir"
        )
        option = input("Opcion: ").strip()
        try:
            if option == "1":
                analyze_camera(service)
            elif option == "2":
                analyze_camera(service, input("Pregunta: ").strip())
            elif option == "3":
                analyze_camera(service, mode="read_text")
            elif option == "4":
                analyze_camera(service, mode="inspect_workspace")
            elif option == "5":
                image = load_image(input("Ruta: ").strip().strip('"'))
                question = input("Pregunta opcional: ").strip()
                print_result(lambda: service.analyze_screen(image, question or None))
            elif option == "6":
                image, color_space = capture_screen()
                question = input("Pregunta opcional: ").strip()
                print_result(
                    lambda: service.analyze_screen(
                        image,
                        question or None,
                        color_space=color_space,
                    )
                )
            elif option == "7":
                print_health(service)
            elif option == "8":
                service.clear_session()
                print("Historial en memoria eliminado")
            elif option == "9":
                return 0
            else:
                print("Opcion no valida")
        except Exception as error:
            print(f"ERROR: {error}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", action="store_true")
    parser.add_argument("--image")
    parser.add_argument("--screen", action="store_true")
    parser.add_argument("--question")
    parser.add_argument("--health", action="store_true")
    parser.add_argument(
        "--mode",
        choices=("describe_scene", "read_text", "inspect_workspace"),
        default="describe_scene",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    service = VisionAIService(GeminiClient())
    try:
        if args.health:
            return 0 if print_health(service) else 1
        if not print_health(service):
            return 1
        if args.camera:
            return 0 if analyze_camera(service, args.question, args.mode) else 1
        if args.image:
            image = load_image(args.image)
            return 0 if print_result(
                lambda: service.analyze_screen(image, args.question)
            ) else 1
        if args.screen:
            image, color_space = capture_screen()
            return 0 if print_result(
                lambda: service.analyze_screen(
                    image,
                    args.question,
                    color_space=color_space,
                )
            ) else 1
        return menu(service)
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())

