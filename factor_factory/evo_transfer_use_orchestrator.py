from __future__ import annotations

import fcntl
import json
import os
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any

from factor_factory.evo_execution_addendum import (
    ADDENDUM_STATUS,
    execution_addendum_path,
    load_and_validate_evo_execution_addendum,
    materialize_evo_execution_addendum,
)
from factor_factory.evo_staging import (
    STAGE_ADMIT_COUNCIL_OUTCOME,
    STAGE_ADMIT_FEEDBACK,
    STAGE_ADMIT_TRANSFER,
    STAGE_RECORD_USE,
    _lifecycle_parent_sha256,
    materialize_evo_v2_stage,
    staging_manifest_path,
    validate_evo_v2_staging_manifest,
)
from factor_factory.evo_v2 import (
    artifact_sha256,
    canonical_json_bytes,
    evo_v2_paths,
    evo_v2_relative_paths,
    load_json_object,
    sha256_file,
    validate_experience_transfer_bundle,
    validate_transfer_use_receipt,
)
from factor_factory.knowledge_context import (
    validate_evo_v2_cold_start_search_receipt,
)
from factor_factory.pre_oos_human_bridge import (
    PRE_OOS_CHILD_INTENT_VERSION,
    pre_oos_child_handoff_path,
    pre_oos_human_approval_path,
)
from factor_factory.research_conjecture import (
    EPISTEMIC_EVOLUTION_LIFECYCLE_VERSION,
    epistemic_evolution_lifecycle_path,
    validate_epistemic_evolution_lifecycle,
    workspace_runtime_trust_manifest,
)
from factor_factory.research_evidence import validate_evidence_reference
from factor_factory.research_obligation_verifier import stable_hash
from factor_factory.research_org.contracts import (
    ResearchOrganizationError,
)
from factor_factory.research_org.runtime_trust import (
    load_runtime_trust_store,
    validate_public_trust_manifest,
)
from factor_factory.researcher_memory import (
    _evo_v2_transfer_use_change_receipt_reasons,
    build_evo_v2_memory_admission,
    load_evo_v2_memory_admissions,
    persist_evo_v2_memory_admission,
)
from factor_factory.researcher_memory_review import (
    build_evo_v2_memory_review_projection,
    validate_evo_v2_memory_review_decision,
)

PREFLIGHT_VERSION = "factorforge_evo_v2_transfer_use_preflight_v1"
PREFLIGHT_VERIFIER_ID = "factorforge_evo_v2_transfer_use_preflight_verifier_v1"
ORCHESTRATION_VERSION = "factorforge_evo_v2_transfer_use_orchestration_v1"
ORCHESTRATION_VERIFIER_ID = "factorforge_evo_v2_transfer_use_orchestration_verifier_v1"
PREFLIGHT_RECEIPT_TYPE = "EVO_V2_TRANSFER_USE_PREFLIGHT_ADMITTED"
ORCHESTRATION_RECEIPT_TYPE = "EVO_V2_TRANSFER_USE_ORCHESTRATION_COMPLETE"
BLOCK_TRANSFER_USE_ORCHESTRATION = (
    "BLOCK_FACTORFORGE_EVO_V2_TRANSFER_USE_ORCHESTRATION_INVALID"
)

_TARGET_BY_MEMORY_STATE = {
    "ADMISSIBLE_MEMORY_FOUND": "TRANSFER_RECORDED",
    "COLD_START_NO_ADMISSIBLE_MEMORY": "COLD_START_RECORDED",
}
_SHA256 = frozenset("0123456789abcdef")


class TransferUseOrchestrationError(ValueError):
    def __init__(self, reasons: Sequence[str]):
        self.reasons = list(dict.fromkeys(str(reason) for reason in reasons if reason))
        super().__init__(";".join(self.reasons))


def _block(reason: str) -> TransferUseOrchestrationError:
    return TransferUseOrchestrationError(
        [f"{BLOCK_TRANSFER_USE_ORCHESTRATION}:{reason}"]
    )


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _SHA256


def transfer_use_preflight_path(root: Path, report_id: str) -> Path:
    return (
        evo_v2_paths(root, report_id)["feedback_ledger"].parent
        / "transfer_use_preflight_verifier.json"
    )


def transfer_use_orchestration_path(root: Path, report_id: str) -> Path:
    return (
        evo_v2_paths(root, report_id)["feedback_ledger"].parent
        / "transfer_use_orchestration.json"
    )


