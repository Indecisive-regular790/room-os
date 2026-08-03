"""Configuración compartida de logging."""

import logging
from logging.handlers import RotatingFileHandler
import sys

from core.runtime_paths import application_data_dir


def configure_logging(level: int = logging.INFO) -> None:
    """Configura una salida uniforme de logs para toda la aplicación."""
    log_directory = application_data_dir() / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        RotatingFileHandler(
            log_directory / "room_os.log",
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
    ]
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )
