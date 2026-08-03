"""Validacion comun para datos que cruzan limites del sistema."""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Any


class InputValidationError(ValueError):
    """Una entrada externa no cumple el formato esperado."""


_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")


def normalize_text(
    value: Any,
    *,
    field_name: str,
    max_length: int,
    allow_empty: bool = False,
) -> str:
    """Normaliza texto y rechaza controles invisibles o tamanos abusivos."""
    if not isinstance(value, str):
        raise InputValidationError(f"{field_name} debe ser texto")
    text = unicodedata.normalize("NFKC", value).strip()
    if not text and not allow_empty:
        raise InputValidationError(f"{field_name} no puede estar vacio")
    if len(text) > max(1, int(max_length)):
        raise InputValidationError(
            f"{field_name} excede el limite de {int(max_length)} caracteres"
        )
    invalid_control = any(
        unicodedata.category(character) == "Cc"
        and character not in {"\n", "\t"}
        for character in text
    )
    if invalid_control:
        raise InputValidationError(f"{field_name} contiene caracteres no permitidos")
    return text


def validate_identifier(
    value: Any,
    *,
    field_name: str,
    max_length: int = 64,
) -> str:
    """Acepta identificadores opacos seguros para eventos y logs."""
    if not isinstance(value, str):
        raise InputValidationError(f"{field_name} debe ser texto")
    identifier = value.strip()
    if not identifier or len(identifier) > max(1, int(max_length)):
        raise InputValidationError(f"{field_name} no tiene una longitud valida")
    if not _SAFE_IDENTIFIER.fullmatch(identifier):
        raise InputValidationError(
            f"{field_name} solo admite letras, numeros, guion y guion bajo"
        )
    return identifier


def escape_rich_text(value: Any) -> str:
    """Convierte texto no confiable en HTML inerte para widgets enriquecidos."""
    return html.escape(str(value), quote=True).replace("\n", "<br>")
