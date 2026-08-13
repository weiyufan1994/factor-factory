from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

from factor_factory.evo_child_authoring import (
    _adapter_completion_reasons,
    _deserialize_authoring_invocation,
    _deserialize_authoring_outcome,
    _load_json_file,
    _private_child_scope,
    _private_write_once,
    _safe_private_root,
    _serialize_authoring_invocation,
    _serialize_authoring_outcome,
    _termination_proof_reasons,
    _write_public_once,
    evo_child_authoring_admission_path,
    validate_evo_child_authoring_admission,
)
from factor_factory.evo_v2 import canonical_json_bytes, sha256_file
from factor_factory.research_conjecture import workspace_runtime_trust_manifest
from factor_factory.research_org.contracts import PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION
from factor_factory.research_org.runtime import (
    ResearchOrgSessionInvocation,
    ResearchOrgSessionOutcome,
)
from factor_factory.research_org.runtime_trust import (
    load_runtime_trust_store,
    verify_signed_receipt_with_manifest,
)


ASSURANCE_VERSION = "factorforge_evo_revision_child_assurance_v1"
REVIEW_VERSION = "factorforge_evo_child_independent_review_v1"
ROLE_ID = "evo_child_independent_reviewer"
STATUS = "REVISION_CHILD_FORMAL_ASSURANCE"
BLOCK = "BLOCK_FACTORFORGE_EVO_CHILD_ASSURANCE_INVALID"
_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}\Z")


class EvoChildAssuranceError(ValueError):
    pass


class Runner(Protocol):
    def run_research_org_session(
        self, invocation: ResearchOrgSessionInvocation
    ) -> ResearchOrgSessionOutcome: ...

    def reconcile_research_org_session(
        self, runtime_instance_id: str
    ) -> Mapping[str, Any]: ...


def _fail(reason: str) -> EvoChildAssuranceError:
    return EvoChildAssuranceError(f"{BLOCK}:{reason}")


def assurance_path(root: Path | str, child_report_id: str) -> Path:
    return (
        Path(root)
        / "objects/research_protocol"
        / f"evo_child_research_org_assurance__{child_report_id}.json"
    )


def _ref(root: Path, path: Path) -> dict[str, str]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha256_file(path),
    }


def _write_once(root: Path, path: Path, raw: bytes) -> None:
    try:
        _write_public_once(root, path, raw)
    except (OSError, ValueError) as exc:
        raise _fail(f"immutable_conflict:{path.name}") from exc


@contextmanager
def _assurance_lock(private: Path, child_report_id: str):
    if _SAFE.fullmatch(child_report_id) is None:
        raise _fail("assurance_lock_child")
    lock_root = private / ".evo-child-locks"
    try:
        lock_root.mkdir(mode=0o700, exist_ok=True)
        metadata = lock_root.lstat()
    except OSError as exc:
        raise _fail("assurance_lock") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_mode & 0o077
    ):
        raise _fail("assurance_lock")
    lock_path = lock_root / (
        "assurance__"
        + hashlib.sha256(
            canonical_json_bytes(
                {
                    "scope": "evo_child_assurance_lock_v1",
                    "child_report_id": child_report_id,
                }
            )
        ).hexdigest()[:32]
        + ".lock"
    )
    descriptor = os.open(
        lock_path,
        os.O_CREAT
        | os.O_RDWR
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise _fail("assurance_lock")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _review_attempt_digest(
    *,
    parent_report_id: str,
    child_report_id: str,
    authoring_admission_ref: Mapping[str, Any],
    generation: int,
) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            {
                "scope": "evo_child_assurance_attempt_v1",
                "parent_report_id": parent_report_id,
                "child_report_id": child_report_id,
                "authoring_admission_ref": dict(authoring_admission_ref),
                "generation": generation,
            }
        )
    ).hexdigest()


