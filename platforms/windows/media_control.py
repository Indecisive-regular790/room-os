"""Control de teclas multimedia nativas de Windows."""

import asyncio
import ctypes
import os
from typing import Any


VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
KEYEVENTF_KEYUP = 0x0002


class WindowsMediaControlError(RuntimeError):
    """Indica que Windows no pudo procesar una tecla multimedia."""


class WindowsMediaControl:
    """Envía únicamente códigos multimedia predefinidos."""

    def __init__(self, volume_step: int = 5) -> None:
        self.volume_step = max(1, min(int(volume_step), 100))

    @staticmethod
    def _ensure_windows() -> None:
        if os.name != "nt":
            raise WindowsMediaControlError("El control multimedia requiere Windows")

    def send_key(self, virtual_key: int, presses: int = 1) -> None:
        """Envía un código virtual interno; nunca acepta comandos o texto libre."""
        self._ensure_windows()
        allowed_keys = {
            VK_MEDIA_NEXT_TRACK,
            VK_MEDIA_PREV_TRACK,
            VK_MEDIA_STOP,
            VK_MEDIA_PLAY_PAUSE,
            VK_VOLUME_MUTE,
            VK_VOLUME_DOWN,
            VK_VOLUME_UP,
        }
        if virtual_key not in allowed_keys:
            raise WindowsMediaControlError("Código multimedia no permitido")

        user32 = ctypes.windll.user32
        for _ in range(max(1, int(presses))):
            user32.keybd_event(virtual_key, 0, 0, 0)
            user32.keybd_event(virtual_key, 0, KEYEVENTF_KEYUP, 0)

    def play_pause(self) -> dict[str, Any]:
        self.send_key(VK_MEDIA_PLAY_PAUSE)
        return self._result("Alternancia reproducción/pausa enviada")

    def play(self) -> dict[str, Any]:
        """Solicita reproducción explícita a la sesión multimedia de Windows."""
        return self._set_playback_state(playing=True)

    def pause(self) -> dict[str, Any]:
        """Solicita pausa explícita a la sesión multimedia de Windows."""
        return self._set_playback_state(playing=False)

    def _set_playback_state(self, playing: bool) -> dict[str, Any]:
        self._ensure_windows()
        try:
            succeeded, source_app = asyncio.run(
                self._set_playback_state_async(playing)
            )
        except ImportError as error:
            raise WindowsMediaControlError(
                "Faltan las dependencias WinRT para controlar reproducción y pausa"
            ) from error

        operation = "reproducción" if playing else "pausa"
        if not succeeded:
            raise WindowsMediaControlError(
                f"La sesión multimedia rechazó la solicitud de {operation}"
            )
        return {
            "message": f"Solicitud de {operation} enviada",
            "metadata": {
                "source_app": source_app,
                "playback_state": "playing" if playing else "paused",
            },
        }

    @staticmethod
    async def _set_playback_state_async(playing: bool) -> tuple[bool, str]:
        from winrt.windows.media.control import (
            GlobalSystemMediaTransportControlsSessionManager,
        )

        manager = (
            await GlobalSystemMediaTransportControlsSessionManager.request_async()
        )
        sessions = list(manager.get_sessions())
        if not sessions:
            raise WindowsMediaControlError(
                "No hay una sesión multimedia activa; inicia una canción primero"
            )

        apple_music = next(
            (
                session
                for session in sessions
                if "applemusic" in session.source_app_user_model_id.casefold()
            ),
            None,
        )
        session = apple_music or manager.get_current_session() or sessions[0]
        succeeded = (
            await session.try_play_async()
            if playing
            else await session.try_pause_async()
        )
        return bool(succeeded), str(session.source_app_user_model_id)

    def next_track(self) -> dict[str, Any]:
        self.send_key(VK_MEDIA_NEXT_TRACK)
        return self._result("Siguiente pista solicitada")

    def previous_track(self) -> dict[str, Any]:
        self.send_key(VK_MEDIA_PREV_TRACK)
        return self._result("Pista anterior solicitada")

    def stop(self) -> dict[str, Any]:
        self.send_key(VK_MEDIA_STOP)
        return self._result("Detención multimedia solicitada")

    def toggle_mute(self) -> dict[str, Any]:
        self.send_key(VK_VOLUME_MUTE)
        return self._result("Silencio multimedia alternado")

    def volume_up(self) -> dict[str, Any]:
        presses = self._volume_presses()
        self.send_key(VK_VOLUME_UP, presses)
        return self._result("Volumen incrementado", presses=presses)

    def volume_down(self) -> dict[str, Any]:
        presses = self._volume_presses()
        self.send_key(VK_VOLUME_DOWN, presses)
        return self._result("Volumen reducido", presses=presses)

    def _volume_presses(self) -> int:
        return max(1, (self.volume_step + 1) // 2)

    def _result(self, message: str, presses: int = 1) -> dict[str, Any]:
        return {
            "message": message,
            "metadata": {
                "volume_step": self.volume_step,
                "key_presses": presses,
            },
        }
