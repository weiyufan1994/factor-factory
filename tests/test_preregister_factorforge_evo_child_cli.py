from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from scripts import preregister_factorforge_evo_child as cli


INCIDENT_TRUST_ROOT = "/host-private/oos-incident-trust"
INCIDENT_INSTALLATION_ID = "host-installation-20260813"


def _common_args(command: str) -> list[str]:
    return [
        command,
        "--workspace-root",
        "/workspace",
        "--parent-report-id",
        "PARENT",
        "--child-report-id",
        "CHILD",
        "--expected-host-trust-manifest-sha256",
        "a" * 64,
    ]


def _formal_args(command: str) -> list[str]:
    args = [
        *_common_args(command),
        "--incident-trust-root",
        INCIDENT_TRUST_ROOT,
        "--incident-installation-id",
        INCIDENT_INSTALLATION_ID,
    ]
    if command in {"validate", "materialize"}:
        args.extend(
            [
                "--state",
                "state.json",
                "--conjecture",
                "conjecture.json",
                "--approaches",
                "approaches.json",
                "--base-search-trial-ledger",
                "ledger.json",
                "--metric-verifier-spec",
                "metric.json",
                "--threshold-registration",
                "threshold.json",
                "--child-web-research-plan",
                "web-plan.json",
                "--agent-authoring-admission",
                "authoring-admission.json",
            ]
        )
    return args


def _without_option(args: list[str], option: str) -> list[str]:
    result = list(args)
    index = result.index(option)
    del result[index : index + 2]
    return result


@pytest.mark.parametrize(
    "command", ["validate", "materialize", "validate-receipt"]
)
@pytest.mark.parametrize(
    "missing_option",
    ["--incident-trust-root", "--incident-installation-id"],
)
def test_formal_commands_require_explicit_incident_context_at_parser_boundary(
    command: str,
    missing_option: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli._parser().parse_args(
            _without_option(_formal_args(command), missing_option)
        )

    assert exc_info.value.code == 2
    assert missing_option in capsys.readouterr().err


def test_legacy_generic_host_flags_do_not_satisfy_formal_incident_context(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = _without_option(
        _without_option(_formal_args("validate-receipt"), "--incident-trust-root"),
        "--incident-installation-id",
    )
    args.extend(
        [
            "--host-trust-root",
            INCIDENT_TRUST_ROOT,
            "--installation-id",
            INCIDENT_INSTALLATION_ID,
        ]
    )

    with pytest.raises(SystemExit) as exc_info:
        cli._parser().parse_args(args)

    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "--incident-trust-root" in stderr
    assert "--incident-installation-id" in stderr


def test_projection_command_does_not_require_formal_incident_context() -> None:
    args = cli._parser().parse_args(
        [
            *_common_args("project-search-identity"),
            "--conjecture",
            "conjecture.json",
        ]
    )

    assert args.command == "project-search-identity"
    assert not hasattr(args, "incident_trust_root")
    assert not hasattr(args, "incident_installation_id")


@pytest.mark.parametrize("command", ["validate", "materialize"])
def test_formal_input_command_forwards_exact_incident_context(
    command: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _fake(**kwargs: Any) -> dict[str, str]:
        captured.update(kwargs)
        return {"verdict": "PASS"}

    target = (
        "validate_evo_child_preregistration_inputs"
        if command == "validate"
        else "materialize_evo_child_preregistration"
    )
    monkeypatch.setattr(cli, target, _fake)
    monkeypatch.setattr(cli, "_emit", lambda payload, **_kwargs: None)
    monkeypatch.setattr(sys, "argv", ["preregister", *_formal_args(command)])

    assert cli.main() == 0
    assert captured["incident_trust_root"] == Path(INCIDENT_TRUST_ROOT)
    assert captured["incident_installation_id"] == INCIDENT_INSTALLATION_ID


def test_validate_receipt_forwards_exact_incident_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def _fake(**kwargs: Any) -> dict[str, str]:
        captured.update(kwargs)
        return {"verdict": "PASS"}

    monkeypatch.setattr(cli, "validate_evo_child_preregistration_receipt", _fake)
    monkeypatch.setattr(cli, "_emit", lambda payload, **_kwargs: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["preregister", *_formal_args("validate-receipt")],
    )

    assert cli.main() == 0
    assert captured["incident_trust_root"] == Path(INCIDENT_TRUST_ROOT)
    assert captured["incident_installation_id"] == INCIDENT_INSTALLATION_ID
