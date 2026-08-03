"""Protección contra instancias duplicadas con restauración de ventana."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from PySide6.QtNetwork import QLocalServer, QLocalSocket

from core.runtime_paths import application_data_dir


class SingleInstanceGuard:
    def __init__(self) -> None:
        identity = hashlib.sha256(
            str(application_data_dir()).encode("utf-8")
        ).hexdigest()[:16]
        self.server_name = f"room-os-{identity}"
        self._server = QLocalServer()
        self._handler: Callable[[], None] | None = None
        self._pending_activation = False
        self._owns_server = False
        self._server.newConnection.connect(self._handle_connection)

    def acquire(self) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(self.server_name)
        if socket.waitForConnected(400):
            socket.write(b"activate")
            socket.waitForBytesWritten(400)
            socket.disconnectFromServer()
            return False

        QLocalServer.removeServer(self.server_name)
        self._owns_server = self._server.listen(self.server_name)
        return self._owns_server

    def set_activation_handler(self, handler: Callable[[], None]) -> None:
        self._handler = handler
        if self._pending_activation:
            self._pending_activation = False
            handler()

    def _handle_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.waitForReadyRead(100)
            socket.readAll()
            socket.disconnectFromServer()
        if self._handler is None:
            self._pending_activation = True
        else:
            self._handler()

    def close(self) -> None:
        if self._owns_server:
            self._server.close()
            QLocalServer.removeServer(self.server_name)
            self._owns_server = False
