"""Operaciones restringidas sobre ventanas de Windows."""

import ctypes
import os
from typing import Any


VK_MENU = 0x12
VK_TAB = 0x09
VK_F4 = 0x73
VK_LWIN = 0x5B
VK_D = 0x44
KEYEVENTF_KEYUP = 0x0002
SW_RESTORE = 9


class WindowsWindowControlError(RuntimeError):
    """Indica que una operación de ventana no pudo completarse."""


class WindowsWindowControl:
    """Implementa combinaciones fijas y enfoque por PID."""

    @staticmethod
    def _ensure_windows() -> None:
        if os.name != "nt":
            raise WindowsWindowControlError("El control de ventanas requiere Windows")

    def send_hotkey(self, *virtual_keys: int) -> None:
        self._ensure_windows()
        allowed_hotkeys = {
            (VK_LWIN, VK_D),
            (VK_MENU, VK_F4),
            (VK_MENU, VK_TAB),
        }
        if tuple(virtual_keys) not in allowed_hotkeys:
            raise WindowsWindowControlError("Combinación de teclas no permitida")

        user32 = ctypes.windll.user32
        for virtual_key in virtual_keys:
            user32.keybd_event(virtual_key, 0, 0, 0)
        for virtual_key in reversed(virtual_keys):
            user32.keybd_event(virtual_key, 0, KEYEVENTF_KEYUP, 0)

    def show_desktop(self) -> dict[str, Any]:
        self.send_hotkey(VK_LWIN, VK_D)
        return {"message": "Escritorio mostrado o restaurado", "metadata": {}}

    def close_active_window(self) -> dict[str, Any]:
        self.send_hotkey(VK_MENU, VK_F4)
        return {"message": "Cierre enviado a la ventana activa", "metadata": {}}

    def switch_window(self) -> dict[str, Any]:
        self.send_hotkey(VK_MENU, VK_TAB)
        return {"message": "Cambio de ventana solicitado", "metadata": {}}

    def focus_process(self, process_id: int) -> bool:
        """Restaura y enfoca la primera ventana visible asociada al PID."""
        self._ensure_windows()
        user32 = ctypes.windll.user32
        target_handle = ctypes.c_void_p()
        callback_type = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)

        @callback_type(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def enum_callback(window_handle: int, _: int) -> bool:
            if not user32.IsWindowVisible(window_handle):
                return True
            window_process_id = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(
                window_handle,
                ctypes.byref(window_process_id),
            )
            if window_process_id.value == process_id:
                target_handle.value = window_handle
                return False
            return True

        user32.EnumWindows(enum_callback, 0)
        if not target_handle.value:
            return False

        user32.ShowWindow(target_handle.value, SW_RESTORE)
        return bool(user32.SetForegroundWindow(target_handle.value))
