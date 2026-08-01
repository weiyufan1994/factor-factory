from __future__ import annotations

import http.client
import base64
import ipaddress
import json
import os
import re
import ssl
import stat
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


ALLOWED_MODEL_PATHS = {"/chat/completions", "/v1/chat/completions"}
_AWS_ACCESS_KEY = re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_AWS_CREDENTIAL_ASSIGNMENT = re.compile(
    rb"(?i)AWS_(?:ACCESS_KEY_ID|SECRET_ACCESS_KEY|SESSION_TOKEN)\s*[:=]\s*[^\s\"']{8,}"
)
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


@dataclass(frozen=True)
class ModelBrokerConfig:
    api_key_file: Path
    listen_host: str = "172.29.0.1"
    listen_port: int = 8781
    allowed_network: str = "172.29.0.0/24"
    upstream_url: str = "https://api.deepseek.com"
    allowed_model: str = "deepseek-reasoner"
    denied_secret_root: Path | None = None
    max_request_bytes: int = 16 * 1024 * 1024
    upstream_timeout_seconds: int = 21_690

    def __post_init__(self) -> None:
        key_file = self.api_key_file.expanduser().absolute()
        object.__setattr__(self, "api_key_file", key_file)
        if self.denied_secret_root is not None:
            secret_root = self.denied_secret_root.expanduser().absolute()
            object.__setattr__(self, "denied_secret_root", secret_root)
        network = ipaddress.ip_network(self.allowed_network, strict=True)
        listen = ipaddress.ip_address(self.listen_host)
        upstream = urlsplit(self.upstream_url)
        if network.version != 4 or network.prefixlen < 24 or listen != network.network_address + 1:
            raise ValueError("model broker must bind the dedicated bridge gateway")
        if self.listen_port < 0 or self.listen_port > 65535:
            raise ValueError("model broker listen port is invalid")
        if upstream.scheme not in {"http", "https"} or not upstream.hostname or upstream.query:
            raise ValueError("model broker upstream URL is invalid")
        if upstream.path not in {"", "/"} or upstream.username or upstream.password:
            raise ValueError("model broker upstream must be an origin URL")
        if self.max_request_bytes < 1024 or self.upstream_timeout_seconds < 60:
            raise ValueError("model broker limits are invalid")
        self._prepare_denied_secret_root()

    @property
    def source_network(self) -> ipaddress.IPv4Network:
        network = ipaddress.ip_network(self.allowed_network, strict=True)
        assert isinstance(network, ipaddress.IPv4Network)
        return network

    def read_api_key(self) -> str:
        path = self.api_key_file
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("model broker API key file is missing or unsafe")
        metadata = path.stat()
        if metadata.st_mode & 0o077 or metadata.st_uid != os.geteuid():
            raise RuntimeError("model broker API key file permissions are too broad")
        current = path.parent
        while current != current.parent:
            if current.is_symlink():
                raise RuntimeError("model broker API key has a symlink ancestor")
            current = current.parent
        value = path.read_text(encoding="utf-8").strip()
        lowered = value.lower()
        if len(value) < 16 or any(token in lowered for token in ("replace", "example", "changeme")):
            raise RuntimeError("model broker API key is invalid")
        return value

    def _prepare_denied_secret_root(self) -> None:
        root = self.denied_secret_root
        if root is None:
            return
        if root.is_symlink():
            raise RuntimeError("model broker denied-secret root is unsafe")
        root.mkdir(mode=0o770, exist_ok=True)
        root.chmod(0o2770)
        metadata = root.stat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_mode & 0o007:
            raise RuntimeError("model broker denied-secret root permissions are unsafe")

    def read_denied_secrets(self) -> tuple[bytes, ...]:
        root = self.denied_secret_root
        if root is None:
            return ()
        if root.is_symlink() or not root.is_dir() or root.stat().st_mode & 0o007:
            raise RuntimeError("model broker denied-secret root is unsafe")
        values: set[bytes] = set()
        for candidate in root.iterdir():
            if candidate.is_symlink() or candidate.suffix != ".secrets":
                raise RuntimeError("model broker denied-secret entry is unsafe")
            metadata = candidate.stat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_mode & 0o007
                or metadata.st_size > 64 * 1024
            ):
                raise RuntimeError("model broker denied-secret entry is unsafe")
            for value in candidate.read_bytes().splitlines():
                if len(value) >= 8:
                    values.add(value)
        return tuple(sorted(values))


class FactorForgeModelBrokerServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, config: ModelBrokerConfig) -> None:
        self.broker_config = config
        self.api_key = config.read_api_key()
        super().__init__((config.listen_host, config.listen_port), FactorForgeModelBrokerHandler)


class FactorForgeModelBrokerHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "FactorForgeModelBroker/1"

    @property
    def config(self) -> ModelBrokerConfig:
        server = self.server
        assert isinstance(server, FactorForgeModelBrokerServer)
        return server.broker_config

    def log_message(self, _format: str, *args: Any) -> None:
        return None

    def do_GET(self) -> None:  # noqa: N802
        if not self._source_allowed() or self.path != "/healthz":
            self._send_json(404, {"ok": False})
            return
        try:
            self.config.read_denied_secrets()
        except (OSError, RuntimeError):
            self._send_json(503, {"ok": False, "error": "secret_scanner_unavailable"})
            return
        self._send_json(200, {"ok": True, "service": "factorforge-model-broker"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._source_allowed():
            self._send_json(403, {"error": "source_not_allowed"})
            return
        if self.path not in ALLOWED_MODEL_PATHS:
            self._send_json(404, {"error": "path_not_allowed"})
            return
        if self.headers.get("Transfer-Encoding"):
            self._send_json(400, {"error": "streaming_request_not_allowed"})
            return
        try:
            length = int(self.headers.get("Content-Length") or "")
        except ValueError:
            length = -1
        if length <= 0 or length > self.config.max_request_bytes:
            self._send_json(413, {"error": "request_size_invalid"})
            return
        body = self.rfile.read(length)
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "request_json_invalid"})
            return
        if not isinstance(payload, dict) or payload.get("model") != self.config.allowed_model:
            self._send_json(400, {"error": "model_not_allowed"})
            return
        try:
            denied_secrets = self.config.read_denied_secrets()
        except (OSError, RuntimeError):
            self._send_json(503, {"error": "secret_scanner_unavailable"})
            return
        if _contains_credential_material(body, denied_secrets):
            self._send_json(400, {"error": "credential_material_forbidden"})
            return
        self._relay(body)

    def _relay(self, body: bytes) -> None:
        upstream = urlsplit(self.config.upstream_url)
        connection_class = (
            http.client.HTTPSConnection if upstream.scheme == "https" else http.client.HTTPConnection
        )
        kwargs: dict[str, Any] = {"timeout": self.config.upstream_timeout_seconds}
        if upstream.scheme == "https":
            kwargs["context"] = ssl.create_default_context()
        connection = connection_class(upstream.hostname, upstream.port, **kwargs)
        upstream_path = self.path
        headers = {
            "Authorization": f"Bearer {self._server_api_key()}",
            "Content-Type": "application/json",
            "Accept": self.headers.get("Accept", "application/json"),
            "Content-Length": str(len(body)),
            "User-Agent": "factorforge-console-model-broker/1",
        }
        response_started = False
        try:
            connection.request("POST", upstream_path, body=body, headers=headers)
            response = connection.getresponse()
            self.send_response(response.status)
            for key, value in response.getheaders():
                lowered = key.lower()
                if lowered not in HOP_BY_HOP_HEADERS and lowered not in {"server", "date"}:
                    self.send_header(key, value)
            self.send_header("Connection", "close")
            self.end_headers()
            response_started = True
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        except (OSError, http.client.HTTPException, ssl.SSLError):
            if not response_started and not self.wfile.closed:
                self._send_json(502, {"error": "upstream_unavailable"})
        finally:
            self.close_connection = True
            connection.close()

    def _source_allowed(self) -> bool:
        try:
            address = ipaddress.ip_address(self.client_address[0])
        except ValueError:
            return False
        return address in self.config.source_network

    def _server_api_key(self) -> str:
        server = self.server
        assert isinstance(server, FactorForgeModelBrokerServer)
        return server.api_key

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True


def serve_model_broker(config: ModelBrokerConfig) -> None:
    server = FactorForgeModelBrokerServer(config)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()


def _contains_credential_material(body: bytes, denied_secrets: tuple[bytes, ...]) -> bool:
    if _AWS_ACCESS_KEY.search(body) or _AWS_CREDENTIAL_ASSIGNMENT.search(body):
        return True
    for value in denied_secrets:
        if value in body or base64.b64encode(value) in body or base64.urlsafe_b64encode(value) in body:
            return True
    return False
