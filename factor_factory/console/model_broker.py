from __future__ import annotations

import http.client
import ipaddress
import json
import os
import re
import secrets
import ssl
import stat
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from factor_factory.console.bounded_http import BoundedThreadingHTTPServer
from factor_factory.console.secret_safety import contains_secret_values


ALLOWED_MODEL_PATHS = {"/chat/completions", "/v1/chat/completions"}
ACTIVE_SECRET_REGISTRY_NAME = "active.registry"
_SECRET_REGISTRY_BASENAME = re.compile(
    r"[a-z0-9][a-z0-9-]{7,62}\.(?:job_[a-f0-9]{10}|readiness)\.secrets"
)
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
    client_token_file: Path
    listen_host: str = "172.29.0.1"
    listen_port: int = 8781
    allowed_network: str = "172.29.0.0/24"
    upstream_url: str = "https://api.deepseek.com"
    allowed_model: str = "deepseek-reasoner"
    denied_secret_root: Path | None = None
    allow_gateway_source: bool = False
    max_request_bytes: int = 16 * 1024 * 1024
    upstream_timeout_seconds: int = 3_300

    def __post_init__(self) -> None:
        key_file = self.api_key_file.expanduser().absolute()
        object.__setattr__(self, "api_key_file", key_file)
        client_token_file = self.client_token_file.expanduser().absolute()
        object.__setattr__(self, "client_token_file", client_token_file)
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
        if (
            self.max_request_bytes < 1024
            or self.upstream_timeout_seconds < 60
            or self.upstream_timeout_seconds > 3_300
        ):
            raise ValueError("model broker limits are invalid")
        self._prepare_denied_secret_root()

    @property
    def source_network(self) -> ipaddress.IPv4Network:
        network = ipaddress.ip_network(self.allowed_network, strict=True)
        assert isinstance(network, ipaddress.IPv4Network)
        return network

    def read_api_key(self) -> str:
        return read_private_token_file(
            self.api_key_file,
            label="model broker API key",
            require_owner=True,
        )

    def read_client_token(self) -> str:
        return read_private_token_file(
            self.client_token_file,
            label="model broker client token",
            require_owner=False,
        )

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
        active_path = root / ACTIVE_SECRET_REGISTRY_NAME
        active_metadata = active_path.stat()
        if (
            active_path.is_symlink()
            or not stat.S_ISREG(active_metadata.st_mode)
            or active_metadata.st_mode & 0o007
            or active_metadata.st_size > 256
        ):
            raise RuntimeError("model broker active secret registry is unsafe")
        active_name = active_path.read_text(encoding="utf-8").strip()
        if _SECRET_REGISTRY_BASENAME.fullmatch(active_name) is None:
            raise RuntimeError("model broker active secret registry is invalid")
        candidate = root / active_name
        metadata = candidate.stat()
        if (
            candidate.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_mode & 0o007
            or metadata.st_size > 64 * 1024
        ):
            raise RuntimeError("model broker denied-secret entry is unsafe")
        values: set[bytes] = set()
        for value in candidate.read_bytes().splitlines():
            if len(value) >= 8:
                values.add(value)
        return tuple(sorted(values))


class FactorForgeModelBrokerServer(BoundedThreadingHTTPServer):
    max_request_threads = 8

    def __init__(self, config: ModelBrokerConfig) -> None:
        self.broker_config = config
        self.api_key = config.read_api_key()
        self.client_token = config.read_client_token()
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
        if not self._client_authenticated():
            self._send_json(403, {"ok": False, "error": "client_not_authenticated"})
            return
        try:
            self._active_denied_secrets()
        except (OSError, RuntimeError):
            self._send_json(503, {"ok": False, "error": "secret_scanner_unavailable"})
            return
        self._send_json(200, {"ok": True, "service": "factorforge-model-broker"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._source_allowed():
            self._send_json(403, {"error": "source_not_allowed"})
            return
        if not self._client_authenticated():
            self._send_json(403, {"error": "client_not_authenticated"})
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
            denied_secrets = self._active_denied_secrets()
        except (OSError, RuntimeError):
            self._send_json(503, {"error": "secret_scanner_unavailable"})
            return
        canonical_body = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if _contains_credential_material(body, denied_secrets) or _contains_credential_material(
            canonical_body,
            denied_secrets,
        ):
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
        network = self.config.source_network
        return bool(
            address in network
            and (self.config.allow_gateway_source or address != network.network_address + 1)
        )

    def _client_authenticated(self) -> bool:
        authorization = self.headers.get("Authorization", "")
        prefix = "Bearer "
        if not authorization.startswith(prefix):
            return False
        server = self.server
        assert isinstance(server, FactorForgeModelBrokerServer)
        return secrets.compare_digest(authorization[len(prefix) :], server.client_token)

    def _server_api_key(self) -> str:
        server = self.server
        assert isinstance(server, FactorForgeModelBrokerServer)
        return server.api_key

    def _active_denied_secrets(self) -> tuple[bytes, ...]:
        server = self.server
        assert isinstance(server, FactorForgeModelBrokerServer)
        values = self.config.read_denied_secrets()
        if not values or server.client_token.encode("utf-8") not in values:
            raise RuntimeError("active task secret registry is missing")
        return values

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
    return contains_secret_values(
        body,
        (value.decode("utf-8", errors="ignore") for value in denied_secrets),
    )


def read_private_token_file(
    path: Path,
    *,
    label: str,
    require_owner: bool,
) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} file is missing or unsafe")
    metadata = path.stat()
    if metadata.st_mode & 0o007 or (require_owner and metadata.st_mode & 0o077):
        raise RuntimeError(f"{label} file permissions are too broad")
    if require_owner and metadata.st_uid != os.geteuid():
        raise RuntimeError(f"{label} file owner is invalid")
    if not require_owner and metadata.st_uid not in {0, os.geteuid()}:
        raise RuntimeError(f"{label} file owner is invalid")
    current = path.parent
    while current != current.parent:
        if current.is_symlink():
            raise RuntimeError(f"{label} has a symlink ancestor")
        current = current.parent
    value = path.read_text(encoding="utf-8").strip()
    lowered = value.lower()
    if len(value) < 24 or any(token in lowered for token in ("replace", "example", "changeme")):
        raise RuntimeError(f"{label} is invalid")
    return value
