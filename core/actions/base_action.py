"""Contrato común para todas las acciones de Room OS."""

from abc import ABC, abstractmethod
from typing import Any, Optional


class ActionValidationError(RuntimeError):
    """Indica que una acción fue rechazada antes de ejecutarse."""


class BaseAction(ABC):
    """Define los metadatos y el ciclo de vida de una acción."""

    def __init__(
        self,
        action_id: str,
        name: str,
        description: str,
        enabled: bool = True,
        dangerous: bool = False,
    ) -> None:
        if not action_id.strip():
            raise ValueError("El ID de la acción no puede estar vacío")
        if not name.strip():
            raise ValueError("El nombre de la acción no puede estar vacío")

        self.id = action_id
        self.name = name
        self.description = description
        self.enabled = enabled
        self.dangerous = dangerous

    def validate(self, context: Optional[dict[str, Any]] = None) -> bool:
        """Valida si la acción puede ejecutarse con el contexto recibido."""
        return True

    @abstractmethod
    def execute(self, context: Optional[dict[str, Any]] = None) -> Any:
        """Ejecuta la acción y devuelve un resultado serializable cuando sea posible."""

    def rollback(
        self,
        context: Optional[dict[str, Any]] = None,
        result: Any = None,
    ) -> None:
        """Punto de extensión para revertir acciones en versiones futuras."""
        return None
