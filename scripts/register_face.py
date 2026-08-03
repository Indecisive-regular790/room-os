"""Registro explícito y local de un perfil facial autorizado."""

import logging
import os
import sys
import time
from pathlib import Path

import cv2


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import (  # noqa: E402
    AUTHORIZED_PROFILE,
    FACE_DATABASE_PATH,
    FACE_MIN_SIZE_PIXELS,
    FACE_REGISTRATION_BLUR_THRESHOLD,
    FACE_REGISTRATION_CAPTURES_PER_POSE,
    PRESENCE_MIN_CONFIDENCE,
)
from modules.presence_detection import MediaPipeFaceDetector  # noqa: E402
from services.face_database import FaceDatabase, FaceDatabaseError  # noqa: E402
from services.face_embedding import (  # noqa: E402
    blur_score,
    crop_face,
    generate_face_embedding,
)


logger = logging.getLogger(__name__)
POSES = (
    "Mira al frente",
    "Gira ligeramente a la izquierda",
    "Gira ligeramente a la derecha",
    "Mira ligeramente arriba",
    "Mira ligeramente abajo",
)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    database = FaceDatabase(FACE_DATABASE_PATH)
    profile_name = input(
        f"Nombre técnico del perfil [{AUTHORIZED_PROFILE}]: "
    ).strip() or AUTHORIZED_PROFILE
    display_name = input("Nombre visible [Usuario autorizado]: ").strip() or "Usuario autorizado"
    try:
        database.validate_profile_name(profile_name)
    except FaceDatabaseError as error:
        logger.error("%s", error)
        return 1

    if database.has_profile(profile_name):
        confirmation = input(
            f"El perfil '{profile_name}' ya existe. Escribe REEMPLAZAR: "
        ).strip()
        if confirmation != "REEMPLAZAR":
            logger.info("Registro cancelado")
            return 0

    backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
    capture = cv2.VideoCapture(0, backend)
    if not capture.isOpened():
        logger.error("No se pudo abrir la cámara")
        return 1

    detector = MediaPipeFaceDetector(PRESENCE_MIN_CONFIDENCE)
    embeddings = []
    images = []
    pose_index = 0
    pose_captures = 0
    last_capture_at = 0.0
    status = "Coloca un solo rostro dentro de la cámara"
    try:
        while pose_index < len(POSES):
            success, frame = capture.read()
            if not success:
                logger.error("Se perdió la señal de la cámara")
                return 1
            frame = cv2.flip(frame, 1)
            boxes = detector.detect(frame)
            now = time.perf_counter()

            if len(boxes) != 1:
                status = "Debe aparecer exactamente un rostro"
            else:
                box = boxes[0]
                height, width = frame.shape[:2]
                if min(box["width"] * width, box["height"] * height) < FACE_MIN_SIZE_PIXELS:
                    status = "Acércate un poco a la cámara"
                else:
                    face_image = crop_face(frame, box)
                    sharpness = blur_score(face_image)
                    status = f"Nitidez: {sharpness:.0f}"
                    if (
                        sharpness >= FACE_REGISTRATION_BLUR_THRESHOLD
                        and now - last_capture_at >= 0.65
                    ):
                        try:
                            embeddings.append(generate_face_embedding(face_image))
                            images.append(face_image)
                            pose_captures += 1
                            last_capture_at = now
                            status = "Captura válida"
                            if pose_captures >= FACE_REGISTRATION_CAPTURES_PER_POSE:
                                pose_index += 1
                                pose_captures = 0
                        except ValueError as error:
                            status = str(error)

                left = int(box["x"] * width)
                top = int(box["y"] * height)
                right = int((box["x"] + box["width"]) * width)
                bottom = int((box["y"] + box["height"]) * height)
                cv2.rectangle(frame, (left, top), (right, bottom), (60, 220, 60), 2)

            current_pose = POSES[min(pose_index, len(POSES) - 1)]
            cv2.putText(frame, current_pose, (20, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 255), 2)
            cv2.putText(
                frame,
                f"Pose {min(pose_index + 1, len(POSES))}/{len(POSES)} | "
                f"captura {pose_captures}/{FACE_REGISTRATION_CAPTURES_PER_POSE}",
                (20, 70),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.58,
                (255, 255, 255),
                2,
            )
            cv2.putText(frame, status, (20, 102), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 200, 80), 2)
            cv2.putText(frame, "Q: cancelar", (20, frame.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (220, 220, 220), 1)
            cv2.imshow("Room OS - Registro facial local", frame)
            if cv2.waitKey(1) & 0xFF in (ord("q"), ord("Q")):
                logger.info("Registro cancelado")
                return 0
    finally:
        detector.close()
        capture.release()
        cv2.destroyAllWindows()

    profile_path = database.save_profile(
        profile_name,
        display_name,
        embeddings,
        images,
    )
    logger.info("Perfil guardado localmente en %s", profile_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
