from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


SOURCE_DIALECT_CONTRACT_VERSION = "factorforge_formula_source_dialect_v2"
SOURCE_DIALECT_ID = "rongliang_factor365_20260707_v2"
LEGACY_SOURCE_DIALECT_CONTRACT_VERSION = "factorforge_formula_source_dialect_v1"
LEGACY_SOURCE_DIALECT_ID = "rongliang_factor365_20260707_v1"
SOURCE_DIALECT_MIGRATION_VERSION = "factorforge_formula_source_dialect_migration_v1"
SOURCE_EVIDENCE_OBJECT_VERSION = "factorforge_formula_source_evidence_v1"
SOURCE_DIALECT_REFERENCE = (
    "https://finance.sina.com.cn/wm/2026-07-07/doc-inifxxwy1421970.shtml"
)
BLOCK_SOURCE_SEMANTICS_UNRESOLVED = (
    "BLOCK_FACTORFORGE_FORMULA_SOURCE_SEMANTICS_UNRESOLVED"
)
BLOCK_SOURCE_FORMULA_INVALID = "BLOCK_FACTORFORGE_FORMULA_SOURCE_DIALECT_INVALID"

SOURCE_OPERATOR_NAMES = frozenset(
    {
        "normalize",
        "s_log_lp",
        "s_log_1p",
        "ts_kurtosis",
        "ts_max_skew",
        "ts_min_skew",
        "ts_max_sum",
    }
)

SEMANTIC_CHOICES = {
    "kurtosis_convention": {"excess_unbiased", "pearson_unbiased"},
    "skew_convention": {"order_statistic_subset", "inner_window_extrema"},
    "max_sum_convention": {"contiguous_subwindow", "topk_values"},
    "zscore_ddof": {"0", "1"},
}
SEMANTIC_CHOICE_OPERATORS = {
    "kurtosis_convention": frozenset({"ts_kurtosis"}),
    "skew_convention": frozenset({"ts_max_skew", "ts_min_skew"}),
    "max_sum_convention": frozenset({"ts_max_sum"}),
    "zscore_ddof": frozenset({"normalize"}),
}
SEMANTIC_AUTHORITY_KINDS = frozenset(
    {"specific_source_evidence", "explicit_user_research_override"}
)


@dataclass(frozen=True)
class SourceFormulaDialectError(ValueError):
    token: str
    reasons: tuple[str, ...]

    def __str__(self) -> str:
        return f"{self.token}: {'; '.join(self.reasons)}"


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_locator_valid(value: str) -> bool:
    reference = str(value or "").strip()
    if "#" not in reference:
        return False
    target, locator = reference.rsplit("#", 1)
    if not target or not locator:
        return False
    target_valid = bool(
        re.fullmatch(r"https?://[^/\s#]+/[^\s#]+", target)
        or re.fullmatch(r"(?:request|workspace|artifact)://[^\s#]+", target)
        or (
            not Path(target).is_absolute()
            and ".." not in Path(target).parts
            and Path(target).suffix.lower()
            in {".html", ".htm", ".pdf", ".md", ".txt", ".json"}
        )
    )
    return bool(
        target_valid
        and re.fullmatch(
            r"(?:page|pages|line|lines|section|paragraph|anchor|quote|loc)=[^\s#]+",
            locator,
            flags=re.IGNORECASE,
        )
    )