def build_evo_child_review_prompt(invocation: ResearchOrgSessionInvocation) -> str:
    return f"""# Independent EVO revision-child review

You are the independent reviewer, not the child semantic author and not the
parent Council. Read only the staged task at
{invocation.context_root / 'identity/evo_child_review_task.json'} and its
referenced staged files. Determine whether the admitted child semantics are an
exact, non-self-authorizing implementation of the approved revision while
preserving frozen thresholds, IS/OOS allocation, falsifiers and parent policy.

Write exactly one JSON object to {invocation.private_output_path}:
{{
  "contract_version": "{PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION}",
  "status": "PASS|BLOCK",
  "public_research_record": {{
    "version": "{REVIEW_VERSION}",
    "child_report_id": "{invocation.identity['report_id']}",
    "verdict": "PASS|BLOCK",
    "checks": {{
      "approved_revision_exact": true,
      "economic_backprojection_preserved": true,
      "frozen_evaluation_preserved": true,
      "fresh_oos_unobserved": true,
      "self_authorization_absent": true
    }}
  }}
}}
All five checks must be evidence-based. Do not execute the factor, inspect OOS,
change any workspace artifact, issue a factor verdict, or mutate methodology.
"""


def _review_material(
    *,
    root: Path,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
) -> dict[str, Any]:
    admission = validate_evo_child_authoring_admission(
        workspace_root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        agent_authoring_admission=evo_child_authoring_admission_path(
            root, child_report_id
        ),
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
    )
    author_ref = admission["admission"]["semantic_bundle_ref"]
    author_admission_ref = _ref(root, Path(admission["admission_path"]))
    author_path = root / str(author_ref["path"])
    source_refs: list[Mapping[str, Any]] = [
        _ref(root, Path(admission["admission_path"])),
        _ref(root, Path(admission["task_path"])),
    ]
    author_task = admission["task"]
    for group_name in (
        "revision_evidence_refs",
        "parent_frozen_contract_refs",
    ):
        group = author_task.get(group_name)
        if isinstance(group, Mapping):
            source_refs.extend(
                reference
                for reference in group.values()
                if isinstance(reference, Mapping)
            )
    staged_refs: list[dict[str, str]] = []
    for reference in source_refs:
        raw_path = reference.get("path")
        expected_sha = reference.get("sha256")
        if not isinstance(raw_path, str) or not isinstance(expected_sha, str):
            raise _fail("review_source_ref")
        source = root / raw_path
        if (
            source.is_symlink()
            or not source.is_file()
            or sha256_file(source) != expected_sha
        ):
            raise _fail("review_source_changed")
        staged_refs.append({"path": raw_path, "sha256": expected_sha})
    task = {
        "version": "factorforge_evo_child_independent_review_task_v1",
        "identity": {
            "factor_id": admission["admission"]["identity"]["factor_id"],
            "research_id": admission["admission"]["identity"]["research_id"],
            "report_id": child_report_id,
        },
        "parent_report_id": parent_report_id,
        "authoring_admission_ref": author_admission_ref,
        "semantic_bundle_sha256": sha256_file(author_path),
        "staged_evidence_refs": staged_refs,
        "forbidden": [
            "factor_execution",
            "oos_access",
            "workspace_write",
            "verdict",
        ],
    }
    task["task_sha256"] = hashlib.sha256(
        canonical_json_bytes(task)
    ).hexdigest()
    return {
        "admission": admission,
        "author_path": author_path,
        "authoring_admission_ref": author_admission_ref,
        "source_refs": staged_refs,
        "task": task,
    }


