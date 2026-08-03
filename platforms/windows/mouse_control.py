"""Control mínimo y seguro del mouse mediante APIs nativas de Windows."""

import ctypes
import os


MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120

_KEY_CODES = {
    "ESC": 0x1B,
    "F8": 0x77,
    "F9": 0x78,
}


class WindowsMouseControlError(RuntimeError):
    """Indica que una operación nativa del mouse no pudo completarse."""


class WindowsMouseControl:
    """Expone únicamente operaciones fijas del mouse y teclas de seguridad."""

    @staticmethod
    def _ensure_windows() -> None:
        if os.name != "nt":
            raise WindowsMouseControlError("El mouse virtual requiere Windows")

    def get_screen_size(self) -> tuple[int, int]:
        self._ensure_windows()
        user32 = ctypes.windll.user32
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))

    def move_cursor(self, x: int, y: int) -> None:
        self._ensure_windows()
        if not ctypes.windll.user32.SetCursorPos(int(x), int(y)):
            raise WindowsMouseControlError("Windows rechazó el movimiento del cursor")

    def left_click(self) -> None:
        self.mouse_down()
        self.mouse_up()

    def right_click(self) -> None:
        self._mouse_event(MOUSEEVENTF_RIGHTDOWN)
        self._mouse_event(MOUSEEVENTF_RIGHTUP)

    def mouse_down(self) -> None:
        self._mouse_event(MOUSEEVENTF_LEFTDOWN)

    def mouse_up(self) -> None:
        self._mouse_event(MOUSEEVENTF_LEFTUP)

    def scroll(self, amount: int) -> None:
        self._mouse_event(MOUSEEVENTF_WHEEL, int(amount) * WHEEL_DELTA)

    def is_key_pressed(self, key_name: str) -> bool:
        self._ensure_windows()
        virtual_key = _KEY_CODES.get(str(key_name).upper())
        if virtual_key is None:
            raise WindowsMouseControlError(
                f"Tecla de seguridad no permitida: {key_name}"
            )
        return bool(ctypes.windll.user32.GetAsyncKeyState(virtual_key) & 0x8000)

    def _mouse_event(self, flags: int, data: int = 0) -> None:
        self._ensure_windows()
        ctypes.windll.user32.mouse_event(flags, 0, 0, data, 0)
