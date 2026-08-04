from __future__ import annotations

import base64
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


def test_model_broker_timeout_cannot_exceed_agent_lease_budget(tmp_path: Path) -> None:
    from factor_factory.console.model_broker import ModelBrokerConfig

    with pytest.raises(ValueError, match="limits"):
        ModelBrokerConfig(
            api_key_file=tmp_path / "unused-key",
            client_token_file=tmp_path / "unused-client-token",
            upstream_timeout_seconds=3_301,
        )


def test_model_broker_does_not_rechmod_a_preprovisioned_secret_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from factor_factory.console.model_broker import ModelBrokerConfig

    denied_root = tmp_path / "denied-secrets"
    denied_root.mkdir(mode=0o770)
    denied_root.chmod(0o2770)
    original_chmod = Path.chmod

    def guarded_chmod(path: Path, mode: int, *args, **kwargs) -> None:
        if path == denied_root:
            raise AssertionError("preprovisioned secret root must not be re-chmodded")
        original_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "chmod", guarded_chmod)
    ModelBrokerConfig(
        api_key_file=tmp_path / "unused-key",
        client_token_file=tmp_path / "unused-client-token",
        denied_secret_root=denied_root,
    )


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
    client_token = "broker-client-token-for-console-test"
    client_token_file = tmp_path / "broker-client-token"
    client_token_file.write_text(client_token, encoding="utf-8")
    client_token_file.chmod(0o600)
    denied_root = tmp_path / "denied-secrets"
    denied_root.mkdir(mode=0o770)
    denied_file = denied_root / "pilot-console.job_0123456789.secrets"
    denied_file.write_text(
        f"{client_token}\n"
        "temporary-secret-for-broker-test\n"
        "temporary-session-token-for-broker-test\n",
        encoding="utf-8",
    )
    denied_file.chmod(0o640)
    active_file = denied_root / "active.registry"
    active_file.write_text(f"{denied_file.name}\n", encoding="utf-8")
    active_file.chmod(0o640)
    broker = FactorForgeModelBrokerServer(
        ModelBrokerConfig(
            api_key_file=key_file,
            client_token_file=client_token_file,
            listen_host="127.0.0.1",
            listen_port=0,
            allowed_network="127.0.0.0/24",
            upstream_url=f"http://127.0.0.1:{upstream.server_port}",
            denied_secret_root=denied_root,
            allow_gateway_source=True,
        )
    )
    broker_thread = threading.Thread(target=broker.serve_forever, daemon=True)
    broker_thread.start()
    base_url = f"http://127.0.0.1:{broker.server_port}"
    try:
        health_request = Request(
            f"{base_url}/healthz",
            headers={"Authorization": f"Bearer {client_token}"},
        )
        health = json.loads(urlopen(health_request, timeout=3).read())
        assert health == {"ok": True, "service": "factorforge-model-broker"}

        with pytest.raises(HTTPError) as failure:
            urlopen(f"{base_url}/healthz", timeout=3)
        assert failure.value.code == 403

        wrong_client = Request(
            f"{base_url}/chat/completions",
            data=b'{"model":"deepseek-v4-flash"}',
            headers={"Authorization": "Bearer wrong-broker-client-token"},
            method="POST",
        )
        with pytest.raises(HTTPError) as failure:
            urlopen(wrong_client, timeout=3)
        assert failure.value.code == 403

        request = Request(
            f"{base_url}/chat/completions",
            data=json.dumps(
                {"model": "deepseek-v4-flash", "messages": [{"role": "user", "content": "test"}]}
            ).encode("utf-8"),
            headers={"Authorization": f"Bearer {client_token}", "Content-Type": "application/json"},
            method="POST",
        )
        assert urlopen(request, timeout=3).status == 200
        assert _UpstreamHandler.requests == [
            {
                "path": "/chat/completions",
                "authorization": "Bearer server-side-deepseek-key-test",
                "payload": {
                    "model": "deepseek-v4-flash",
                    "messages": [{"role": "user", "content": "test"}],
                    "max_tokens": 16384,
                },
            }
        ]

        for denied_model in ("other", "deepseek-reasoner"):
            wrong_model = Request(
                f"{base_url}/chat/completions",
                data=json.dumps({"model": denied_model}).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {client_token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with pytest.raises(HTTPError) as failure:
                urlopen(wrong_model, timeout=3)
            assert failure.value.code == 400
        excessive_output = Request(
            f"{base_url}/chat/completions",
            data=json.dumps(
                {
                    "model": "deepseek-v4-flash",
                    "messages": [{"role": "user", "content": "test"}],
                    "max_tokens": 16_385,
                }
            ).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {client_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with pytest.raises(HTTPError) as failure:
            urlopen(excessive_output, timeout=3)
        assert failure.value.code == 400
        with pytest.raises(HTTPError) as failure:
            urlopen(
                Request(
                    f"{base_url}/arbitrary",
                    data=b'{"model":"deepseek-v4-flash"}',
                    headers={"Authorization": f"Bearer {client_token}"},
                    method="POST",
                ),
                timeout=3,
            )
        assert failure.value.code == 404

        for leaked_value in (
            client_token,
            "AWS_SESSION_TOKEN=temporary-session-token-for-broker-test",
            base64.b64encode(b"temporary-secret-for-broker-test").decode("ascii"),
            base64.urlsafe_b64encode(
                b"temporary-session-token-for-broker-test"
            ).decode("ascii").rstrip("="),
            "ASIAABCDEFGHIJKLMNOP",
        ):
            leaked = Request(
                f"{base_url}/chat/completions",
                data=json.dumps(
                    {
                        "model": "deepseek-v4-flash",
                        "messages": [{"role": "user", "content": leaked_value}],
                    }
                ).encode("utf-8"),
                headers={"Authorization": f"Bearer {client_token}", "Content-Type": "application/json"},
                method="POST",
            )
            with pytest.raises(HTTPError) as failure:
                urlopen(leaked, timeout=3)
            assert failure.value.code == 400
        escaped_secret = "".join(
            f"\\u{ord(character):04x}"
            for character in "temporary-session-token-for-broker-test"
        )
        unicode_escaped = Request(
            f"{base_url}/chat/completions",
            data=(
                '{"model":"deepseek-v4-flash","messages":['
                '{"role":"user","content":"' + escaped_secret + '"}]}'
            ).encode("ascii"),
            headers={"Authorization": f"Bearer {client_token}", "Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as failure:
            urlopen(unicode_escaped, timeout=3)
        assert failure.value.code == 400
        assert len(_UpstreamHandler.requests) == 1

        denied_file.unlink()
        stale_file = denied_root / "old_job.secrets"
        stale_file.write_text(f"{client_token}\n", encoding="utf-8")
        stale_file.chmod(0o640)
        with pytest.raises(HTTPError) as failure:
            urlopen(health_request, timeout=3)
        assert failure.value.code == 503
        with pytest.raises(HTTPError) as failure:
            urlopen(request, timeout=3)
        assert failure.value.code == 503
        assert len(_UpstreamHandler.requests) == 1
    finally:
        broker.shutdown()
        broker.server_close()
        upstream.shutdown()
        upstream.server_close()
        broker_thread.join(timeout=3)
        upstream_thread.join(timeout=3)