def _prepare_review_invocation(
    *,
    root: Path,
    tree: Path,
    private: Path,
    material: Mapping[str, Any],
    generation: int,
    timeout_seconds: int,
) -> ResearchOrgSessionInvocation:
    task = material["task"]
    token = _review_attempt_digest(
        parent_report_id=str(task["parent_report_id"]),
        child_report_id=str(task["identity"]["report_id"]),
        authoring_admission_ref=task["authoring_admission_ref"],
        generation=generation,
    )
    session = private / f"evo-child-assurance-{token[:32]}"
    context = session / "context"
    result_dir = session / "output"
    context.mkdir(parents=True, mode=0o700, exist_ok=True)
    result_dir.mkdir(mode=0o700, exist_ok=True)
    staged = context / "objects/evo_child_semantic_bundle.json"
    _private_write_once(staged, Path(material["author_path"]).read_bytes())
    for reference in material["source_refs"]:
        source = root / str(reference["path"])
        if (
            source.is_symlink()
            or not source.is_file()
            or sha256_file(source) != reference["sha256"]
        ):
            raise _fail("review_source_changed")
        _private_write_once(
            context / str(reference["path"]), source.read_bytes()
        )
    task_path = context / "identity/evo_child_review_task.json"
    _private_write_once(task_path, canonical_json_bytes(task))
    context_hash = hashlib.sha256(
        canonical_json_bytes(
            {
                "task": sha256_file(task_path),
                "semantic": sha256_file(staged),
                "evidence": material["source_refs"],
            }
        )
    ).hexdigest()
    return ResearchOrgSessionInvocation(
        identity=dict(task["identity"]),
        role_id=ROLE_ID,
        task_id=f"evo_child_review_{token[:20]}",
        task_sha256=str(task["task_sha256"]),
        attempt_id=f"attempt_evo_child_review_{token[:20]}",
        attempt_number=generation,
        session_id=f"session_{token[:32]}",
        runtime_instance_id=f"fforg-evo-child-review-{token[:16]}",
        worktree=tree,
        workspace=root,
        private_attempt_root=session,
        context_root=context,
        private_output_path=result_dir / "agent_result.json",
        cancel_request_path=session / "cancel.json",
        context_manifest_sha256=context_hash,
        required_skills=("factor-forge-ultimate",),
        timeout_seconds=timeout_seconds,
        runtime_id=f"runtime_evo_child_review_{token[:20]}",
        plan_sha256=sha256_file(Path(material["author_path"])),
        scheduler_epoch=generation,
        dispatch_event_seq=generation,
        idempotency_key=hashlib.sha256(
            canonical_json_bytes(
                {
                    "task_sha256": task["task_sha256"],
                    "generation": generation,
                }
            )
        ).hexdigest(),
        adapter_challenge=hashlib.sha256(
            canonical_json_bytes(
                {
                    "scope": "evo_child_assurance_challenge_v1",
                    "attempt_sha256": token,
                }
            )
        ).hexdigest(),
        dependency_admissions=(
            dict(material["authoring_admission_ref"]),
        ),
        parent_session_uid=None,
    )


