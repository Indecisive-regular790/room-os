"""Funciones de sistema Windows con comandos internos fijos."""

import ctypes
import os
import subprocess
from typing import Any

from platforms.windows.media_control import WindowsMediaControl
from platforms.windows.window_control import WindowsWindowControl


class WindowsSystemControlError(RuntimeError):
    """Indica que una operación del sistema operativo falló."""


class WindowsSystemControl:
    """Encapsula operaciones nativas de Windows sin aceptar comandos libres."""

    def __init__(
        self,
        volume_step: int = 5,
        media_control: WindowsMediaControl | None = None,
        window_control: WindowsWindowControl | None = None,
    ) -> None:
        self._media_control = media_control or WindowsMediaControl(volume_step)
        self._window_control = window_control or WindowsWindowControl()

    @staticmethod
    def _ensure_windows() -> None:
        if os.name != "nt":
            raise WindowsSystemControlError("El control del sistema requiere Windows")

    def lock(self) -> dict[str, Any]:
        self._ensure_windows()
        if not ctypes.windll.user32.LockWorkStation():
            raise WindowsSystemControlError("Windows rechazó el bloqueo de sesión")
        return {"message": "Windows bloqueado", "metadata": {"dangerous": False}}

    def sleep(self) -> dict[str, Any]:
        self._ensure_windows()
        if not ctypes.windll.powrprof.SetSuspendState(False, False, False):
            raise WindowsSystemControlError("Windows rechazó la suspensión")
        return {"message": "Suspensión solicitada", "metadata": {"dangerous": True}}

    def schedule_shutdown(self, delay_seconds: int) -> dict[str, Any]:
        delay = max(0, int(delay_seconds))
        self._run_shutdown_command(["/s", "/t", str(delay)])
        return {
            "message": f"Apagado programado en {delay} segundos",
            "metadata": {"delay_seconds": delay, "dangerous": True},
        }

    def schedule_restart(self, delay_seconds: int) -> dict[str, Any]:
        delay = max(0, int(delay_seconds))
        self._run_shutdown_command(["/r", "/t", str(delay)])
        return {
            "message": f"Reinicio programado en {delay} segundos",
            "metadata": {"delay_seconds": delay, "dangerous": True},
        }

    def cancel_pending_power_action(self) -> dict[str, Any]:
        self._run_shutdown_command(["/a"])
        return {
            "message": "Apagado o reinicio pendiente cancelado",
            "metadata": {"dangerous": False},
        }

    def toggle_mute(self) -> dict[str, Any]:
        return self._media_control.toggle_mute()

    def volume_up(self) -> dict[str, Any]:
        return self._media_control.volume_up()

    def volume_down(self) -> dict[str, Any]:
        return self._media_control.volume_down()

    def show_desktop(self) -> dict[str, Any]:
        return self._window_control.show_desktop()

    def open_task_manager(self) -> dict[str, Any]:
        self._ensure_windows()
        subprocess.Popen(
            ["taskmgr.exe"],
            close_fds=True,
        )
        return {"message": "Administrador de tareas abierto", "metadata": {}}

    def _run_shutdown_command(self, fixed_arguments: list[str]) -> None:
        self._ensure_windows()
        completed = subprocess.run(
            ["shutdown.exe", *fixed_arguments],
            check=False,
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if completed.returncode != 0:
            error = (completed.stderr or completed.stdout or "Error desconocido").strip()
            raise WindowsSystemControlError(error)