def _safe_workspace_evidence_path(root: Path, relative_path: str) -> Path:
    relative = Path(str(relative_path or "").strip())
    if not relative_path or relative.is_absolute() or ".." in relative.parts:
        raise SourceFormulaDialectError(
            BLOCK_SOURCE_SEMANTICS_UNRESOLVED,
            ("semantic_authority.evidence_object.artifact_path must be workspace-relative",),
        )
    resolved_root = Path(root).resolve()
    unresolved = resolved_root / relative
    cursor = resolved_root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise SourceFormulaDialectError(
                BLOCK_SOURCE_SEMANTICS_UNRESOLVED,
                ("semantic_authority.evidence_object.artifact_path cannot traverse symlinks",),
            )
    candidate = unresolved.resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise SourceFormulaDialectError(
            BLOCK_SOURCE_SEMANTICS_UNRESOLVED,
            ("semantic_authority.evidence_object.artifact_path escapes evidence_root",),
        ) from exc
    if not candidate.is_file():
        raise SourceFormulaDialectError(
            BLOCK_SOURCE_SEMANTICS_UNRESOLVED,
            ("semantic_authority.evidence_object.artifact_path is not a readable regular file",),
        )
    return candidate


def _normalize_embedded_evidence(
    *,
    reference: str,
    excerpt: str,
    supplied_excerpt_sha256: str,
) -> dict[str, Any]:
    failures: list[str] = []
    if not _source_locator_valid(reference):
        failures.append(
            "semantic_authority.reference must include a source locator such as #page=7 or #line=10-20"
        )
    if not excerpt:
        failures.append(
            "semantic_authority.source_excerpt is required; hash-only evidence cannot be verified"
        )
    computed_excerpt_sha256 = _sha256_text(excerpt) if excerpt else ""
    if supplied_excerpt_sha256 and not re.fullmatch(
        r"[a-f0-9]{64}", supplied_excerpt_sha256
    ):
        failures.append(
            "semantic_authority.source_excerpt_sha256 must be a SHA-256 hex digest"
        )
    if (
        supplied_excerpt_sha256
        and computed_excerpt_sha256
        and supplied_excerpt_sha256 != computed_excerpt_sha256
    ):
        failures.append(
            "semantic_authority.source_excerpt_sha256 does not match source_excerpt"
        )
    if failures:
        raise SourceFormulaDialectError(
            BLOCK_SOURCE_SEMANTICS_UNRESOLVED,
            tuple(failures),
        )
    return {
        "version": SOURCE_EVIDENCE_OBJECT_VERSION,
        "storage_kind": "embedded_request_excerpt",
        "artifact_path": "request://semantic_authority/source_excerpt",
        "artifact_sha256": computed_excerpt_sha256,
        "locator": reference,
        "excerpt": excerpt,
        "excerpt_sha256": computed_excerpt_sha256,
        "read_verified": True,
        "hash_verified": True,
        "network_access_used": False,
        "verification_scope": "submitted_request_evidence_integrity",
    }