def _admit_review_completion(
    *,
    root: Path,
    output: Path,
    material: Mapping[str, Any],
    invocation: ResearchOrgSessionInvocation,
    outcome: ResearchOrgSessionOutcome,
    manifest: Mapping[str, Any],
    store: Any,
    installation_id: str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
) -> dict[str, Any]:
    task = material["task"]
    if (
        invocation.identity != task["identity"]
        or invocation.role_id != ROLE_ID
        or invocation.task_sha256 != task["task_sha256"]
        or invocation.parent_session_uid is not None
        or invocation.session_id
        == material["admission"]["admission"]["runtime_attestation"][
            "session_id"
        ]
    ):
        raise _fail("review_invocation_binding")
    try:
        raw = invocation.private_output_path.read_bytes()
        private_payload = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _fail("independent_review_output") from exc
    review = (
        private_payload.get("public_research_record")
        if isinstance(private_payload, Mapping)
        else None
    )
    checks = review.get("checks") if isinstance(review, Mapping) else None
    expected_checks = {
        "approved_revision_exact",
        "economic_backprojection_preserved",
        "frozen_evaluation_preserved",
        "fresh_oos_unobserved",
        "self_authorization_absent",
    }
    reasons = _adapter_completion_reasons(
        receipt=outcome.adapter_receipt,
        invocation=invocation,
        outcome=outcome,
        trust_manifest=manifest,
        installation_id=installation_id,
        output_sha256=hashlib.sha256(raw).hexdigest(),
        output_size_bytes=len(raw),
    )
    if (
        reasons
        or outcome.isolation_class != "container_staged_context"
        or outcome.transport != "openclaw_disposable_container"
        or not isinstance(private_payload, Mapping)
        or set(private_payload)
        != {"contract_version", "status", "public_research_record"}
        or private_payload.get("contract_version")
        != PRIVATE_AGENT_OUTPUT_CONTRACT_VERSION
        or private_payload.get("status") != "PASS"
        or not isinstance(review, Mapping)
        or set(review) != {"version", "child_report_id", "verdict", "checks"}
        or review.get("version") != REVIEW_VERSION
        or review.get("child_report_id") != child_report_id
        or review.get("verdict") != "PASS"
        or not isinstance(checks, Mapping)
        or set(checks) != expected_checks
        or any(value is not True for value in checks.values())
    ):
        raise _fail("independent_review_failed")
    core = {
        "receipt_type": "EVO_REVISION_CHILD_ASSURANCE",
        "assurance_version": ASSURANCE_VERSION,
        "status": STATUS,
        "parent_report_id": parent_report_id,
        "child_report_id": child_report_id,
        "trust_manifest_sha256": expected_host_trust_manifest_sha256,
        "authoring_admission_ref": dict(
            material["authoring_admission_ref"]
        ),
        "independent_review": dict(review),
        "review_adapter_receipt": dict(outcome.adapter_receipt or {}),
        "review_runtime": {
            "role_id": ROLE_ID,
            "session_id": outcome.session_id,
            "isolation_class": outcome.isolation_class,
            "transport": outcome.transport,
            "termination_confirmed": (
                (outcome.adapter_receipt or {}).get("outcome", {}).get(
                    "termination_confirmed"
                )
            ),
            "adapter_receipt_id": outcome.adapter_receipt["receipt_id"],
        },
        "assurance_scope": {
            "kind": "REVISION_CHILD_NOT_FULL_SEVEN_ROLE_RESEARCH_ORG",
            "parent_council_and_human_approval_required": True,
            "isolated_child_author_required": True,
            "independent_child_reviewer_required": True,
            "factor_execution_allowed": True,
            "oos_release_allowed": False,
            "factor_verdict": "NOT_ISSUED",
        },
    }
    signed = store.sign("host_admission", core)
    _write_once(root, output, canonical_json_bytes(signed))
    return validate_evo_child_assurance(
        workspace_root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        assurance=output,
        expected_host_trust_manifest_sha256=(
            expected_host_trust_manifest_sha256
        ),
    )


