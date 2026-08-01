from __future__ import annotations

import json
import os
import socket
import socketserver
import stat
import threading
from pathlib import Path
from typing import Callable


_MAX_PORTABLE_UNIX_SOCKET_PATH_BYTES = 99


class _RunnerHealthServer(socketserver.UnixStreamServer):

    def __init__(self, path: str, callback: Callable[[], dict[str, object]]) -> None:
        self.health_callback = callback
        super().__init__(path, _RunnerHealthHandler)


class _RunnerHealthHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        self.connection.settimeout(1.0)
        request = self.rfile.readline(64)
        if request != b"health\n":
            return
        server = self.server
        assert isinstance(server, _RunnerHealthServer)
        payload = server.health_callback()
        self.wfile.write(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")


class RunnerHealthSocket:
    def __init__(self, path: str | Path, callback: Callable[[], dict[str, object]]) -> None:
        self.path = Path(path).expanduser().resolve(strict=False)
        self.callback = callback
        self._server: _RunnerHealthServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if len(os.fsencode(self.path)) > _MAX_PORTABLE_UNIX_SOCKET_PATH_BYTES:
            raise RuntimeError("runner health socket path exceeds the portable Unix limit")
        parent = self.path.parent
        if parent.is_symlink() or not parent.is_dir():
            raise RuntimeError("runner health socket directory is missing or unsafe")
        if self.path.exists() or self.path.is_symlink():
            metadata = self.path.lstat()
            if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.geteuid():
                raise RuntimeError("runner health socket path is occupied")
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.settimeout(0.5)
                    probe.connect(str(self.path))
            except OSError:
                self.path.unlink()
            else:
                raise RuntimeError("runner health socket is already active")
        self._server = _RunnerHealthServer(str(self.path), self.callback)
        self.path.chmod(0o660)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="factorforge-runner-health",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=3)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        self._server = None
        self._thread = None


def probe_runner_health(path: str | Path, *, timeout: float = 2.0) -> dict[str, object] | None:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(timeout)
            connection.connect(str(path))
            connection.sendall(b"health\n")
            response = b""
            while len(response) <= 16_384 and not response.endswith(b"\n"):
                chunk = connection.recv(4096)
                if not chunk:
                    break
                response += chunk
        payload = json.loads(response)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None