def _normalize_workspace_evidence(
    raw: Mapping[str, Any],
    *,
    reference: str,
    evidence_root: Path | None,
) -> dict[str, Any]:
    failures: list[str] = []
    artifact_path = str(raw.get("artifact_path") or "").strip()
    artifact_sha256 = str(raw.get("artifact_sha256") or "").strip().lower()
    locator = str(raw.get("locator") or reference).strip()
    excerpt = str(raw.get("excerpt") or "").strip()
    excerpt_sha256 = str(raw.get("excerpt_sha256") or "").strip().lower()
    if evidence_root is None:
        failures.append(
            "semantic_authority.evidence_object workspace evidence requires evidence_root"
        )
    if not _source_locator_valid(locator):
        failures.append(
            "semantic_authority.evidence_object.locator must identify page, line, section, paragraph, anchor, quote, or loc"
        )
    if locator != reference:
        failures.append(
            "semantic_authority.reference must exactly match evidence_object.locator"
        )
    if "#" in locator:
        locator_target = locator.rsplit("#", 1)[0]
        if locator_target.startswith("workspace://"):
            locator_target = locator_target.removeprefix("workspace://")
        if Path(locator_target).as_posix() != Path(artifact_path).as_posix():
            failures.append(
                "semantic_authority.evidence_object.locator must identify artifact_path"
            )
    if not re.fullmatch(r"[a-f0-9]{64}", artifact_sha256):
        failures.append(
            "semantic_authority.evidence_object.artifact_sha256 must be an exact SHA-256 digest"
        )
    if not excerpt:
        failures.append("semantic_authority.evidence_object.excerpt is required")
    if excerpt_sha256 and not re.fullmatch(r"[a-f0-9]{64}", excerpt_sha256):
        failures.append(
            "semantic_authority.evidence_object.excerpt_sha256 must be a SHA-256 digest"
        )
    if failures:
        raise SourceFormulaDialectError(
            BLOCK_SOURCE_SEMANTICS_UNRESOLVED,
            tuple(failures),
        )

    candidate = _safe_workspace_evidence_path(Path(evidence_root), artifact_path)
    actual_artifact_sha256 = _sha256_file(candidate)
    if actual_artifact_sha256 != artifact_sha256:
        failures.append(
            "semantic_authority.evidence_object.artifact_sha256 does not match artifact"
        )
    try:
        artifact_text = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        failures.append(
            "semantic_authority.evidence_object artifact must be readable UTF-8 evidence"
        )
        artifact_text = ""
    actual_excerpt_sha256 = _sha256_text(excerpt)
    if excerpt_sha256 and excerpt_sha256 != actual_excerpt_sha256:
        failures.append(
            "semantic_authority.evidence_object.excerpt_sha256 does not match excerpt"
        )
    if excerpt and excerpt not in artifact_text:
        failures.append(
            "semantic_authority.evidence_object.excerpt is not present in artifact"
        )
    if failures:
        raise SourceFormulaDialectError(
            BLOCK_SOURCE_SEMANTICS_UNRESOLVED,
            tuple(failures),
        )
    return {
        "version": SOURCE_EVIDENCE_OBJECT_VERSION,
        "storage_kind": "workspace_artifact",
        "artifact_path": Path(artifact_path).as_posix(),
        "artifact_sha256": actual_artifact_sha256,
        "locator": locator,
        "excerpt": excerpt,
        "excerpt_sha256": actual_excerpt_sha256,
        "read_verified": True,
        "hash_verified": True,
        "network_access_used": False,
        "verification_scope": "workspace_artifact_content_and_locator",
    }


def detected_source_operators(formula_text: str) -> list[str]:
    calls = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", str(formula_text or ""))
    return sorted({name.lower() for name in calls if name.lower() in SOURCE_OPERATOR_NAMES})


def uses_source_dialect(formula_text: str) -> bool:
    return bool(detected_source_operators(formula_text))


def normalize_semantic_choices(
    raw: Mapping[str, Any] | None,
    *,
    detected_operators: list[str] | None = None,
) -> dict[str, str]:
    required = (
        set(SEMANTIC_CHOICES)
        if detected_operators is None
        else {
            key
            for key, operators in SEMANTIC_CHOICE_OPERATORS.items()
            if operators.intersection(detected_operators)
        }
    )
    choices = {
        key: str((raw or {}).get(key) or "").strip().lower()
        for key in required
    }
    failures = [
        f"{key} must be one of {','.join(sorted(allowed))}"
        for key, allowed in SEMANTIC_CHOICES.items()
        if key in required
        if choices[key] not in allowed
    ]
    if failures:
        raise SourceFormulaDialectError(
            BLOCK_SOURCE_SEMANTICS_UNRESOLVED,
            tuple(failures),
        )
    return choices


