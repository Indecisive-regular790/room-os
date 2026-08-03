"""Eliminación confirmada de un perfil facial local."""

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import FACE_DATABASE_PATH  # noqa: E402
from services.face_database import FaceDatabase, FaceDatabaseError  # noqa: E402


def main() -> int:
    database = FaceDatabase(FACE_DATABASE_PATH)
    profiles = database.list_profiles()
    if not profiles:
        print("No hay perfiles faciales registrados.")
        return 0
    print("Perfiles:", ", ".join(profiles))
    profile_name = input("Escribe el nombre exacto del perfil: ").strip()
    confirmation = input(f"Para borrar '{profile_name}', escribe BORRAR: ").strip()
    if confirmation != "BORRAR":
        print("Operación cancelada.")
        return 0
    try:
        database.delete_profile(profile_name)
    except FaceDatabaseError as error:
        print(f"Error: {error}")
        return 1
    print(f"Perfil '{profile_name}' eliminado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
