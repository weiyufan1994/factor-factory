from __future__ import annotations

import socket
import threading
from http.server import ThreadingHTTPServer
from typing import Any


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    max_request_threads = 32
    request_socket_timeout = 15.0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._request_capacity = threading.BoundedSemaphore(self.max_request_threads)
        super().__init__(*args, **kwargs)

    def process_request(self, request: socket.socket, client_address: Any) -> None:
        if not self._request_capacity.acquire(timeout=0.1):
            try:
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\n"
                    b"Content-Length: 0\r\nConnection: close\r\n\r\n"
                )
            except OSError:
                pass
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request: socket.socket, client_address: Any) -> None:
        try:
            request.settimeout(self.request_socket_timeout)
            super().process_request_thread(request, client_address)
        finally:
            self._request_capacity.release()
