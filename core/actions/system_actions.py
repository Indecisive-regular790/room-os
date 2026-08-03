"""Acciones reales de sistema delegadas a la capa Windows."""

from typing import Any, Optional

from config import (
    ALLOW_RESTART,
    ALLOW_SHUTDOWN,
    ALLOW_SLEEP,
    SHUTDOWN_DELAY_SECONDS,
    VOLUME_STEP,
)
from core.actions.base_action import ActionValidationError, BaseAction
from platforms.windows.system_control import WindowsSystemControl


def _system_controller() -> WindowsSystemControl:
    return WindowsSystemControl(volume_step=VOLUME_STEP)


class LockSystemAction(BaseAction):
    def __init__(self, controller: WindowsSystemControl | None = None) -> None:
        super().__init__("system.lock", "Lock system", "Bloquea Windows inmediatamente.")
        self._controller = controller or _system_controller()

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.lock()


class SleepSystemAction(BaseAction):
    def __init__(
        self,
        controller: WindowsSystemControl | None = None,
        allow_sleep: bool = ALLOW_SLEEP,
    ) -> None:
        super().__init__(
            "system.sleep",
            "Sleep system",
            "Suspende Windows.",
            dangerous=True,
        )
        self._controller = controller or _system_controller()
        self._allow_sleep = allow_sleep

    def validate(self, context: Optional[dict[str, Any]] = None) -> bool:
        if not self._allow_sleep:
            raise ActionValidationError("La suspensión está bloqueada por ALLOW_SLEEP")
        return True

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.sleep()


class ShutdownSystemAction(BaseAction):
    def __init__(
        self,
        controller: WindowsSystemControl | None = None,
        allow_shutdown: bool = ALLOW_SHUTDOWN,
        delay_seconds: int = SHUTDOWN_DELAY_SECONDS,
    ) -> None:
        super().__init__(
            "system.shutdown",
            "Shutdown system",
            "Programa el apagado de Windows.",
            dangerous=True,
        )
        self._controller = controller or _system_controller()
        self._allow_shutdown = allow_shutdown
        self._delay_seconds = max(0, int(delay_seconds))

    def validate(self, context: Optional[dict[str, Any]] = None) -> bool:
        if not self._allow_shutdown:
            raise ActionValidationError("El apagado está bloqueado por ALLOW_SHUTDOWN")
        if not context or context.get("confirmed") is not True:
            raise ActionValidationError(
                "system.shutdown requiere context={'confirmed': True}"
            )
        return True

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.schedule_shutdown(self._delay_seconds)


class RestartSystemAction(BaseAction):
    def __init__(
        self,
        controller: WindowsSystemControl | None = None,
        allow_restart: bool = ALLOW_RESTART,
        delay_seconds: int = SHUTDOWN_DELAY_SECONDS,
    ) -> None:
        super().__init__(
            "system.restart",
            "Restart system",
            "Programa el reinicio de Windows.",
            dangerous=True,
        )
        self._controller = controller or _system_controller()
        self._allow_restart = allow_restart
        self._delay_seconds = max(0, int(delay_seconds))

    def validate(self, context: Optional[dict[str, Any]] = None) -> bool:
        if not self._allow_restart:
            raise ActionValidationError("El reinicio está bloqueado por ALLOW_RESTART")
        if not context or context.get("confirmed") is not True:
            raise ActionValidationError(
                "system.restart requiere context={'confirmed': True}"
            )
        return True

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.schedule_restart(self._delay_seconds)


class CancelPowerAction(BaseAction):
    def __init__(self, controller: WindowsSystemControl | None = None) -> None:
        super().__init__(
            "system.cancel_power",
            "Cancel pending power action",
            "Cancela un apagado o reinicio pendiente.",
        )
        self._controller = controller or _system_controller()

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.cancel_pending_power_action()


class ToggleSystemMuteAction(BaseAction):
    def __init__(self, controller: WindowsSystemControl | None = None) -> None:
        super().__init__("system.toggle_mute", "Toggle system mute", "Alterna silencio.")
        self._controller = controller or _system_controller()

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.toggle_mute()


class SystemVolumeUpAction(BaseAction):
    def __init__(self, controller: WindowsSystemControl | None = None) -> None:
        super().__init__("system.volume_up", "System volume up", "Sube el volumen.")
        self._controller = controller or _system_controller()

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.volume_up()


class SystemVolumeDownAction(BaseAction):
    def __init__(self, controller: WindowsSystemControl | None = None) -> None:
        super().__init__("system.volume_down", "System volume down", "Baja el volumen.")
        self._controller = controller or _system_controller()

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.volume_down()


class ShowDesktopAction(BaseAction):
    def __init__(self, controller: WindowsSystemControl | None = None) -> None:
        super().__init__(
            "system.show_desktop",
            "Show desktop",
            "Minimiza o restaura todas las ventanas.",
        )
        self._controller = controller or _system_controller()

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.show_desktop()


class OpenTaskManagerAction(BaseAction):
    def __init__(self, controller: WindowsSystemControl | None = None) -> None:
        super().__init__(
            "system.open_task_manager",
            "Open Task Manager",
            "Abre el Administrador de tareas.",
        )
        self._controller = controller or _system_controller()

    def execute(self, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._controller.open_task_manager()