def _read_canonical(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise _block(f"missing_or_unsafe:{path.name}")
    try:
        payload = load_json_object(path)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise _block(f"invalid_json:{path.name}") from exc
    if path.read_bytes() != canonical_json_bytes(payload):
        raise _block(f"noncanonical_json:{path.name}")
    return payload


def _workspace_json_value(
    root: Path,
    raw_path: Path | str,
    *,
    label: str,
) -> tuple[Any, dict[str, str]]:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise _block(f"{label}_outside_workspace") from exc
    if candidate.is_symlink() or not candidate.is_file():
        raise _block(f"missing_or_unsafe:{candidate.name}")
    try:
        value = json.loads(candidate.read_text(encoding="utf-8"))
        expected = (
            json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise _block(f"invalid_json:{candidate.name}") from exc
    if candidate.read_bytes() != expected:
        raise _block(f"noncanonical_json:{candidate.name}")
    return value, {
        "path": candidate.relative_to(root).as_posix(),
        "sha256": sha256_file(candidate),
    }


def _workspace_input(
    root: Path,
    raw_path: Path | str,
    *,
    label: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise _block(f"{label}_outside_workspace") from exc
    payload = _read_canonical(candidate)
    return payload, {
        "path": candidate.relative_to(root).as_posix(),
        "sha256": sha256_file(candidate),
    }


def _read_ref(root: Path, reference: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(reference, Mapping) or not {"path", "sha256"}.issubset(reference):
        raise _block(f"{label}_ref_shape")
    raw = reference.get("path")
    if not isinstance(raw, str) or "\\" in raw:
        raise _block(f"{label}_ref_path")
    relative = PurePosixPath(raw)
    if relative.is_absolute() or ".." in relative.parts:
        raise _block(f"{label}_ref_path")
    path = (root / relative).resolve(strict=False)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise _block(f"{label}_ref_escape") from exc
    payload = _read_canonical(path)
    if reference.get("sha256") != sha256_file(path):
        raise _block(f"{label}_ref_sha256")
    return payload


def _cleanup_atomic_temporaries(path: Path, *, target_is_exact: bool) -> None:
    prefix = f".{path.name}."
    for candidate in path.parent.iterdir():
        if not (candidate.name.startswith(prefix) and candidate.name.endswith(".tmp")):
            continue
        metadata = candidate.lstat()
        linked_exact_target = (
            target_is_exact and metadata.st_nlink == 2 and candidate.samefile(path)
        )
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or (metadata.st_nlink != 1 and not linked_exact_target)
        ):
            raise _block(f"unsafe_atomic_temporary:{candidate.name}")
        candidate.unlink()


def _write_once(path: Path, payload: Mapping[str, Any]) -> bool:
    expected = canonical_json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise _block(f"unsafe_parent:{path.name}")
    target_exists = path.exists() or path.is_symlink()
    target_is_exact = (
        target_exists
        and not path.is_symlink()
        and path.is_file()
        and path.read_bytes() == expected
    )
    if target_exists and not target_is_exact:
        raise _block(f"immutable_conflict:{path.name}")
    _cleanup_atomic_temporaries(path, target_is_exact=target_is_exact)
    if target_is_exact:
        return False
    descriptor, raw_temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(raw_temporary)
    try:
        offset = 0
        while offset < len(expected):
            written = os.write(descriptor, expected[offset:])
            if written <= 0:
                raise OSError("atomic_write_made_no_progress")
            offset += written
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = -1
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
                raise _block(f"immutable_conflict:{path.name}")
            return False
        directory_descriptor = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        return True
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _load_trust(
    *,
    root: Path,
    report_id: str,
    trust_root: Path,
    installation_id: str,
) -> Any:
    private_root = trust_root.expanduser().resolve(strict=True)
    if (
        private_root == root
        or root in private_root.parents
        or private_root in root.parents
    ):
        raise _block("trust_root_overlaps_workspace")
    trust_store = load_runtime_trust_store(
        private_root,
        installation_id=installation_id,
    )
    public = workspace_runtime_trust_manifest(root, report_id=report_id)
    if (
        public is None
        or validate_public_trust_manifest(public)
        or public != trust_store.public_manifest
    ):
        raise _block("trust_manifest_mismatch")
    return trust_store


def _load_lifecycle(root: Path, report_id: str) -> dict[str, Any]:
    lifecycle = _read_canonical(epistemic_evolution_lifecycle_path(root, report_id))
    reasons = validate_epistemic_evolution_lifecycle(
        lifecycle,
        report_id=report_id,
        workspace_root=root,
        require_signed_host_receipts=True,
    )
    if reasons:
        raise TransferUseOrchestrationError(
            [
                f"{BLOCK_TRANSFER_USE_ORCHESTRATION}:lifecycle:{reason}"
                for reason in reasons
            ]
        )
    return lifecycle


def _lifecycle_prefix(
    lifecycle: Mapping[str, Any],
    *,
    state: str,
) -> tuple[dict[str, Any], int, str]:
    events = lifecycle.get("events")
    if not isinstance(events, list):
        raise _block("lifecycle_events")
    indices = [
        index
        for index, event in enumerate(events)
        if isinstance(event, Mapping) and event.get("to_state") == state
    ]
    if len(indices) != 1:
        raise _block(f"lifecycle_state_count:{state}")
    index = indices[0]
    prefix: dict[str, Any] = {
        "contract_version": EPISTEMIC_EVOLUTION_LIFECYCLE_VERSION,
        "report_id": lifecycle.get("report_id"),
        "current_state": state,
        "events": [dict(event) for event in events[: index + 1]],
        "host_authority": lifecycle.get("host_authority"),
    }
    prefix["content_sha256"] = stable_hash(prefix)
    return prefix, index, stable_hash(prefix)


def _minimal_lifecycle(
    lifecycle: Mapping[str, Any],
    *,
    expected_minimal_lifecycle_sha256: str,
) -> tuple[dict[str, Any], int, str, dict[str, Any]]:
    if not _is_sha256(expected_minimal_lifecycle_sha256):
        raise _block("expected_minimal_lifecycle_sha256")
    prefix, index, digest = _lifecycle_prefix(
        lifecycle,
        state="MINIMAL_MECHANISM_DELTA",
    )
    if digest != expected_minimal_lifecycle_sha256:
        raise _block("minimal_lifecycle_cas_mismatch")
    events = lifecycle.get("events")
    if not isinstance(events, list) or events[: index + 1] != prefix["events"]:
        raise _block("minimal_lifecycle_not_ancestor")
    minimal_event = prefix["events"][-1]
    refs = (
        minimal_event.get("evidence_refs")
        if isinstance(minimal_event, Mapping)
        else None
    )
    if not isinstance(refs, list) or len(refs) != 1 or not isinstance(refs[0], dict):
        raise _block("minimal_transition_evidence")
    source_ref = dict(refs[0])
    if not _is_sha256(source_ref.get("dataset_snapshot_hash")) or not _is_sha256(
        source_ref.get("window_hash")
    ):
        raise _block("minimal_transition_evidence_hashes")
    return prefix, index, digest, source_ref


def _load_staging(root: Path, report_id: str) -> dict[str, Any]:
    path = staging_manifest_path(root, report_id)
    manifest = _read_canonical(path)
    reasons = validate_evo_v2_staging_manifest(
        manifest,
        root=root,
        report_id=report_id,
        verify_readback=True,
    )
    if reasons:
        raise TransferUseOrchestrationError(
            [
                f"{BLOCK_TRANSFER_USE_ORCHESTRATION}:staging:{reason}"
                for reason in reasons
            ]
        )
    return manifest


def _staging_prefix(
    manifest: Mapping[str, Any],
    *,
    report_id: str,
    expected_staging_content_sha256: str,
) -> tuple[list[dict[str, Any]], str]:
    if not _is_sha256(expected_staging_content_sha256):
        raise _block("expected_staging_content_sha256")
    events = manifest.get("events")
    if not isinstance(events, list) or not 2 <= len(events) <= 4:
        raise _block("staging_event_count")
    if (
        events[0].get("stage") != STAGE_ADMIT_FEEDBACK
        or events[0].get("outcome") != "QUALIFIED_CONTRADICTION"
        or events[1].get("stage") != STAGE_ADMIT_COUNCIL_OUTCOME
        or events[1].get("outcome") != "MINIMAL_MECHANISM_DELTA"
    ):
        raise _block("minimal_staging_prefix")
    prefix_events = [dict(item) for item in events[:2]]
    prefix = {
        "contract_version": manifest.get("contract_version"),
        "report_id": report_id,
        "host_authority": manifest.get("host_authority"),
        "events": prefix_events,
    }
    digest = stable_hash(prefix)
    if digest != expected_staging_content_sha256:
        raise _block("minimal_staging_cas_mismatch")
    expected_order = [
        STAGE_ADMIT_FEEDBACK,
        STAGE_ADMIT_COUNCIL_OUTCOME,
        STAGE_ADMIT_TRANSFER,
        STAGE_RECORD_USE,
    ]
    if [item.get("stage") for item in events] != expected_order[: len(events)]:
        raise _block("staging_order")
    return [dict(item) for item in events], digest


def _assert_pre_human_pre_oos(root: Path, report_id: str) -> None:
    forbidden = [
        pre_oos_human_approval_path(root, report_id),
        pre_oos_child_handoff_path(root, report_id),
    ]
    protocol = root / "objects" / "research_protocol"
    forbidden.extend(
        [
            protocol / f"metric_verifier_bound_spec__{report_id}.json",
            protocol / f"oos_release_manifest__{report_id}.json",
            protocol / f"factor_proof_panel__{report_id}.parquet",
            protocol / f"factor_proof_verifier_report__{report_id}.json",
            protocol / f"factor_proof_finalization__{report_id}.json",
            protocol / f"metric_verifier_bundle__{report_id}.json",
        ]
    )
    if protocol.is_dir() and not protocol.is_symlink():
        forbidden.extend(protocol.glob(f"component_oos_release__{report_id}__*.json"))
        for path in protocol.glob("evo_child_intent__*.json"):
            if path.is_symlink() or not path.is_file():
                forbidden.append(path)
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                forbidden.append(path)
                continue
            if (
                isinstance(payload, Mapping)
                and payload.get("contract_version") == PRE_OOS_CHILD_INTENT_VERSION
                and payload.get("parent_report_id") == report_id
            ):
                forbidden.append(path)
    existing = sorted(
        {path.name for path in forbidden if path.exists() or path.is_symlink()}
    )
    if existing:
        raise _block("human_child_or_oos_surface_present:" + ",".join(existing))


def _core_refs(
    report_id: str, transfer: Mapping[str, Any], receipt: Mapping[str, Any]
) -> tuple[dict[str, str], dict[str, str]]:
    paths = evo_v2_relative_paths(report_id)
    return (
        {
            "path": paths["experience_transfer_bundle"],
            "sha256": artifact_sha256(transfer),
        },
        {
            "path": paths["transfer_use_receipt"],
            "sha256": artifact_sha256(receipt),
        },
    )


def _validate_candidate_core(
    *,
    root: Path,
    report_id: str,
    transfer: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> tuple[str, dict[str, str], dict[str, str]]:
    paths = evo_v2_paths(root, report_id)
    prior = {
        name: _read_canonical(paths[name])
        for name in (
            "feedback_ledger",
            "mechanism_delta",
            "economic_backprojection",
        )
    }
    relative = evo_v2_relative_paths(report_id)
    known: dict[str, Mapping[str, Any]] = {
        relative[name]: payload for name, payload in prior.items()
    }
    known[relative["experience_transfer_bundle"]] = transfer
    known[relative["transfer_use_receipt"]] = receipt
    reasons = validate_experience_transfer_bundle(
        transfer,
        mechanism_delta=prior["mechanism_delta"],
        economic_backprojection=prior["economic_backprojection"],
        workspace_root=root,
        known_artifacts=known,
        verify_refs=True,
    )
    reasons.extend(
        validate_transfer_use_receipt(
            receipt,
            transfer_bundle=transfer,
            mechanism_delta=prior["mechanism_delta"],
            workspace_root=root,
            known_artifacts=known,
            verify_refs=True,
        )
    )
    identities = [
        payload.get("artifact_identity")
        for payload in [*prior.values(), transfer, receipt]
    ]
    if any(identity != identities[0] for identity in identities[1:]):
        reasons.append("artifact_identity_mismatch")
    identity = transfer.get("artifact_identity")
    if not isinstance(identity, Mapping) or identity.get("report_id") != report_id:
        reasons.append("report_id_mismatch")
    retrieval = transfer.get("retrieval_policy")
    memory_state = (
        retrieval.get("memory_state") if isinstance(retrieval, Mapping) else None
    )
    target = _TARGET_BY_MEMORY_STATE.get(str(memory_state))
    if target is None:
        reasons.append("memory_state")
        target = ""
    if reasons:
        raise TransferUseOrchestrationError(
            [f"{BLOCK_TRANSFER_USE_ORCHESTRATION}:core:{reason}" for reason in reasons]
        )
    bundle_ref, receipt_ref = _core_refs(report_id, transfer, receipt)
    return target, bundle_ref, receipt_ref


def _prepare_evidence(
    *,
    root: Path,
    report_id: str,
    transfer_path: Path | str,
    receipt_path: Path | str,
    review_decision_path: Path | str | None,
    transfer_use_change_path: Path | str | None,
    cold_start_search_path: Path | str | None,
    execution_tests_path: Path | str | None,
    trust_store: Any,
) -> dict[str, Any]:
    transfer, transfer_input_ref = _workspace_input(
        root, transfer_path, label="experience_transfer_bundle_input"
    )
    receipt, receipt_input_ref = _workspace_input(
        root, receipt_path, label="transfer_use_receipt_input"
    )
    target, bundle_ref, use_ref = _validate_candidate_core(
        root=root,
        report_id=report_id,
        transfer=transfer,
        receipt=receipt,
    )
    memory_state = transfer["retrieval_policy"]["memory_state"]
    evidence: dict[str, Any] = {
        "memory_state": memory_state,
        "target_state": target,
        "transfer": transfer,
        "receipt": receipt,
        "transfer_input_ref": transfer_input_ref,
        "receipt_input_ref": receipt_input_ref,
        "canonical_bundle_ref": bundle_ref,
        "canonical_use_ref": use_ref,
        "review_decision": None,
        "review_decision_ref": None,
        "change_receipt": None,
        "change_receipt_ref": None,
        "cold_receipt": None,
        "cold_receipt_ref": None,
        "execution_tests": None,
        "execution_tests_ref": None,
        "execution_target": None,
        "execution_addendum": None,
        "execution_addendum_ref": None,
    }
    if memory_state == "ADMISSIBLE_MEMORY_FOUND":
        if (
            review_decision_path is None
            or transfer_use_change_path is None
            or cold_start_search_path is not None
        ):
            raise _block("found_branch_evidence_arguments")
        if execution_tests_path is None:
            raise _block("execution_addendum_required_for_positive_hit")
        decision, decision_ref = _workspace_input(
            root, review_decision_path, label="review_decision"
        )
        change, change_ref = _workspace_input(
            root, transfer_use_change_path, label="transfer_use_change"
        )
        execution_input, execution_input_ref = _workspace_json_value(
            root, execution_tests_path, label="execution_tests"
        )
        execution_tests = (
            execution_input.get("execution_tests")
            if isinstance(execution_input, Mapping)
            else execution_input
        )
        if not isinstance(execution_tests, list) or not execution_tests:
            raise _block("execution_tests_nonempty_array_required")
        try:
            projection = build_evo_v2_memory_review_projection(
                experience_transfer_bundle=transfer,
                transfer_use_receipt=receipt,
                experience_transfer_bundle_ref=bundle_ref,
                transfer_use_receipt_ref=use_ref,
                trust_store=trust_store,
                source_workspace=None,
            )
        except (ResearchOrganizationError, KeyError, TypeError, ValueError) as exc:
            detail = (
                exc.token
                if isinstance(exc, ResearchOrganizationError)
                else type(exc).__name__
            )
            raise _block(f"review_projection:{detail}") from exc
        review_reasons = validate_evo_v2_memory_review_decision(
            decision,
            projection=projection,
            trust_store=trust_store,
        )
        change_reasons = _evo_v2_transfer_use_change_receipt_reasons(
            change,
            transfer_bundle=transfer,
            transfer_receipt=receipt,
            trust_store=trust_store,
            workspace=root,
            verify_refs=True,
        )
        if review_reasons or change_reasons:
            raise TransferUseOrchestrationError(
                [
                    *(
                        f"{BLOCK_TRANSFER_USE_ORCHESTRATION}:review:{reason}"
                        for reason in review_reasons
                    ),
                    *(
                        f"{BLOCK_TRANSFER_USE_ORCHESTRATION}:"
                        f"transfer_use_change:{reason}"
                        for reason in change_reasons
                    ),
                ]
            )
        evidence.update(
            {
                "review_decision": decision,
                "review_decision_ref": decision_ref,
                "change_receipt": change,
                "change_receipt_ref": change_ref,
                "execution_tests": execution_tests,
                "execution_tests_ref": execution_input_ref,
            }
        )
        stages = {
            item.get("execution_stage")
            for item in execution_tests
            if isinstance(item, Mapping)
        }
        if len(stages) != 1 or not all(
            isinstance(item, Mapping) for item in execution_tests
        ):
            raise _block("execution_tests_single_execution_target_required")
        evidence["execution_target"] = stages.pop()
        return evidence

    if (
        cold_start_search_path is None
        or review_decision_path is not None
        or transfer_use_change_path is not None
        or execution_tests_path is not None
    ):
        raise _block("cold_branch_evidence_arguments")
    cold, cold_ref = _workspace_input(
        root, cold_start_search_path, label="cold_start_search_receipt"
    )
    retrieval_refs = transfer["retrieval_policy"]["retrieval_evidence_refs"]
    if retrieval_refs != [cold_ref]:
        raise _block("cold_start_search_ref_not_sole_retrieval_evidence")
    cold_reasons = validate_evo_v2_cold_start_search_receipt(
        cold,
        artifact_identity=transfer["artifact_identity"],
        mechanism_fingerprint=transfer["mechanism_fingerprint"],
        trust_store=trust_store,
    )
    try:
        projection = build_evo_v2_memory_review_projection(
            experience_transfer_bundle=transfer,
            transfer_use_receipt=receipt,
            experience_transfer_bundle_ref=bundle_ref,
            transfer_use_receipt_ref=use_ref,
            trust_store=trust_store,
            source_workspace=None,
            cold_start_search_receipt_ref=cold_ref,
            cold_start_search_receipt=cold,
        )
    except (ResearchOrganizationError, KeyError, TypeError, ValueError) as exc:
        detail = (
            exc.token
            if isinstance(exc, ResearchOrganizationError)
            else type(exc).__name__
        )
        raise _block(f"cold_projection:{detail}") from exc
    if (
        cold_reasons
        or projection.get("eligible_for_independent_reviewer_consideration") is not True
        or projection.get("review_checks", {}).get(
            "cold_start_has_runtime_signed_zero_hit_proof"
        )
        is not True
    ):
        raise TransferUseOrchestrationError(
            [
                f"{BLOCK_TRANSFER_USE_ORCHESTRATION}:cold_start:{reason}"
                for reason in (cold_reasons or ["runtime_signed_zero_hit_required"])
            ]
        )
    evidence.update({"cold_receipt": cold, "cold_receipt_ref": cold_ref})
    evidence["execution_target"] = None
    return evidence


def _preflight_payload(
    *,
    report_id: str,
    evidence: Mapping[str, Any],
    minimal_lifecycle_sha256: str,
    minimal_staging_sha256: str,
    source_lifecycle_evidence: Mapping[str, Any],
    trust_store: Any,
) -> dict[str, Any]:
    identity = dict(evidence["transfer"]["artifact_identity"])
    review_gate = {
        "memory_state": evidence["memory_state"],
        "review_decision_ref": evidence["review_decision_ref"],
        "review_decision_sha256": (
            evidence["review_decision"].get("decision_sha256")
            if isinstance(evidence["review_decision"], Mapping)
            else None
        ),
        "transfer_use_change_ref": evidence["change_receipt_ref"],
        "transfer_use_change_sha256": (
            evidence["change_receipt"].get("change_receipt_sha256")
            if isinstance(evidence["change_receipt"], Mapping)
            else None
        ),
        "cold_start_search_ref": evidence["cold_receipt_ref"],
        "cold_start_search_receipt_id": (
            evidence["cold_receipt"].get("receipt_id")
            if isinstance(evidence["cold_receipt"], Mapping)
            else None
        ),
        "execution_tests_ref": evidence["execution_tests_ref"],
        "execution_target": evidence["execution_target"],
    }
    core = {
        "contract_version": PREFLIGHT_VERSION,
        "verifier_id": PREFLIGHT_VERIFIER_ID,
        "verifier_status": "PASS",
        "verifier_source_sha256": sha256_file(Path(__file__)),
        "dataset_snapshot_hash": source_lifecycle_evidence["dataset_snapshot_hash"],
        "window_hash": source_lifecycle_evidence["window_hash"],
        "report_id": report_id,
        "artifact_identity": identity,
        "authorized_transition_state": evidence["target_state"],
        "minimal_lifecycle_sha256": minimal_lifecycle_sha256,
        "minimal_staging_content_sha256": minimal_staging_sha256,
        "input_refs": {
            "experience_transfer_bundle_input": evidence["transfer_input_ref"],
            "transfer_use_receipt_input": evidence["receipt_input_ref"],
            "canonical_experience_transfer_bundle": evidence["canonical_bundle_ref"],
            "canonical_transfer_use_receipt": evidence["canonical_use_ref"],
            "execution_tests_input": evidence["execution_tests_ref"],
        },
        "review_gate": review_gate,
        "authority": {
            "host_only_transition": True,
            "structured_preregistered_test_binding_required_for_positive_hit": True,
            "transfer_test_execution_completed": False,
            "runtime_signed_zero_hit_required_for_cold_start": True,
            "human_approval_granted": False,
            "oos_accessed": False,
            "child_execution_allowed": False,
            "factor_verdict": "NOT_ISSUED",
            "canonical_memory_write_allowed": False,
            "skill_or_policy_mutation_allowed": False,
        },
    }
    host_receipt = trust_store.sign(
        "host_admission",
        {
            "receipt_type": PREFLIGHT_RECEIPT_TYPE,
            "identity": identity,
            "bindings": {
                "preflight_core_sha256": stable_hash(core),
                "authorized_transition_state": evidence["target_state"],
                "minimal_lifecycle_sha256": minimal_lifecycle_sha256,
                "minimal_staging_content_sha256": minimal_staging_sha256,
                "input_refs": core["input_refs"],
                "review_gate": review_gate,
            },
            "outcome": {
                "verifier_status": "PASS",
                "lifecycle_transition_only": True,
                "human_approval_granted": False,
                "oos_accessed": False,
                "child_execution_allowed": False,
                "factor_verdict": "NOT_ISSUED",
                "canonical_memory_write_allowed": False,
            },
        },
    )
    payload = {**core, "host_preflight_receipt": host_receipt}
    payload["content_sha256"] = stable_hash(payload)
    return payload


def _preflight_reference(
    root: Path, report_id: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    path = transfer_use_preflight_path(root, report_id)
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
        "dataset_snapshot_hash": payload["dataset_snapshot_hash"],
        "window_hash": payload["window_hash"],
        "verifier_id": payload["verifier_id"],
        "verifier_status": payload["verifier_status"],
        "verifier_source_sha256": payload["verifier_source_sha256"],
        "report_id": report_id,
        "authorized_transition_state": payload["authorized_transition_state"],
    }


def _validate_preflight_payload(
    payload: Mapping[str, Any],
    *,
    root: Path,
    report_id: str,
    expected: Mapping[str, Any],
    trust_store: Any,
) -> dict[str, Any]:
    if payload != expected:
        raise _block("preflight_replay_mismatch")
    fields = {
        "contract_version",
        "verifier_id",
        "verifier_status",
        "verifier_source_sha256",
        "dataset_snapshot_hash",
        "window_hash",
        "report_id",
        "artifact_identity",
        "authorized_transition_state",
        "minimal_lifecycle_sha256",
        "minimal_staging_content_sha256",
        "input_refs",
        "review_gate",
        "authority",
        "host_preflight_receipt",
        "content_sha256",
    }
    if set(payload) != fields or payload.get("content_sha256") != stable_hash(
        {key: value for key, value in payload.items() if key != "content_sha256"}
    ):
        raise _block("preflight_shape_or_hash")
    receipt = payload.get("host_preflight_receipt")
    signature_reasons = (
        trust_store.verify(receipt, expected_issuer="host_admission")
        if isinstance(receipt, Mapping)
        else ["receipt_object"]
    )
    core = {
        key: value
        for key, value in payload.items()
        if key not in {"host_preflight_receipt", "content_sha256"}
    }
    if (
        signature_reasons
        or not isinstance(receipt, Mapping)
        or receipt.get("receipt_type") != PREFLIGHT_RECEIPT_TYPE
        or receipt.get("identity") != payload.get("artifact_identity")
        or receipt.get("bindings")
        != {
            "preflight_core_sha256": stable_hash(core),
            "authorized_transition_state": payload.get("authorized_transition_state"),
            "minimal_lifecycle_sha256": payload.get("minimal_lifecycle_sha256"),
            "minimal_staging_content_sha256": payload.get(
                "minimal_staging_content_sha256"
            ),
            "input_refs": payload.get("input_refs"),
            "review_gate": payload.get("review_gate"),
        }
    ):
        raise _block("preflight_host_signature")
    reference = _preflight_reference(root, report_id, payload)
    evidence_reasons = validate_evidence_reference(
        reference,
        workspace_root=root,
        token_prefix=BLOCK_TRANSFER_USE_ORCHESTRATION,
        require_verifier_pass=True,
        allowed_verifier_ids={PREFLIGHT_VERIFIER_ID},
        expected_verifier_source_sha256=sha256_file(Path(__file__)),
        expected_bindings={
            "report_id": report_id,
            "authorized_transition_state": payload["authorized_transition_state"],
        },
    )
    if evidence_reasons:
        raise TransferUseOrchestrationError(evidence_reasons)
    return reference


def _run_lifecycle_transition(
    *,
    root: Path,
    report_id: str,
    target_state: str,
    evidence_ref: Mapping[str, Any],
    expected_parent_sha256: str,
    trust_root: Path,
    installation_id: str,
) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    script = repository_root / "scripts/record_factorforge_evo_v2_lifecycle.py"
    command = [
        sys.executable,
        str(script),
        "--workspace-root",
        str(root),
        "--report-id",
        report_id,
        "--to-state",
        target_state,
        "--evidence-ref",
        json.dumps(
            dict(evidence_ref),
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        "--expected-parent-sha256",
        expected_parent_sha256,
        "--trust-root",
        str(trust_root),
        "--installation-id",
        installation_id,
    ]
    completed = subprocess.run(
        command,
        cwd=repository_root,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip()[-2000:]
        raise _block(
            "signed_lifecycle_transition_failed:"
            + (detail or f"return_code_{completed.returncode}")
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise _block("signed_lifecycle_transition_output") from exc
    if (
        not isinstance(result, Mapping)
        or result.get("verdict") != "PASS"
        or result.get("current_state") != target_state
    ):
        raise _block("signed_lifecycle_transition_result")


def _target_transition(
    *,
    lifecycle: Mapping[str, Any],
    minimal_index: int,
    target_state: str,
    preflight_ref: Mapping[str, Any],
) -> dict[str, Any]:
    events = lifecycle.get("events")
    if not isinstance(events, list) or len(events) != minimal_index + 2:
        raise _block("target_transition_position")
    event = events[minimal_index + 1]
    if (
        not isinstance(event, dict)
        or event.get("from_state") != "MINIMAL_MECHANISM_DELTA"
        or event.get("to_state") != target_state
        or event.get("evidence_refs") != [dict(preflight_ref)]
        or event.get("actor") != "Ultimate Host"
    ):
        raise _block("target_transition_binding")
    return event


def _normalized_private_ref(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "admission_id",
        "admission_sha256",
        "relative_path",
        "file_sha256",
        "semantic_authority",
    }
    output = {field: value.get(field) for field in fields}
    if (
        not all(isinstance(output[field], str) and output[field] for field in fields)
        or not _is_sha256(output["admission_sha256"])
        or not _is_sha256(output["file_sha256"])
    ):
        raise _block("private_admission_ref")
    return output


def _execution_addendum_ref(
    root: Path,
    report_id: str,
    payload: Mapping[str, Any],
) -> dict[str, str]:
    path = execution_addendum_path(root, report_id)
    if _read_canonical(path) != dict(payload):
        raise _block("execution_addendum_readback")
    content_sha256 = payload.get("content_sha256")
    if not _is_sha256(content_sha256):
        raise _block("execution_addendum_content_sha256")
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
        "content_sha256": content_sha256,
    }


def _admit_positive_transfer(
    *,
    root: Path,
    evidence: Mapping[str, Any],
    admissions_root: Path,
    trust_store: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    repository_root = Path(__file__).resolve().parents[1]
    private_root = Path(admissions_root).expanduser().resolve(strict=False)
    canonical_bundle_ref = dict(evidence["canonical_bundle_ref"])
    canonical_use_ref = dict(evidence["canonical_use_ref"])
    admission = build_evo_v2_memory_admission(
        workspace=root,
        experience_transfer_bundle_ref=canonical_bundle_ref,
        transfer_use_receipt_ref=canonical_use_ref,
        review_decision_receipt=evidence["review_decision"],
        trust_store=trust_store,
        transfer_use_change_receipt=evidence["change_receipt"],
    )
    persisted = persist_evo_v2_memory_admission(
        root=private_root,
        admission=admission,
        repo_root=repository_root,
        workspace=root,
        trust_store=trust_store,
    )
    loaded = load_evo_v2_memory_admissions(
        root=private_root,
        repo_root=repository_root,
        trust_store=trust_store,
        source_workspace=root,
    )
    matching = [
        item for item in loaded if item.get("admission_id") == admission["admission_id"]
    ]
    if len(matching) != 1 or matching[0] != admission:
        raise _block("private_admission_readback")
    return admission, _normalized_private_ref(persisted)


def _final_payload(
    *,
    root: Path,
    report_id: str,
    evidence: Mapping[str, Any],
    minimal_lifecycle_sha256: str,
    minimal_staging_sha256: str,
    preflight_ref: Mapping[str, Any],
    lifecycle: Mapping[str, Any],
    staging: Mapping[str, Any],
    private_admission_ref: Mapping[str, Any] | None,
    trust_store: Any,
) -> dict[str, Any]:
    found = evidence["memory_state"] == "ADMISSIBLE_MEMORY_FOUND"
    addendum = evidence.get("execution_addendum")
    addendum_ref = evidence.get("execution_addendum_ref")
    if found:
        if (
            not isinstance(addendum, Mapping)
            or addendum.get("status") != ADDENDUM_STATUS
            or addendum.get("execution_binding", {}).get("state")
            != "PREREGISTERED_AND_BOUND_NOT_EVALUATED"
            or addendum.get("execution_binding", {}).get("execution_completed")
            is not False
            or not isinstance(addendum_ref, Mapping)
        ):
            raise _block("validated_execution_addendum_required")
    elif addendum is not None or addendum_ref is not None:
        raise _block("cold_start_execution_addendum_forbidden")
    lifecycle_path = epistemic_evolution_lifecycle_path(root, report_id)
    manifest_path = staging_manifest_path(root, report_id)
    canonical_paths = evo_v2_paths(root, report_id)
    canonical_refs = {
        name: {
            "path": canonical_paths[name].relative_to(root).as_posix(),
            "sha256": sha256_file(canonical_paths[name]),
            "content_sha256": _read_canonical(canonical_paths[name])["content_sha256"],
        }
        for name in ("experience_transfer_bundle", "transfer_use_receipt")
    }
    gate_evidence = {
        "review_decision_ref": evidence["review_decision_ref"],
        "review_decision_sha256": (
            evidence["review_decision"].get("decision_sha256")
            if isinstance(evidence["review_decision"], Mapping)
            else None
        ),
        "transfer_use_change_ref": evidence["change_receipt_ref"],
        "transfer_use_change_sha256": (
            evidence["change_receipt"].get("change_receipt_sha256")
            if isinstance(evidence["change_receipt"], Mapping)
            else None
        ),
        "cold_start_search_ref": evidence["cold_receipt_ref"],
        "cold_start_search_receipt_id": (
            evidence["cold_receipt"].get("receipt_id")
            if isinstance(evidence["cold_receipt"], Mapping)
            else None
        ),
        "private_memory_admission_ref": (
            dict(private_admission_ref)
            if isinstance(private_admission_ref, Mapping)
            else None
        ),
        "execution_addendum_ref": addendum_ref,
        "execution_addendum_status": (
            addendum.get("status") if isinstance(addendum, Mapping) else None
        ),
    }
    core = {
        "contract_version": ORCHESTRATION_VERSION,
        "verifier_id": ORCHESTRATION_VERIFIER_ID,
        "verifier_status": "PASS",
        "verifier_source_sha256": sha256_file(Path(__file__)),
        "dataset_snapshot_hash": _read_canonical(
            transfer_use_preflight_path(root, report_id)
        )["dataset_snapshot_hash"],
        "window_hash": _read_canonical(transfer_use_preflight_path(root, report_id))[
            "window_hash"
        ],
        "report_id": report_id,
        "artifact_identity": dict(evidence["transfer"]["artifact_identity"]),
        "memory_state": evidence["memory_state"],
        "lifecycle": {
            "path": lifecycle_path.relative_to(root).as_posix(),
            "sha256": sha256_file(lifecycle_path),
            "content_sha256": lifecycle["content_sha256"],
            "lifecycle_sha256": stable_hash(lifecycle),
            "minimal_lifecycle_sha256": minimal_lifecycle_sha256,
            "current_state": lifecycle["current_state"],
            "preflight_evidence_ref": dict(preflight_ref),
        },
        "staging_manifest": {
            "path": manifest_path.relative_to(root).as_posix(),
            "sha256": sha256_file(manifest_path),
            "content_sha256": staging["content_sha256"],
            "minimal_prefix_content_sha256": minimal_staging_sha256,
            "event_count": len(staging["events"]),
            "event_sha256s": [item["event_sha256"] for item in staging["events"]],
        },
        "canonical_artifacts": canonical_refs,
        "gate_evidence": gate_evidence,
        "authority": {
            "four_stage_events_exact_readback": True,
            "preregistered_transfer_tests_bound": found,
            "transfer_test_execution_completed": False,
            "transfer_execution_state": (
                "PREREGISTERED_AND_BOUND_NOT_EXECUTED"
                if found
                else "NOT_APPLICABLE_COLD_START"
            ),
            "cold_start_zero_hit_verified": evidence["memory_state"]
            == "COLD_START_NO_ADMISSIBLE_MEMORY",
            "human_approval_granted": False,
            "oos_accessed": False,
            "child_execution_allowed": False,
            "factor_verdict": "NOT_ISSUED",
            "canonical_memory_write_allowed": False,
            "canonical_factor_write_allowed": False,
            "skill_or_policy_mutation_allowed": False,
        },
    }
    host_receipt = trust_store.sign(
        "host_admission",
        {
            "receipt_type": ORCHESTRATION_RECEIPT_TYPE,
            "identity": core["artifact_identity"],
            "bindings": {
                "orchestration_core_sha256": stable_hash(core),
                "memory_state": core["memory_state"],
                "lifecycle": core["lifecycle"],
                "staging_manifest": core["staging_manifest"],
                "canonical_artifacts": canonical_refs,
                "gate_evidence": gate_evidence,
            },
            "outcome": {
                "verifier_status": "PASS",
                "four_stage_events_exact_readback": True,
                "human_approval_granted": False,
                "oos_accessed": False,
                "child_execution_allowed": False,
                "factor_verdict": "NOT_ISSUED",
                "canonical_memory_write_allowed": False,
                "canonical_factor_write_allowed": False,
            },
        },
    )
    payload = {**core, "host_completion_receipt": host_receipt}
    payload["content_sha256"] = stable_hash(payload)
    return payload


def _validate_final_signature(payload: Mapping[str, Any], *, trust_store: Any) -> None:
    fields = {
        "contract_version",
        "verifier_id",
        "verifier_status",
        "verifier_source_sha256",
        "dataset_snapshot_hash",
        "window_hash",
        "report_id",
        "artifact_identity",
        "memory_state",
        "lifecycle",
        "staging_manifest",
        "canonical_artifacts",
        "gate_evidence",
        "authority",
        "host_completion_receipt",
        "content_sha256",
    }
    if (
        set(payload) != fields
        or payload.get("contract_version") != ORCHESTRATION_VERSION
        or payload.get("verifier_id") != ORCHESTRATION_VERIFIER_ID
        or payload.get("verifier_status") != "PASS"
        or payload.get("content_sha256")
        != stable_hash(
            {key: value for key, value in payload.items() if key != "content_sha256"}
        )
    ):
        raise _block("orchestration_shape_or_hash")
    receipt = payload.get("host_completion_receipt")
    signature_reasons = (
        trust_store.verify(receipt, expected_issuer="host_admission")
        if isinstance(receipt, Mapping)
        else ["receipt_object"]
    )
    core = {
        key: value
        for key, value in payload.items()
        if key not in {"host_completion_receipt", "content_sha256"}
    }
    if (
        signature_reasons
        or not isinstance(receipt, Mapping)
        or receipt.get("receipt_type") != ORCHESTRATION_RECEIPT_TYPE
        or receipt.get("identity") != payload.get("artifact_identity")
        or receipt.get("bindings")
        != {
            "orchestration_core_sha256": stable_hash(core),
            "memory_state": payload.get("memory_state"),
            "lifecycle": payload.get("lifecycle"),
            "staging_manifest": payload.get("staging_manifest"),
            "canonical_artifacts": payload.get("canonical_artifacts"),
            "gate_evidence": payload.get("gate_evidence"),
        }
    ):
        raise _block("orchestration_host_signature")


@contextmanager
def _orchestration_lock(root: Path, report_id: str):
    directory = evo_v2_paths(root, report_id)["feedback_ledger"].parent
    directory.mkdir(parents=True, exist_ok=True)
    if directory.is_symlink():
        raise _block("orchestration_directory_symlink")
    path = directory / ".transfer_use_orchestration.lock"
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _evidence_from_final_report(
    *,
    root: Path,
    report: Mapping[str, Any],
    trust_store: Any,
) -> dict[str, Any]:
    inputs = report.get("lifecycle")
    preflight_ref = (
        inputs.get("preflight_evidence_ref") if isinstance(inputs, Mapping) else None
    )
    preflight = _read_ref(root, preflight_ref, label="preflight")
    input_refs = preflight.get("input_refs")
    gate = preflight.get("review_gate")
    if not isinstance(input_refs, Mapping) or not isinstance(gate, Mapping):
        raise _block("preflight_embedded_bindings")
    return _prepare_evidence(
        root=root,
        report_id=str(report.get("report_id") or ""),
        transfer_path=input_refs["experience_transfer_bundle_input"]["path"],
        receipt_path=input_refs["transfer_use_receipt_input"]["path"],
        review_decision_path=(
            gate["review_decision_ref"]["path"]
            if isinstance(gate.get("review_decision_ref"), Mapping)
            else None
        ),
        transfer_use_change_path=(
            gate["transfer_use_change_ref"]["path"]
            if isinstance(gate.get("transfer_use_change_ref"), Mapping)
            else None
        ),
        cold_start_search_path=(
            gate["cold_start_search_ref"]["path"]
            if isinstance(gate.get("cold_start_search_ref"), Mapping)
            else None
        ),
        execution_tests_path=(
            input_refs["execution_tests_input"]["path"]
            if isinstance(input_refs.get("execution_tests_input"), Mapping)
            else None
        ),
        trust_store=trust_store,
    )


def validate_evo_v2_transfer_use_orchestration(
    *,
    workspace_root: Path,
    report_id: str,
    expected_minimal_lifecycle_sha256: str,
    expected_staging_content_sha256: str,
    trust_root: Path,
    installation_id: str,
    admissions_root: Path | None = None,
) -> dict[str, Any]:
    root = workspace_root.expanduser().resolve(strict=True)
    trust_store = _load_trust(
        root=root,
        report_id=report_id,
        trust_root=trust_root,
        installation_id=installation_id,
    )
    report_path = transfer_use_orchestration_path(root, report_id)
    report = _read_canonical(report_path)
    _validate_final_signature(report, trust_store=trust_store)
    if report.get("report_id") != report_id:
        raise _block("orchestration_report_id")
    evidence = _evidence_from_final_report(
        root=root,
        report=report,
        trust_store=trust_store,
    )
    lifecycle = _load_lifecycle(root, report_id)
    _minimal, minimal_index, minimal_digest, source_ref = _minimal_lifecycle(
        lifecycle,
        expected_minimal_lifecycle_sha256=expected_minimal_lifecycle_sha256,
    )
    if lifecycle.get("current_state") != evidence["target_state"]:
        raise _block("lifecycle_target_state")
    staging = _load_staging(root, report_id)
    events, minimal_staging = _staging_prefix(
        staging,
        report_id=report_id,
        expected_staging_content_sha256=expected_staging_content_sha256,
    )
    if len(events) != 4:
        raise _block("four_staging_events_required")
    expected_preflight = _preflight_payload(
        report_id=report_id,
        evidence=evidence,
        minimal_lifecycle_sha256=minimal_digest,
        minimal_staging_sha256=minimal_staging,
        source_lifecycle_evidence=source_ref,
        trust_store=trust_store,
    )
    preflight = _read_canonical(transfer_use_preflight_path(root, report_id))
    preflight_ref = _validate_preflight_payload(
        preflight,
        root=root,
        report_id=report_id,
        expected=expected_preflight,
        trust_store=trust_store,
    )
    _target_transition(
        lifecycle=lifecycle,
        minimal_index=minimal_index,
        target_state=evidence["target_state"],
        preflight_ref=preflight_ref,
    )
    canonical_paths = evo_v2_paths(root, report_id)
    if (
        _read_canonical(canonical_paths["experience_transfer_bundle"])
        != evidence["transfer"]
        or _read_canonical(canonical_paths["transfer_use_receipt"])
        != evidence["receipt"]
    ):
        raise _block("canonical_core_readback")

    private_ref: dict[str, Any] | None = None
    if evidence["memory_state"] == "ADMISSIBLE_MEMORY_FOUND":
        if admissions_root is None:
            raise _block("admissions_root_required")
        repository_root = Path(__file__).resolve().parents[1]
        private_root = Path(admissions_root).expanduser().resolve(strict=True)
        admissions = load_evo_v2_memory_admissions(
            root=private_root,
            repo_root=repository_root,
            trust_store=trust_store,
            source_workspace=root,
        )
        expected_private = report.get("gate_evidence", {}).get(
            "private_memory_admission_ref"
        )
        if not isinstance(expected_private, Mapping):
            raise _block("private_admission_ref_missing")
        matching = [
            admission
            for admission in admissions
            if admission.get("admission_id") == expected_private.get("admission_id")
        ]
        if (
            len(matching) != 1
            or matching[0].get("admission_sha256")
            != expected_private.get("admission_sha256")
            or matching[0].get("core_payloads", {}).get("experience_transfer_bundle")
            != evidence["transfer"]
            or matching[0].get("core_payloads", {}).get("transfer_use_receipt")
            != evidence["receipt"]
        ):
            raise _block("private_admission_readback")
        private_path = private_root / str(expected_private.get("relative_path") or "")
        if (
            private_path.is_symlink()
            or not private_path.is_file()
            or sha256_file(private_path) != expected_private.get("file_sha256")
        ):
            raise _block("private_admission_file_readback")
        private_ref = dict(expected_private)
        addendum, addendum_reasons = load_and_validate_evo_execution_addendum(
            workspace_root=root,
            report_id=report_id,
            trust_store=trust_store,
            private_admission_ref=private_ref,
            admissions_root=private_root,
            repository_root=repository_root,
        )
        if addendum is None or addendum_reasons:
            raise TransferUseOrchestrationError(
                [
                    f"{BLOCK_TRANSFER_USE_ORCHESTRATION}:execution_addendum:{reason}"
                    for reason in (addendum_reasons or ["validated_payload_required"])
                ]
            )
        addendum_ref = _execution_addendum_ref(root, report_id, addendum)
        if (
            report.get("gate_evidence", {}).get("execution_addendum_ref")
            != addendum_ref
        ):
            raise _block("execution_addendum_final_binding")
        evidence["execution_addendum"] = addendum
        evidence["execution_addendum_ref"] = addendum_ref
    elif (
        report.get("gate_evidence", {}).get("private_memory_admission_ref") is not None
    ):
        raise _block("cold_start_private_admission_forbidden")
    else:
        addendum_path = execution_addendum_path(root, report_id)
        if addendum_path.exists() or addendum_path.is_symlink():
            raise _block("cold_start_execution_addendum_forbidden")

    expected_final = _final_payload(
        root=root,
        report_id=report_id,
        evidence=evidence,
        minimal_lifecycle_sha256=minimal_digest,
        minimal_staging_sha256=minimal_staging,
        preflight_ref=preflight_ref,
        lifecycle=lifecycle,
        staging=staging,
        private_admission_ref=private_ref,
        trust_store=trust_store,
    )
    if report != expected_final:
        raise _block("orchestration_replay_mismatch")
    return {
        "verdict": "PASS",
        "status": "IDEMPOTENT_VERIFIED",
        "report_id": report_id,
        "memory_state": evidence["memory_state"],
        "lifecycle_state": lifecycle["current_state"],
        "lifecycle_sha256": stable_hash(lifecycle),
        "staging_manifest_content_sha256": staging["content_sha256"],
        "staging_event_count": 4,
        "orchestration_ref": {
            "path": report_path.relative_to(root).as_posix(),
            "sha256": sha256_file(report_path),
            "content_sha256": report["content_sha256"],
        },
        "authority": dict(report["authority"]),
    }


def orchestrate_evo_v2_transfer_use(
    *,
    workspace_root: Path,
    report_id: str,
    expected_minimal_lifecycle_sha256: str,
    expected_staging_content_sha256: str,
    experience_transfer_bundle_path: Path | str,
    transfer_use_receipt_path: Path | str,
    trust_root: Path,
    installation_id: str,
    review_decision_receipt_path: Path | str | None = None,
    transfer_use_change_receipt_path: Path | str | None = None,
    cold_start_search_receipt_path: Path | str | None = None,
    execution_tests_path: Path | str | None = None,
    admissions_root: Path | None = None,
) -> dict[str, Any]:
    """Close MINIMAL -> transfer/cold through Host CAS and exact four-stage readback.

    This function never authors experience semantics, changes a factor, releases
    OOS, grants human approval, or promotes canonical memory.  All semantic core
    payloads and runtime evidence must already exist as immutable workspace files.
    """

    root = workspace_root.expanduser().resolve(strict=True)
    trust_store = _load_trust(
        root=root,
        report_id=report_id,
        trust_root=trust_root,
        installation_id=installation_id,
    )
    with _orchestration_lock(root, report_id):
        report_path = transfer_use_orchestration_path(root, report_id)
        if report_path.exists() or report_path.is_symlink():
            replay = validate_evo_v2_transfer_use_orchestration(
                workspace_root=root,
                report_id=report_id,
                expected_minimal_lifecycle_sha256=(expected_minimal_lifecycle_sha256),
                expected_staging_content_sha256=(expected_staging_content_sha256),
                trust_root=trust_root,
                installation_id=installation_id,
                admissions_root=admissions_root,
            )
            return {
                **replay,
                "status": "IDEMPOTENT_REPLAY",
                "actions": {
                    "preflight_materialized": False,
                    "host_lifecycle_transition_performed": False,
                    "transfer_materialized": False,
                    "use_materialized": False,
                    "private_admission_verified": False,
                    "execution_addendum_materialized": False,
                    "orchestration_materialized": False,
                },
            }
        _assert_pre_human_pre_oos(root, report_id)
        evidence = _prepare_evidence(
            root=root,
            report_id=report_id,
            transfer_path=experience_transfer_bundle_path,
            receipt_path=transfer_use_receipt_path,
            review_decision_path=review_decision_receipt_path,
            transfer_use_change_path=transfer_use_change_receipt_path,
            cold_start_search_path=cold_start_search_receipt_path,
            execution_tests_path=execution_tests_path,
            trust_store=trust_store,
        )
        if (
            evidence["memory_state"] == "ADMISSIBLE_MEMORY_FOUND"
            and admissions_root is None
        ):
            raise _block("admissions_root_required")

        lifecycle = _load_lifecycle(root, report_id)
        _minimal, minimal_index, minimal_digest, source_ref = _minimal_lifecycle(
            lifecycle,
            expected_minimal_lifecycle_sha256=expected_minimal_lifecycle_sha256,
        )
        staging = _load_staging(root, report_id)
        staging_events, minimal_staging = _staging_prefix(
            staging,
            report_id=report_id,
            expected_staging_content_sha256=expected_staging_content_sha256,
        )
        current_state = lifecycle.get("current_state")
        if current_state not in {"MINIMAL_MECHANISM_DELTA", evidence["target_state"]}:
            raise _block(f"lifecycle_state:{current_state}")
        if current_state == "MINIMAL_MECHANISM_DELTA" and len(staging_events) != 2:
            raise _block("future_stage_before_lifecycle_transition")

        expected_preflight = _preflight_payload(
            report_id=report_id,
            evidence=evidence,
            minimal_lifecycle_sha256=minimal_digest,
            minimal_staging_sha256=minimal_staging,
            source_lifecycle_evidence=source_ref,
            trust_store=trust_store,
        )
        preflight_path = transfer_use_preflight_path(root, report_id)
        preflight_written = _write_once(preflight_path, expected_preflight)
        preflight = _read_canonical(preflight_path)
        preflight_ref = _validate_preflight_payload(
            preflight,
            root=root,
            report_id=report_id,
            expected=expected_preflight,
            trust_store=trust_store,
        )

        transition_performed = False
        if current_state == "MINIMAL_MECHANISM_DELTA":
            if stable_hash(lifecycle) != minimal_digest:
                raise _block("minimal_lifecycle_changed")
            _run_lifecycle_transition(
                root=root,
                report_id=report_id,
                target_state=evidence["target_state"],
                evidence_ref=preflight_ref,
                expected_parent_sha256=minimal_digest,
                trust_root=trust_root.expanduser().resolve(strict=True),
                installation_id=installation_id,
            )
            transition_performed = True
            lifecycle = _load_lifecycle(root, report_id)
        _minimal_lifecycle(
            lifecycle,
            expected_minimal_lifecycle_sha256=minimal_digest,
        )
        _target_transition(
            lifecycle=lifecycle,
            minimal_index=minimal_index,
            target_state=evidence["target_state"],
            preflight_ref=preflight_ref,
        )

        transfer_materialized = False
        use_materialized = False
        staging = _load_staging(root, report_id)
        staging_events, _ = _staging_prefix(
            staging,
            report_id=report_id,
            expected_staging_content_sha256=minimal_staging,
        )
        lifecycle_parent = _lifecycle_parent_sha256(lifecycle)
        if not isinstance(lifecycle_parent, str):
            raise _block("target_lifecycle_parent")
        if len(staging_events) == 2:
            result = materialize_evo_v2_stage(
                workspace_root=root,
                report_id=report_id,
                stage=STAGE_ADMIT_TRANSFER,
                expected_lifecycle_parent_sha256=lifecycle_parent,
                expected_lifecycle_content_sha256=lifecycle["content_sha256"],
                expected_staging_content_sha256=staging["content_sha256"],
                experience_transfer_bundle=evidence["transfer"],
            )
            transfer_materialized = not result.get("idempotent_replay")
            staging = _load_staging(root, report_id)
            staging_events, _ = _staging_prefix(
                staging,
                report_id=report_id,
                expected_staging_content_sha256=minimal_staging,
            )
        if len(staging_events) == 3:
            result = materialize_evo_v2_stage(
                workspace_root=root,
                report_id=report_id,
                stage=STAGE_RECORD_USE,
                expected_lifecycle_parent_sha256=lifecycle_parent,
                expected_lifecycle_content_sha256=lifecycle["content_sha256"],
                expected_staging_content_sha256=staging["content_sha256"],
                transfer_use_receipt=evidence["receipt"],
            )
            use_materialized = not result.get("idempotent_replay")
            staging = _load_staging(root, report_id)
            staging_events, _ = _staging_prefix(
                staging,
                report_id=report_id,
                expected_staging_content_sha256=minimal_staging,
            )
        if len(staging_events) != 4:
            raise _block("four_staging_events_required")
        canonical_paths = evo_v2_paths(root, report_id)
        if (
            _read_canonical(canonical_paths["experience_transfer_bundle"])
            != evidence["transfer"]
            or _read_canonical(canonical_paths["transfer_use_receipt"])
            != evidence["receipt"]
        ):
            raise _block("canonical_core_readback")

        private_ref: dict[str, Any] | None = None
        private_admitted = False
        addendum_materialized = False
        if evidence["memory_state"] == "ADMISSIBLE_MEMORY_FOUND":
            assert admissions_root is not None
            _admission, private_ref = _admit_positive_transfer(
                root=root,
                evidence=evidence,
                admissions_root=admissions_root,
                trust_store=trust_store,
            )
            private_admitted = True
            addendum_result = materialize_evo_execution_addendum(
                workspace_root=root,
                report_id=report_id,
                transfer_bundle=evidence["transfer"],
                transfer_use_receipt=evidence["receipt"],
                change_receipt=evidence["change_receipt"],
                change_receipt_ref=evidence["change_receipt_ref"],
                private_admission_ref=private_ref,
                execution_tests=evidence["execution_tests"],
                execution_target=evidence["execution_target"],
                trust_store=trust_store,
                admissions_root=Path(admissions_root).expanduser().resolve(strict=True),
                repository_root=Path(__file__).resolve().parents[1],
            )
            if (
                addendum_result.get("verdict") != "PASS"
                or addendum_result.get("status") != ADDENDUM_STATUS
                or addendum_result.get("execution_completed") is not False
            ):
                raise _block("execution_addendum_materialization_result")
            evidence["execution_addendum"] = addendum_result["payload"]
            evidence["execution_addendum_ref"] = addendum_result["ref"]
            addendum_materialized = addendum_result["written"] is True
        else:
            addendum_path = execution_addendum_path(root, report_id)
            if addendum_path.exists() or addendum_path.is_symlink():
                raise _block("cold_start_execution_addendum_forbidden")

        final = _final_payload(
            root=root,
            report_id=report_id,
            evidence=evidence,
            minimal_lifecycle_sha256=minimal_digest,
            minimal_staging_sha256=minimal_staging,
            preflight_ref=preflight_ref,
            lifecycle=lifecycle,
            staging=staging,
            private_admission_ref=private_ref,
            trust_store=trust_store,
        )
        final_written = _write_once(report_path, final)
        validation = validate_evo_v2_transfer_use_orchestration(
            workspace_root=root,
            report_id=report_id,
            expected_minimal_lifecycle_sha256=minimal_digest,
            expected_staging_content_sha256=minimal_staging,
            trust_root=trust_root,
            installation_id=installation_id,
            admissions_root=admissions_root,
        )
        any_action = any(
            (
                preflight_written,
                transition_performed,
                transfer_materialized,
                use_materialized,
                addendum_materialized,
                final_written,
            )
        )
        return {
            **validation,
            "status": "ORCHESTRATED" if any_action else "IDEMPOTENT_REPLAY",
            "actions": {
                "preflight_materialized": preflight_written,
                "host_lifecycle_transition_performed": transition_performed,
                "transfer_materialized": transfer_materialized,
                "use_materialized": use_materialized,
                "private_admission_verified": private_admitted,
                "execution_addendum_materialized": addendum_materialized,
                "orchestration_materialized": final_written,
            },
        }


__all__ = [
    "BLOCK_TRANSFER_USE_ORCHESTRATION",
    "ORCHESTRATION_VERSION",
    "PREFLIGHT_VERSION",
    "TransferUseOrchestrationError",
    "orchestrate_evo_v2_transfer_use",
    "transfer_use_orchestration_path",
    "transfer_use_preflight_path",
    "validate_evo_v2_transfer_use_orchestration",
]
