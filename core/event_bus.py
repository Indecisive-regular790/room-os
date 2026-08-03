"""Bus de eventos síncrono y seguro para varios hilos."""

import logging
from collections import defaultdict
from collections.abc import Callable
from threading import RLock
from typing import Any


logger = logging.getLogger(__name__)
EventCallback = Callable[[Any], None]


class EventBus:
    """Permite suscribir, cancelar y publicar eventos por nombre."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventCallback]] = defaultdict(list)
        self._lock = RLock()

    def subscribe(self, event_name: str, callback: EventCallback) -> None:
        """Suscribe un callback a un evento."""
        with self._lock:
            if callback not in self._subscribers[event_name]:
                self._subscribers[event_name].append(callback)

    def unsubscribe(self, event_name: str, callback: EventCallback) -> None:
        """Elimina un callback previamente suscrito."""
        with self._lock:
            callbacks = self._subscribers.get(event_name)
            if not callbacks:
                return

            try:
                callbacks.remove(callback)
            except ValueError:
                return

            if not callbacks:
                del self._subscribers[event_name]

    def publish(self, event_name: str, data: Any = None) -> None:
        """Ejecuta los callbacks suscritos usando una copia estable de la lista."""
        with self._lock:
            callbacks = tuple(self._subscribers.get(event_name, ()))

        for callback in callbacks:
            try:
                callback(data)
            except Exception:
                logger.exception(
                    "Error en un suscriptor del evento '%s'",
                    event_name,
                )
