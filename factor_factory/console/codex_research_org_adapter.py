from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from factor_factory.research_evidence import sha256_file
from factor_factory.research_org.contracts import stable_json_hash
from factor_factory.research_org.runtime import (
    ResearchOrgSessionInvocation,
    ResearchOrgSessionOutcome,
    build_research_org_session_prompt,
)
from factor_factory.research_org.runtime_trust import ensure_runtime_trust_store


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class CodexResearchOrgAdapter:
    """Host-signed Codex runner for non-formal structural/developer workflows."""

    def __init__(self, *, trust_root: Path, installation_id: str, model: str = "gpt-5.6-sol") -> None:
        self.trust_root = trust_root
        self.installation_id = installation_id
        self.model = model
        self._active: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.Lock()

    def _context_packet(self, root: Path) -> str:
        chunks: list[str] = []
        total = 0
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            payload = path.read_bytes()
            total += len(payload)
            if total > 16 * 1024 * 1024:
                raise RuntimeError("research organization context exceeds 16 MiB")
            text = payload.decode("utf-8")
            relative = path.relative_to(root).as_posix()
            chunks.append(f"\n--- BEGIN STAGED FILE {relative} ---\n{text}\n--- END STAGED FILE {relative} ---")
        return "".join(chunks)

    def _skill_packet(self, invocation: ResearchOrgSessionInvocation) -> str:
        chunks: list[str] = []
        for skill in invocation.required_skills:
            path = invocation.worktree / "skills" / skill / "SKILL.md"
            if not path.is_file() or path.is_symlink():
                raise RuntimeError(f"required role skill is missing: {skill}")
            skill_text = path.read_text(encoding="utf-8")
            chunks.append(
                f"\n--- BEGIN REQUIRED SKILL {skill}/SKILL.md ---\n"
                + skill_text
                + f"\n--- END REQUIRED SKILL {skill}/SKILL.md ---"
            )
            linked: set[Path] = set()
            for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", skill_text):
                if "://" in target or target.startswith("#"):
                    continue
                candidate = (path.parent / target).resolve(strict=False)
                try:
                    candidate.relative_to(path.parent.resolve(strict=True))
                except ValueError:
                    continue
                if candidate.is_file() and not candidate.is_symlink():
                    linked.add(candidate)
            for reference in sorted(linked):
                relative = reference.relative_to(path.parent).as_posix()
                chunks.append(
                    f"\n--- BEGIN REQUIRED SKILL REFERENCE {skill}/{relative} ---\n"
                    + reference.read_text(encoding="utf-8")
                    + f"\n--- END REQUIRED SKILL REFERENCE {skill}/{relative} ---"
                )
        return "".join(chunks)

    @staticmethod
    def _parse_final_json(text: str) -> dict[str, Any]:
        candidate = text.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", candidate, re.DOTALL)
        if fenced:
            candidate = fenced.group(1)
        value = json.loads(candidate)
        if not isinstance(value, dict):
            raise ValueError("Codex research result must be a JSON object")
        return value

    def _receipt(
        self,
        invocation: ResearchOrgSessionInvocation,
        *,
        started: str,
        finished: str,
        provider_hash: str,
        returncode: int,
        output_hash: str | None,
        output_size: int | None,
    ) -> dict[str, Any]:
        store = ensure_runtime_trust_store(
            self.trust_root, installation_id=self.installation_id
        )
        codex_binary = shutil.which("codex")
        if not codex_binary:
            raise RuntimeError("codex executable is unavailable")
        codex_digest = f"sha256:{sha256_file(Path(codex_binary).resolve(strict=True))}"
        return store.sign(
            "runtime_adapter",
            {
                "receipt_type": "COMPLETED" if returncode == 0 else "FAILED",
                "identity": {
                    **invocation.identity,
                    "runtime_id": invocation.runtime_id,
                    "task_id": invocation.task_id,
                    "role_id": invocation.role_id,
                    "attempt_id": invocation.attempt_id,
                    "attempt_no": invocation.attempt_number,
                },
                "ordering": {
                    "scheduler_epoch": invocation.scheduler_epoch,
                    "dispatch_event_seq": invocation.dispatch_event_seq,
                    "issued_at_utc": finished,
                    "started_at_utc": started,
                    "finished_at_utc": finished,
                },
                "bindings": {
                    "plan_sha256": invocation.plan_sha256,
                    "task_sha256": invocation.task_sha256,
                    "context_manifest_sha256": invocation.context_manifest_sha256,
                    "dependency_admissions": [dict(item) for item in invocation.dependency_admissions],
                    "idempotency_key": invocation.idempotency_key,
                    "adapter_challenge": invocation.adapter_challenge,
                },
                "session": {
                    "session_uid": invocation.session_id,
                    "runtime_handle_sha256": hashlib.sha256(invocation.runtime_instance_id.encode()).hexdigest(),
                    "provider_handle_sha256": provider_hash,
                    "adapter_id": self.installation_id,
                    "adapter_build_sha256": sha256_file(Path(__file__)),
                    # v1 names this compatibility field after the container
                    # runner. For a local Codex transport it binds the exact
                    # executable artifact instead of claiming a container.
                    "container_image_digest": codex_digest,
                    "isolation_profile_sha256": stable_json_hash(
                        {
                            "class": "codex_subagent_isolated",
                            "workspace_paths_exposed": False,
                            "staged_context_embedded_read_only": True,
                            "network_policy": "codex_host_policy",
                            "installation_id": self.installation_id,
                        }
                    ),
                    "runtime": {
                        "provider": "codex",
                        "model": self.model,
                        "transport": "codex_exec_ephemeral",
                        "isolation_class": "codex_subagent_isolated",
                        "owned_termination_supported": True,
                    },
                    "parent_session_uid": invocation.parent_session_uid,
                    "lease_epoch": invocation.scheduler_epoch,
                },
                "outcome": {
                    "returncode": returncode,
                    "cancelled": False,
                    "error_class": None if returncode == 0 else "BLOCK_AGENT_RUNTIME_FAILED",
                    "private_output_sha256": output_hash,
                    "private_output_size_bytes": output_size,
                    "termination_confirmed": True,
                },
            },
        )

    def run_research_org_session(self, invocation: ResearchOrgSessionInvocation) -> ResearchOrgSessionOutcome:
        started = _utc_now()
        agent_root = invocation.private_attempt_root / "codex_agent"
        agent_root.mkdir(parents=True, exist_ok=True)
        last_message = agent_root / "last_message.json"
        prompt = build_research_org_session_prompt(invocation)
        prompt += self._skill_packet(invocation)
        prompt += self._context_packet(invocation.context_root)
        prompt += (
            "\nThe staged files above are the complete read-only context. You cannot access host paths. "
            "Do not use tools or request more files. IMPORTANT TRANSPORT OVERRIDE: the runtime prompt's "
            "factorforge_agent_private_output_v1 template is the only outer object you return. If a Skill "
            "or its example shows factorforge_agent_result_v1, do not return that envelope: copy only its "
            "public_research_record value into the runtime template; the Host alone adds task_ref, identity, "
            "role_id, producer_mode, session_id, and result_sha256. Return that exact private-output JSON "
            "object as your entire final response, with no Markdown fence or commentary. The Host will materialize it."
        )
        if invocation.role_id == "knowledge_librarian":
            prompt += (
                " The frozen knowledge summary is non-cold-start when it contains nodes. In that case "
                "claims must be non-empty: include at least one exact source-text claim with its exact "
                "JSON source_path and UTF-8 SHA-256, in addition to any historical_metrics."
            )
        command = [
            "codex",
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--skip-git-repo-check",
            "--sandbox",
            "workspace-write",
            "--model",
            self.model,
            "--cd",
            str(agent_root),
            "--output-last-message",
            str(last_message),
            "-",
        ]
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        with self._lock:
            self._active[invocation.runtime_instance_id] = proc
        try:
            stdout, stderr = proc.communicate(prompt, timeout=invocation.timeout_seconds)
            returncode = proc.returncode
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            returncode = 124
        finally:
            with self._lock:
                self._active.pop(invocation.runtime_instance_id, None)
        output_hash = None
        output_size = None
        if returncode == 0 and last_message.is_file():
            try:
                result = self._parse_final_json(last_message.read_text(encoding="utf-8"))
                invocation.private_output_path.parent.mkdir(parents=True, exist_ok=True)
                invocation.private_output_path.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                output_hash = sha256_file(invocation.private_output_path)
                output_size = invocation.private_output_path.stat().st_size
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                stderr = f"{stderr}\n{exc}"
                returncode = 1
        finished = _utc_now()
        provider_hash = hashlib.sha256(
            f"{invocation.session_id}\0{invocation.runtime_instance_id}\0{output_hash or ''}".encode()
        ).hexdigest()
        receipt = self._receipt(
            invocation,
            started=started,
            finished=finished,
            provider_hash=provider_hash,
            returncode=returncode,
            output_hash=output_hash,
            output_size=output_size,
        )
        return ResearchOrgSessionOutcome(
            returncode=returncode,
            session_id=invocation.session_id,
            runtime_instance_id=invocation.runtime_instance_id,
            started_at_utc=started,
            finished_at_utc=finished,
            provider="codex",
            model=self.model,
            transport="codex_exec_ephemeral",
            isolation_class="codex_subagent_isolated",
            owned_termination_supported=True,
            stdout_tail=stdout[-4000:],
            stderr_tail=stderr[-4000:],
            provider_session_handle_sha256=provider_hash,
            adapter_receipt=receipt,
        )

    def cancel_research_org_session(self, runtime_instance_id: str) -> bool:
        with self._lock:
            proc = self._active.get(runtime_instance_id)
        if proc is None:
            return True
        proc.kill()
        return True
