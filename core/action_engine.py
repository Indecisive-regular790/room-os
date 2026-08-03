"""Motor centralizado para ejecutar acciones desacopladas."""

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from core.action_registry import ActionNotFoundError, ActionRegistry
from core.actions.base_action import ActionValidationError
from core.event_bus import EventBus


logger = logging.getLogger(__name__)

ACTION_EXECUTE_EVENT = "action.execute"
ACTION_RESULT_EVENT = "action.result"


@dataclass(frozen=True)
class ActionExecutionResult:
    """Resultado inmutable de un intento de ejecución."""

    action_id: str
    success: bool
    message: str
    started_at: str
    finished_at: str
    duration_ms: float
    error_type: Optional[str]
    error_message: Optional[str]
    metadata: dict[str, Any]
    action_name: Optional[str] = None
    status: str = "success"
    result: Any = None

    @property
    def error(self) -> Optional[str]:
        """Alias compatible con consumidores anteriores."""
        return self.error_message

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "success": self.success,
            "message": self.message,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "metadata": dict(self.metadata),
            "action_name": self.action_name,
            "status": self.status,
            "result": self.result,
        }


class ActionEngine:
    """Escucha solicitudes, ejecuta acciones y conserva sus resultados."""

    def __init__(self, event_bus: EventBus, registry: ActionRegistry) -> None:
        self._event_bus = event_bus
        self._registry = registry
        self._history: list[ActionExecutionResult] = []
        self._history_lock = threading.RLock()
        self._started = False

    def start(self) -> None:
        """Comienza a escuchar solicitudes action.execute."""
        if self._started:
            return
        self._event_bus.subscribe(ACTION_EXECUTE_EVENT, self._on_execute_event)
        self._started = True
        logger.info("Action Engine iniciado con %d acciones", len(self._registry))

    def execute(
        self,
        action_id: str,
        context: Optional[dict[str, Any]] = None,
    ) -> ActionExecutionResult:
        """Ejecuta una acción por ID sin propagar errores al resto del sistema."""
        started_at = datetime.now(timezone.utc)
        started_clock = time.perf_counter()

        try:
            action = self._registry.get_by_id(action_id)
        except ActionNotFoundError as error:
            logger.warning(
                "Acción inexistente: id=%s time=%s result=not_found error=%s",
                action_id,
                started_at.isoformat(),
                error,
            )
            return self._finish(
                action_id=action_id,
                action_name=None,
                success=False,
                status="not_found",
                started_at=started_at,
                started_clock=started_clock,
                message="Acción no registrada",
                error_type=type(error).__name__,
                error_message=str(error),
            )

        if not action.enabled:
            logger.warning(
                "Acción deshabilitada: id=%s time=%s result=disabled",
                action.id,
                started_at.isoformat(),
            )
            return self._finish(
                action_id=action.id,
                action_name=action.name,
                success=False,
                status="disabled",
                started_at=started_at,
                started_clock=started_clock,
                message="Acción deshabilitada",
                error_type="ActionDisabledError",
                error_message="La acción está deshabilitada",
                metadata={"dangerous": action.dangerous},
            )

        action_context = dict(context or {})
        logger.info(
            "Executing action: %s | name=%s time=%s",
            action.id,
            action.name,
            started_at.isoformat(),
        )

        try:
            if not action.validate(action_context):
                return self._finish(
                    action_id=action.id,
                    action_name=action.name,
                    success=False,
                    status="validation_failed",
                    started_at=started_at,
                    started_clock=started_clock,
                    message="Acción rechazada por validación",
                    error_type="ActionValidationError",
                    error_message="La validación de la acción devolvió False",
                    metadata={"dangerous": action.dangerous},
                )

            output = action.execute(action_context)
            output_message = "Acción ejecutada correctamente"
            output_metadata: dict[str, Any] = {"dangerous": action.dangerous}
            if isinstance(output, dict):
                output_message = str(output.get("message", output_message))
                supplied_metadata = output.get("metadata", {})
                if isinstance(supplied_metadata, dict):
                    output_metadata.update(supplied_metadata)
            return self._finish(
                action_id=action.id,
                action_name=action.name,
                success=True,
                status="success",
                started_at=started_at,
                started_clock=started_clock,
                message=output_message,
                result=output,
                metadata=output_metadata,
            )
        except ActionValidationError as error:
            logger.warning(
                "Acción rechazada: id=%s time=%s error=%s",
                action.id,
                started_at.isoformat(),
                error,
            )
            return self._finish(
                action_id=action.id,
                action_name=action.name,
                success=False,
                status="validation_failed",
                started_at=started_at,
                started_clock=started_clock,
                message="Acción rechazada por validación",
                error_type=type(error).__name__,
                error_message=str(error),
                metadata={"dangerous": action.dangerous},
            )
        except Exception as error:
            logger.exception(
                "Error ejecutando acción: id=%s time=%s",
                action.id,
                started_at.isoformat(),
            )
            return self._finish(
                action_id=action.id,
                action_name=action.name,
                success=False,
                status="error",
                started_at=started_at,
                started_clock=started_clock,
                message="Error del sistema operativo al ejecutar la acción",
                error_type=type(error).__name__,
                error_message=str(error),
                metadata={"dangerous": action.dangerous},
            )

    def _finish(
        self,
        action_id: str,
        action_name: Optional[str],
        success: bool,
        status: str,
        started_at: datetime,
        started_clock: float,
        message: str,
        result: Any = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> ActionExecutionResult:
        finished_at = datetime.now(timezone.utc)
        duration_ms = (time.perf_counter() - started_clock) * 1000.0
        execution_result = ActionExecutionResult(
            action_id=action_id,
            success=success,
            message=message,
            started_at=started_at.isoformat(),
            finished_at=finished_at.isoformat(),
            duration_ms=duration_ms,
            error_type=error_type,
            error_message=error_message,
            metadata=dict(metadata or {}),
            action_name=action_name,
            status=status,
            result=result,
        )

        with self._history_lock:
            self._history.append(execution_result)

        log_method = logger.info if success else logger.warning
        log_method(
            "Action result: id=%s time=%s duration_ms=%.3f result=%s error=%s",
            action_id,
            finished_at.isoformat(),
            duration_ms,
            status,
            error_message or "none",
        )
        self._event_bus.publish(ACTION_RESULT_EVENT, execution_result.to_dict())
        return execution_result

    def _on_execute_event(self, event_data: Any) -> None:
        """Adapta eventos action.execute al método execute."""
        if isinstance(event_data, str):
            self.execute(event_data)
            return

        if not isinstance(event_data, dict):
            logger.error("Evento action.execute inválido: %r", event_data)
            return

        action_id = event_data.get("action_id")
        if not isinstance(action_id, str) or not action_id:
            logger.error("Evento action.execute sin action_id válido: %r", event_data)
            return

        context = event_data.get("context")
        if context is not None and not isinstance(context, dict):
            logger.error("Contexto inválido para la acción '%s'", action_id)
            return

        self.execute(action_id, context)

    def get_history(self) -> tuple[ActionExecutionResult, ...]:
        """Devuelve una copia inmutable del historial de ejecución."""
        with self._history_lock:
            return tuple(self._history)

    def close(self) -> None:
        """Deja de escuchar eventos sin alterar el registro."""
        if self._started:
            self._event_bus.unsubscribe(ACTION_EXECUTE_EVENT, self._on_execute_event)
        self._started = False
        logger.info("Action Engine cerrado")
