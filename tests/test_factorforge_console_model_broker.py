from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest


class _UpstreamHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length)
        self.requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "payload": json.loads(body),
            }
        )
        response = b'{"id":"test","choices":[]}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, _format: str, *args: object) -> None:
        return None


def test_model_broker_injects_server_key_and_enforces_path_and_model(tmp_path: Path) -> None:
    from factor_factory.console.model_broker import (
        FactorForgeModelBrokerServer,
        ModelBrokerConfig,
    )

    _UpstreamHandler.requests = []
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamHandler)
    upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
    upstream_thread.start()
    key_file = tmp_path / "deepseek-api-key"
    key_file.write_text("server-side-deepseek-key-test", encoding="utf-8")
    key_file.chmod(0o600)
    broker = FactorForgeModelBrokerServer(
        ModelBrokerConfig(
            api_key_file=key_file,
            listen_host="127.0.0.1",
            listen_port=0,
            allowed_network="127.0.0.0/24",
            upstream_url=f"http://127.0.0.1:{upstream.server_port}",
        )
    )
    broker_thread = threading.Thread(target=broker.serve_forever, daemon=True)
    broker_thread.start()
    base_url = f"http://127.0.0.1:{broker.server_port}"
    try:
        health = json.loads(urlopen(f"{base_url}/healthz", timeout=3).read())
        assert health == {"ok": True, "service": "factorforge-model-broker"}

        request = Request(
            f"{base_url}/chat/completions",
            data=json.dumps(
                {"model": "deepseek-reasoner", "messages": [{"role": "user", "content": "test"}]}
            ).encode("utf-8"),
            headers={"Authorization": "Bearer container-placeholder", "Content-Type": "application/json"},
            method="POST",
        )
        assert urlopen(request, timeout=3).status == 200
        assert _UpstreamHandler.requests == [
            {
                "path": "/chat/completions",
                "authorization": "Bearer server-side-deepseek-key-test",
                "payload": {
                    "model": "deepseek-reasoner",
                    "messages": [{"role": "user", "content": "test"}],
                },
            }
        ]

        wrong_model = Request(
            f"{base_url}/chat/completions",
            data=b'{"model":"other"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as failure:
            urlopen(wrong_model, timeout=3)
        assert failure.value.code == 400
        with pytest.raises(HTTPError) as failure:
            urlopen(
                Request(
                    f"{base_url}/arbitrary",
                    data=b'{"model":"deepseek-reasoner"}',
                    method="POST",
                ),
                timeout=3,
            )
        assert failure.value.code == 404
        assert len(_UpstreamHandler.requests) == 1
    finally:
        broker.shutdown()
        broker.server_close()
        upstream.shutdown()
        upstream.server_close()
        broker_thread.join(timeout=3)
        upstream_thread.join(timeout=3)