def normalize_semantic_authority(
    raw: Mapping[str, Any] | None,
    *,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    authority = raw if isinstance(raw, Mapping) else {}
    kind = str(authority.get("kind") or "").strip().lower()
    reference = str(authority.get("reference") or "").strip()
    rationale = str(authority.get("rationale") or "").strip()
    not_performance_selected = authority.get(
        "implementation_choices_not_performance_selected"
    )
    failures: list[str] = []
    if kind not in SEMANTIC_AUTHORITY_KINDS:
        failures.append(
            "semantic_authority.kind must be specific_source_evidence or "
            "explicit_user_research_override"
        )
    if not reference:
        failures.append("semantic_authority.reference is required")
    if not rationale:
        failures.append("semantic_authority.rationale is required")
    if not_performance_selected is not True:
        failures.append(
            "semantic_authority.implementation_choices_not_performance_selected "
            "must be explicitly attested true"
        )

    normalized: dict[str, Any] = {
        "kind": kind,
        "reference": reference,
        "rationale": rationale,
        "implementation_choices_not_performance_selected": True,
    }
    if kind == "specific_source_evidence":
        evidence = (
            authority.get("evidence_object")
            if isinstance(authority.get("evidence_object"), Mapping)
            else None
        )
        if evidence is not None and (
            evidence.get("storage_kind")
            not in {"embedded_request_excerpt", "workspace_artifact"}
            or (
                evidence.get("version") is not None
                and evidence.get("version") != SOURCE_EVIDENCE_OBJECT_VERSION
            )
        ):
            raise SourceFormulaDialectError(
                BLOCK_SOURCE_SEMANTICS_UNRESOLVED,
                (
                    "semantic_authority.evidence_object must use the supported version "
                    "and storage_kind",
                ),
            )
        if evidence is not None and evidence.get("storage_kind") == "workspace_artifact":
            normalized_evidence = _normalize_workspace_evidence(
                evidence,
                reference=reference,
                evidence_root=evidence_root,
            )
            normalized["evidence_object"] = normalized_evidence
        else:
            excerpt = str(
                (evidence or {}).get("excerpt")
                or authority.get("source_excerpt")
                or ""
            ).strip()
            excerpt_sha256 = str(
                (evidence or {}).get("excerpt_sha256")
                or authority.get("source_excerpt_sha256")
                or ""
            ).strip().lower()
            normalized_evidence = _normalize_embedded_evidence(
                reference=reference,
                excerpt=excerpt,
                supplied_excerpt_sha256=excerpt_sha256,
            )
            normalized.update(
                {
                    "source_excerpt": excerpt,
                    "source_excerpt_sha256": normalized_evidence["excerpt_sha256"],
                    "evidence_object": normalized_evidence,
                }
            )
    elif kind == "explicit_user_research_override":
        override_reason = str(authority.get("override_reason") or "").strip()
        if not override_reason:
            failures.append(
                "semantic_authority.override_reason is required for "
                "explicit_user_research_override"
            )
        normalized["override_reason"] = override_reason

    if failures:
        raise SourceFormulaDialectError(
            BLOCK_SOURCE_SEMANTICS_UNRESOLVED,
            tuple(failures),
        )
    return normalized


class _RongliangDialectTranslator(ast.NodeTransformer):
    def __init__(self, choices: Mapping[str, str]) -> None:
        self.choices = choices

    def visit_Name(self, node: ast.Name) -> ast.AST:
        normalized = node.id.strip().lower()
        if normalized == "change_pct":
            return ast.copy_location(ast.Name(id="returns", ctx=node.ctx), node)
        if normalized in {"close", "volume"}:
            return ast.copy_location(ast.Name(id=normalized, ctx=node.ctx), node)
        return node

    def visit_Call(self, node: ast.Call) -> ast.AST:
        node = self.generic_visit(node)
        if not isinstance(node.func, ast.Name):
            return node
        source_name = node.func.id.strip().lower()
        if source_name not in SOURCE_OPERATOR_NAMES:
            return node
        if source_name == "normalize":
            standardize = None
            remaining_keywords: list[ast.keyword] = []
            for keyword in node.keywords:
                if str(keyword.arg or "").strip().lower() == "standardize":
                    if not isinstance(keyword.value, ast.Constant):
                        raise SourceFormulaDialectError(
                            BLOCK_SOURCE_FORMULA_INVALID,
                            ("NORMALIZE.STANDARDIZE must be a literal",),
                        )
                    standardize = keyword.value.value
                else:
                    remaining_keywords.append(keyword)
            if len(node.args) != 1 or remaining_keywords or standardize != 1:
                raise SourceFormulaDialectError(
                    BLOCK_SOURCE_FORMULA_INVALID,
                    ("only NORMALIZE(x, STANDARDIZE=1) is supported by this source dialect",),
                )
            return ast.copy_location(
                ast.Call(
                    func=ast.Name(id="cs_zscore", ctx=ast.Load()),
                    args=[node.args[0], ast.Constant(value=int(self.choices["zscore_ddof"]))],
                    keywords=[],
                ),
                node,
            )
        if node.keywords:
            raise SourceFormulaDialectError(
                BLOCK_SOURCE_FORMULA_INVALID,
                (f"{node.func.id} does not accept keyword arguments",),
            )
        if source_name in {"s_log_lp", "s_log_1p"}:
            replacement = "signed_log1p"
        elif source_name == "ts_kurtosis":
            replacement = (
                "rolling_excess_kurtosis"
                if self.choices["kurtosis_convention"] == "excess_unbiased"
                else "rolling_pearson_kurtosis"
            )
        elif source_name == "ts_max_skew":
            replacement = (
                "rolling_topk_skew"
                if self.choices["skew_convention"] == "order_statistic_subset"
                else "rolling_max_inner_skew"
            )
        elif source_name == "ts_min_skew":
            replacement = (
                "rolling_bottomk_skew"
                if self.choices["skew_convention"] == "order_statistic_subset"
                else "rolling_min_inner_skew"
            )
        elif source_name == "ts_max_sum":
            replacement = (
                "rolling_max_subwindow_sum"
                if self.choices["max_sum_convention"] == "contiguous_subwindow"
                else "rolling_topk_sum"
            )
        else:  # pragma: no cover - SOURCE_OPERATOR_NAMES is exhaustive above.
            return node
        node.func.id = replacement
        return node


def resolve_source_formula(
    formula_text: str,
    semantic_choices: Mapping[str, Any] | None,
    semantic_authority: Mapping[str, Any] | None = None,
    *,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    raw_formula = str(formula_text or "").strip()
    detected = detected_source_operators(raw_formula)
    if not detected:
        return {
            "contract_version": SOURCE_DIALECT_CONTRACT_VERSION,
            "dialect_id": "canonical_factorforge_formula_ir",
            "source_reference": None,
            "raw_formula": raw_formula,
            "raw_formula_sha256": _sha256_text(raw_formula),
            "canonical_formula": raw_formula,
            "semantic_choices": {},
            "detected_source_operators": [],
            "implementation_choices_frozen": False,
        }
    choices = normalize_semantic_choices(
        semantic_choices,
        detected_operators=detected,
    )
    authority = normalize_semantic_authority(
        semantic_authority,
        evidence_root=evidence_root,
    )
    try:
        expression = ast.parse(raw_formula, mode="eval")
        translated = _RongliangDialectTranslator(choices).visit(expression)
        ast.fix_missing_locations(translated)
        canonical_formula = ast.unparse(translated)
    except SourceFormulaDialectError:
        raise
    except (SyntaxError, TypeError, ValueError) as exc:
        raise SourceFormulaDialectError(
            BLOCK_SOURCE_FORMULA_INVALID,
            (f"{type(exc).__name__}: {exc}",),
        ) from exc
    contract = {
        "contract_version": SOURCE_DIALECT_CONTRACT_VERSION,
        "dialect_id": SOURCE_DIALECT_ID,
        "source_reference": SOURCE_DIALECT_REFERENCE,
        "raw_formula": raw_formula,
        "raw_formula_sha256": _sha256_text(raw_formula),
        "canonical_formula": canonical_formula,
        "semantic_choices": choices,
        "semantic_authority": authority,
        "detected_source_operators": detected,
        "implementation_choices_frozen": True,
        "source_meaning_status": (
            "verified_from_auditable_specific_source_evidence"
            if authority["kind"] == "specific_source_evidence"
            else "not_verified_explicit_user_research_override"
        ),
        "source_meaning_verified": authority["kind"] == "specific_source_evidence",
        "source_authenticity_verified": bool(
            authority["kind"] == "specific_source_evidence"
            and authority["evidence_object"]["storage_kind"] == "workspace_artifact"
        ),
        "source_verification_scope": (
            authority["evidence_object"]["verification_scope"]
            if authority["kind"] == "specific_source_evidence"
            else "explicit_user_research_override"
        ),
        "formal_execution_eligible": True,
        "implementation_variant_set": {
            "scope": "bounded_implementation_set",
            "implemented_variant_count": 2 ** len(choices),
            "exhaustive_source_truth": False,
        },
        "unit_translation": {"CHANGE_PCT": "returns=pct_chg/100"},
        "source_conflicts": [
            conflict
            for operators, conflict in (
                (
                    {"ts_max_sum"},
                    "TS_MAX_SUM body describes contiguous subwindows while the footnote describes top-k values.",
                ),
                (
                    {"ts_max_skew", "ts_min_skew"},
                    "TS_MAX_SKEW and TS_MIN_SKEW do not freeze estimator or nested-window semantics.",
                ),
                (
                    {"s_log_lp"},
                    "S_LOG_LP is treated as the source typo for documented S_LOG_1P.",
                ),
            )
            if operators.intersection(detected)
        ],
    }
    contract["contract_sha256"] = _sha256_text(
        json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return contract


def _legacy_source_formula_contract(
    formula_text: str,
    semantic_choices: Mapping[str, Any] | None,
) -> dict[str, Any]:
    raw_formula = str(formula_text or "").strip()
    detected = detected_source_operators(raw_formula)
    if not detected:
        raise SourceFormulaDialectError(
            BLOCK_SOURCE_FORMULA_INVALID,
            ("legacy migration requires a source-dialect formula",),
        )
    choices = normalize_semantic_choices(semantic_choices)
    try:
        expression = ast.parse(raw_formula, mode="eval")
        translated = _RongliangDialectTranslator(choices).visit(expression)
        ast.fix_missing_locations(translated)
        canonical_formula = ast.unparse(translated)
    except SourceFormulaDialectError:
        raise
    except (SyntaxError, TypeError, ValueError) as exc:
        raise SourceFormulaDialectError(
            BLOCK_SOURCE_FORMULA_INVALID,
            (f"{type(exc).__name__}: {exc}",),
        ) from exc
    contract = {
        "contract_version": LEGACY_SOURCE_DIALECT_CONTRACT_VERSION,
        "dialect_id": LEGACY_SOURCE_DIALECT_ID,
        "source_reference": SOURCE_DIALECT_REFERENCE,
        "raw_formula": raw_formula,
        "raw_formula_sha256": _sha256_text(raw_formula),
        "canonical_formula": canonical_formula,
        "semantic_choices": choices,
        "detected_source_operators": detected,
        "ambiguities_resolved": True,
        "unit_translation": {"CHANGE_PCT": "returns=pct_chg/100"},
        "source_conflicts": [
            "TS_MAX_SUM body describes contiguous subwindows while the footnote describes top-k values.",
            "TS_MAX_SKEW and TS_MIN_SKEW do not freeze estimator or nested-window semantics.",
            "S_LOG_LP is treated as the source typo for documented S_LOG_1P.",
        ],
    }
    contract["contract_sha256"] = _sha256_text(
        json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    return contract


def valid_source_formula_contract(
    value: Any,
    *,
    evidence_root: Path | None = None,
) -> bool:
    if not isinstance(value, Mapping):
        return False
    if (
        value.get("contract_version") != SOURCE_DIALECT_CONTRACT_VERSION
        or value.get("dialect_id") != SOURCE_DIALECT_ID
    ):
        return False
    try:
        expected = resolve_source_formula(
            str(value.get("raw_formula") or ""),
            value.get("semantic_choices")
            if isinstance(value.get("semantic_choices"), Mapping)
            else None,
            value.get("semantic_authority")
            if isinstance(value.get("semantic_authority"), Mapping)
            else None,
            evidence_root=evidence_root,
        )
    except SourceFormulaDialectError:
        return False
    return dict(value) == expected


def recognize_legacy_source_formula_contract(value: Any) -> bool:
    """Recognize a v1 artifact for explicit migration; never grants formal validity."""
    if not isinstance(value, Mapping):
        return False
    if (
        value.get("contract_version") != LEGACY_SOURCE_DIALECT_CONTRACT_VERSION
        or value.get("dialect_id") != LEGACY_SOURCE_DIALECT_ID
    ):
        return False
    try:
        expected = _legacy_source_formula_contract(
            str(value.get("raw_formula") or ""),
            value.get("semantic_choices")
            if isinstance(value.get("semantic_choices"), Mapping)
            else None,
        )
    except SourceFormulaDialectError:
        return False
    return dict(value) == expected


def migrate_legacy_source_formula_contract(
    value: Mapping[str, Any],
    semantic_authority: Mapping[str, Any] | None = None,
    *,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    if not recognize_legacy_source_formula_contract(value):
        raise SourceFormulaDialectError(
            BLOCK_SOURCE_FORMULA_INVALID,
            ("legacy source formula contract is not recognized",),
        )
    if semantic_authority is not None:
        return resolve_source_formula(
            str(value.get("raw_formula") or ""),
            value.get("semantic_choices")
            if isinstance(value.get("semantic_choices"), Mapping)
            else None,
            semantic_authority,
            evidence_root=evidence_root,
        )

    legacy_contract = dict(value)
    migration = {
        "contract_version": SOURCE_DIALECT_MIGRATION_VERSION,
        "dialect_id": SOURCE_DIALECT_ID,
        "source_reference": legacy_contract.get("source_reference"),
        "raw_formula": legacy_contract.get("raw_formula"),
        "raw_formula_sha256": legacy_contract.get("raw_formula_sha256"),
        "canonical_formula": legacy_contract.get("canonical_formula"),
        "semantic_choices": legacy_contract.get("semantic_choices"),
        "detected_source_operators": legacy_contract.get(
            "detected_source_operators"
        ),
        "implementation_choices_frozen": True,
        "semantic_authority": {
            "kind": "legacy_authority_required",
            "reference": "legacy-contract-sha256:"
            + str(legacy_contract.get("contract_sha256") or ""),
            "rationale": (
                "Preserve the v1 implementation choices for an auditable resume; "
                "the legacy artifact did not record a v2 source authority."
            ),
            "implementation_choices_not_performance_selected": None,
        },
        "source_meaning_status": "not_verified_legacy_authority_required",
        "source_meaning_verified": False,
        "source_authenticity_verified": False,
        "source_verification_scope": "legacy_contract_identity_only",
        "formal_execution_eligible": False,
        "authority_resolution": {
            "status": "AUTHORITY_REQUIRED",
            "required_contract_version": SOURCE_DIALECT_CONTRACT_VERSION,
            "legacy_contract_version": legacy_contract.get("contract_version"),
            "legacy_contract_sha256": legacy_contract.get("contract_sha256"),
            "legacy_contract_json_sha256": _sha256_text(
                json.dumps(
                    legacy_contract,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            ),
            "source_meaning_verified": False,
        },
        "unit_translation": legacy_contract.get("unit_translation"),
        "source_conflicts": legacy_contract.get("source_conflicts"),
    }
    migration["contract_sha256"] = _sha256_text(
        json.dumps(
            migration,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return migration