def materialize_evo_child_assurance(
    *,
    runner: Runner,
    workspace_root: Path | str,
    worktree: Path | str,
    private_root: Path | str,
    trust_root: Path | str,
    installation_id: str,
    parent_report_id: str,
    child_report_id: str,
    expected_host_trust_manifest_sha256: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    root = Path(workspace_root).resolve(strict=True)
    tree = Path(worktree).resolve(strict=True)
    manifest = workspace_runtime_trust_manifest(root, report_id=parent_report_id)
    store = load_runtime_trust_store(Path(trust_root), installation_id=installation_id)
    if manifest != store.public_manifest:
        raise _fail("host_trust_manifest")
    private = _safe_private_root(
        Path(private_root), workspace=root, worktree=tree
    )
    try:
        private = _private_child_scope(
            private,
            namespace="assurance",
            child_report_id=child_report_id,
        )
    except ValueError as exc:
        raise _fail("private_child_scope") from exc
    output = assurance_path(root, child_report_id)
    with _assurance_lock(private, child_report_id):
        if output.exists() or output.is_symlink():
            if output.is_symlink() or not output.is_file():
                raise _fail("assurance_output_unsafe")
            return validate_evo_child_assurance(
                workspace_root=root,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                assurance=output,
                expected_host_trust_manifest_sha256=(
                    expected_host_trust_manifest_sha256
                ),
            )
        material = _review_material(
            root=root,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            expected_host_trust_manifest_sha256=(
                expected_host_trust_manifest_sha256
            ),
        )
        completion_journals = sorted(
            private.glob(
                "evo-child-assurance-*/completion_journal.json"
            )
        )
        if completion_journals:
            if len(completion_journals) != 1:
                raise _fail("completion_journal_count")
            completion = _load_json_file(
                completion_journals[0],
                label="assurance_completion_journal",
                canonical=True,
            )
            invocation_raw = completion.get("invocation")
            outcome_raw = completion.get("outcome")
            if (
                store.verify(completion, expected_issuer="host_admission")
                or completion.get("receipt_type")
                != "EVO_CHILD_ASSURANCE_COMPLETION_JOURNAL"
                or completion.get("parent_report_id") != parent_report_id
                or completion.get("child_report_id") != child_report_id
                or completion.get("task_sha256")
                != material["task"]["task_sha256"]
                or not isinstance(invocation_raw, Mapping)
                or not isinstance(outcome_raw, Mapping)
            ):
                raise _fail("completion_journal_invalid")
            try:
                invocation = _deserialize_authoring_invocation(
                    dict(invocation_raw),
                    root=root,
                    tree=tree,
                    private=private,
                )
                outcome = _deserialize_authoring_outcome(dict(outcome_raw))
            except (OSError, ValueError) as exc:
                raise _fail("completion_journal_replay") from exc
            return _admit_review_completion(
                root=root,
                output=output,
                material=material,
                invocation=invocation,
                outcome=outcome,
                manifest=manifest,
                store=store,
                installation_id=installation_id,
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                expected_host_trust_manifest_sha256=(
                    expected_host_trust_manifest_sha256
                ),
            )
        launch_journals = sorted(
            private.glob("evo-child-assurance-*/launch_journal.json")
        )
        launches: list[
            tuple[int, Path, dict[str, Any], ResearchOrgSessionInvocation]
        ] = []
        for launch_path in launch_journals:
            launch = _load_json_file(
                launch_path,
                label="assurance_launch_journal",
                canonical=True,
            )
            generation_raw = launch.get("generation")
            invocation_raw = launch.get("invocation")
            if (
                store.verify(launch, expected_issuer="host_admission")
                or launch.get("receipt_type")
                != "EVO_CHILD_ASSURANCE_LAUNCH_JOURNAL"
                or launch.get("parent_report_id") != parent_report_id
                or launch.get("child_report_id") != child_report_id
                or launch.get("task_sha256")
                != material["task"]["task_sha256"]
                or isinstance(generation_raw, bool)
                or not isinstance(generation_raw, int)
                or not 1 <= generation_raw <= 32
                or not isinstance(invocation_raw, Mapping)
            ):
                raise _fail("launch_journal_invalid")
            try:
                invocation = _deserialize_authoring_invocation(
                    dict(invocation_raw),
                    root=root,
                    tree=tree,
                    private=private,
                    require_output=False,
                )
            except (OSError, ValueError) as exc:
                raise _fail("launch_journal_invocation") from exc
            expected_attempt = _review_attempt_digest(
                parent_report_id=parent_report_id,
                child_report_id=child_report_id,
                authoring_admission_ref=(
                    material["authoring_admission_ref"]
                ),
                generation=generation_raw,
            )
            if (
                launch.get("attempt_seed_sha256") != expected_attempt
                or invocation.attempt_number != generation_raw
                or invocation.scheduler_epoch != generation_raw
                or invocation.dispatch_event_seq != generation_raw
                or invocation.private_attempt_root
                != private / f"evo-child-assurance-{expected_attempt[:32]}"
                or launch_path.parent != invocation.private_attempt_root
            ):
                raise _fail("launch_journal_attempt")
            launches.append(
                (generation_raw, launch_path, launch, invocation)
            )
        launches.sort(key=lambda item: item[0])
        if [item[0] for item in launches] != list(
            range(1, len(launches) + 1)
        ):
            raise _fail("launch_generation_sequence")
        for index, (generation_raw, launch_path, launch, invocation) in enumerate(
            launches
        ):
            abandoned_path = launch_path.parent / "abandoned_journal.json"
            retry_path = (
                launch_path.parent / "retry_authorized_journal.json"
            )
            abandoned = (
                _load_json_file(
                    abandoned_path,
                    label="assurance_abandoned_journal",
                    canonical=True,
                )
                if abandoned_path.exists() or abandoned_path.is_symlink()
                else None
            )
            retry = (
                _load_json_file(
                    retry_path,
                    label="assurance_retry_journal",
                    canonical=True,
                )
                if retry_path.exists() or retry_path.is_symlink()
                else None
            )
            if retry is not None and abandoned is None:
                raise _fail("retry_without_abandonment")
            if abandoned is None:
                if index != len(launches) - 1:
                    raise _fail("unclosed_historical_launch")
                reconcile = getattr(
                    runner, "reconcile_research_org_session", None
                )
                if not callable(reconcile):
                    raise _fail("targeted_reconcile_unavailable")
                try:
                    termination_proof = reconcile(
                        invocation.runtime_instance_id
                    )
                except Exception as exc:  # noqa: BLE001
                    raise _fail(
                        f"targeted_reconcile_failed:{type(exc).__name__}"
                    ) from exc
                proof_reasons = _termination_proof_reasons(
                    termination_proof,
                    runtime_instance_id=invocation.runtime_instance_id,
                    trust_store=store,
                    installation_id=installation_id,
                )
                if proof_reasons:
                    raise _fail(
                        "targeted_reconcile:" + ",".join(proof_reasons)
                    )
                abandoned = store.sign(
                    "host_admission",
                    {
                        "receipt_type": "EVO_CHILD_ASSURANCE_ABANDONED",
                        "parent_report_id": parent_report_id,
                        "child_report_id": child_report_id,
                        "generation": generation_raw,
                        "launch_receipt_id": launch["receipt_id"],
                        "runtime_instance_id": (
                            invocation.runtime_instance_id
                        ),
                        "termination_proof": dict(termination_proof),
                        "authority": {
                            "launch_abandoned": True,
                            "retry_authorized": False,
                            "factor_verdict": "NOT_ISSUED",
                        },
                    },
                )
                _private_write_once(
                    abandoned_path, canonical_json_bytes(abandoned)
                )
            proof_reasons = _termination_proof_reasons(
                abandoned.get("termination_proof"),
                runtime_instance_id=invocation.runtime_instance_id,
                trust_store=store,
                installation_id=installation_id,
            )
            if (
                store.verify(abandoned, expected_issuer="host_admission")
                or abandoned.get("receipt_type")
                != "EVO_CHILD_ASSURANCE_ABANDONED"
                or abandoned.get("parent_report_id") != parent_report_id
                or abandoned.get("child_report_id") != child_report_id
                or abandoned.get("generation") != generation_raw
                or abandoned.get("launch_receipt_id")
                != launch.get("receipt_id")
                or abandoned.get("runtime_instance_id")
                != invocation.runtime_instance_id
                or abandoned.get("authority")
                != {
                    "launch_abandoned": True,
                    "retry_authorized": False,
                    "factor_verdict": "NOT_ISSUED",
                }
                or proof_reasons
            ):
                raise _fail("abandoned_journal_invalid")
            if retry is None:
                retry = store.sign(
                    "host_admission",
                    {
                        "receipt_type": (
                            "EVO_CHILD_ASSURANCE_RETRY_AUTHORIZED"
                        ),
                        "parent_report_id": parent_report_id,
                        "child_report_id": child_report_id,
                        "abandoned_receipt_id": abandoned["receipt_id"],
                        "prior_generation": generation_raw,
                        "next_generation": generation_raw + 1,
                        "authority": {
                            "new_review_attempt_allowed": True,
                            "factor_verdict": "NOT_ISSUED",
                        },
                    },
                )
                _private_write_once(
                    retry_path, canonical_json_bytes(retry)
                )
            if (
                store.verify(retry, expected_issuer="host_admission")
                or retry.get("receipt_type")
                != "EVO_CHILD_ASSURANCE_RETRY_AUTHORIZED"
                or retry.get("parent_report_id") != parent_report_id
                or retry.get("child_report_id") != child_report_id
                or retry.get("abandoned_receipt_id")
                != abandoned.get("receipt_id")
                or retry.get("prior_generation") != generation_raw
                or retry.get("next_generation") != generation_raw + 1
                or retry.get("authority")
                != {
                    "new_review_attempt_allowed": True,
                    "factor_verdict": "NOT_ISSUED",
                }
            ):
                raise _fail("retry_authorization_invalid")
        generation = len(launches) + 1
        if generation > 32:
            raise _fail("assurance_retry_limit")
        invocation = _prepare_review_invocation(
            root=root,
            tree=tree,
            private=private,
            material=material,
            generation=generation,
            timeout_seconds=timeout_seconds,
        )
        attempt_seed = _review_attempt_digest(
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            authoring_admission_ref=material["authoring_admission_ref"],
            generation=generation,
        )
        launch = store.sign(
            "host_admission",
            {
                "receipt_type": "EVO_CHILD_ASSURANCE_LAUNCH_JOURNAL",
                "parent_report_id": parent_report_id,
                "child_report_id": child_report_id,
                "generation": generation,
                "attempt_seed_sha256": attempt_seed,
                "task_sha256": material["task"]["task_sha256"],
                "invocation": _serialize_authoring_invocation(invocation),
                "authority": {
                    "review_inflight_only": True,
                    "rerun_after_unknown_crash_allowed": False,
                    "factor_verdict": "NOT_ISSUED",
                },
            },
        )
        _private_write_once(
            invocation.private_attempt_root / "launch_journal.json",
            canonical_json_bytes(launch),
        )
        outcome = runner.run_research_org_session(invocation)
        completion = store.sign(
            "host_admission",
            {
                "receipt_type": (
                    "EVO_CHILD_ASSURANCE_COMPLETION_JOURNAL"
                ),
                "parent_report_id": parent_report_id,
                "child_report_id": child_report_id,
                "generation": generation,
                "task_sha256": material["task"]["task_sha256"],
                "invocation": _serialize_authoring_invocation(invocation),
                "outcome": _serialize_authoring_outcome(outcome),
                "authority": {
                    "host_observed_review_completion": True,
                    "public_assurance_pending": True,
                    "factor_verdict": "NOT_ISSUED",
                },
            },
        )
        _private_write_once(
            invocation.private_attempt_root / "completion_journal.json",
            canonical_json_bytes(completion),
        )
        return _admit_review_completion(
            root=root,
            output=output,
            material=material,
            invocation=invocation,
            outcome=outcome,
            manifest=manifest,
            store=store,
            installation_id=installation_id,
            parent_report_id=parent_report_id,
            child_report_id=child_report_id,
            expected_host_trust_manifest_sha256=(
                expected_host_trust_manifest_sha256
            ),
        )


def validate_evo_child_assurance(
    *,
    workspace_root: Path | str,
    parent_report_id: str,
    child_report_id: str,
    assurance: Path | str,
    expected_host_trust_manifest_sha256: str,
) -> dict[str, Any]:
    root = Path(workspace_root).resolve(strict=True)
    path = Path(assurance).resolve(strict=True)
    if path != assurance_path(root, child_report_id).resolve(strict=False):
        raise _fail("assurance_path")
    payload = json.loads(path.read_text(encoding="utf-8"))
    manifest = workspace_runtime_trust_manifest(root, report_id=parent_report_id)
    reasons = verify_signed_receipt_with_manifest(
        payload, trust_manifest=manifest, expected_issuer="host_admission"
    )
    adapter_receipt = payload.get("review_adapter_receipt")
    reasons.extend(
        verify_signed_receipt_with_manifest(
            adapter_receipt,
            trust_manifest=manifest,
            expected_issuer="runtime_adapter",
        )
    )
    authoring = validate_evo_child_authoring_admission(
        workspace_root=root,
        parent_report_id=parent_report_id,
        child_report_id=child_report_id,
        agent_authoring_admission=evo_child_authoring_admission_path(
            root, child_report_id
        ),
        expected_host_trust_manifest_sha256=expected_host_trust_manifest_sha256,
    )
    expected_checks = {
        "approved_revision_exact": True,
        "economic_backprojection_preserved": True,
        "frozen_evaluation_preserved": True,
        "fresh_oos_unobserved": True,
        "self_authorization_absent": True,
    }
    expected_review = {
        "version": REVIEW_VERSION,
        "child_report_id": child_report_id,
        "verdict": "PASS",
        "checks": expected_checks,
    }
    expected_scope = {
        "kind": "REVISION_CHILD_NOT_FULL_SEVEN_ROLE_RESEARCH_ORG",
        "parent_council_and_human_approval_required": True,
        "isolated_child_author_required": True,
        "independent_child_reviewer_required": True,
        "factor_execution_allowed": True,
        "oos_release_allowed": False,
        "factor_verdict": "NOT_ISSUED",
    }
    expected_top_level = {
        "contract_version",
        "issuer",
        "receipt_id",
        "signature",
        "receipt_type",
        "assurance_version",
        "status",
        "parent_report_id",
        "child_report_id",
        "trust_manifest_sha256",
        "authoring_admission_ref",
        "independent_review",
        "review_adapter_receipt",
        "review_runtime",
        "assurance_scope",
    }
    runtime = payload.get("review_runtime")
    expected_runtime_fields = {
        "role_id",
        "session_id",
        "isolation_class",
        "transport",
        "termination_confirmed",
        "adapter_receipt_id",
    }
    if (
        reasons
        or set(payload) != expected_top_level
        or payload.get("receipt_type") != "EVO_REVISION_CHILD_ASSURANCE"
        or payload.get("assurance_version") != ASSURANCE_VERSION
        or payload.get("status") != STATUS
        or payload.get("parent_report_id") != parent_report_id
        or payload.get("child_report_id") != child_report_id
        or payload.get("trust_manifest_sha256") != expected_host_trust_manifest_sha256
        or payload.get("authoring_admission_ref")
        != _ref(root, Path(authoring["admission_path"]))
        or not isinstance(adapter_receipt, Mapping)
        or payload.get("independent_review") != expected_review
        or not isinstance(runtime, Mapping)
        or set(runtime) != expected_runtime_fields
        or runtime.get("adapter_receipt_id")
        != adapter_receipt.get("receipt_id")
        or runtime.get("role_id") != ROLE_ID
        or runtime.get("isolation_class") != "container_staged_context"
        or runtime.get("transport") != "openclaw_disposable_container"
        or runtime.get("termination_confirmed") is not True
        or not isinstance(runtime.get("session_id"), str)
        or not runtime.get("session_id")
        or payload.get("assurance_scope") != expected_scope
    ):
        raise _fail("assurance_exact_replay")
    return {
        "verdict": "PASS",
        "status": STATUS,
        "assurance": payload,
        "assurance_path": path,
        "assurance_ref": _ref(root, path),
    }


__all__ = [
    "ASSURANCE_VERSION",
    "BLOCK",
    "ROLE_ID",
    "STATUS",
    "assurance_path",
    "build_evo_child_review_prompt",
    "materialize_evo_child_assurance",
    "validate_evo_child_assurance",
]
