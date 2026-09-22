#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = Path(os.getenv('FACTORFORGE_ROOT', str(REPO_ROOT))).expanduser()
OBJECTS = RUNTIME_ROOT / 'objects'
DEFAULT_OUTPUT = RUNTIME_ROOT / 'knowledge' / 'retrieval' / 'factorforge_retrieval_index.jsonl'
DEFAULT_MANIFEST = RUNTIME_ROOT / 'knowledge' / 'retrieval' / 'factorforge_retrieval_manifest.json'


class CorpusBuildError(ValueError):
    """Raised when a canonical object cannot be represented safely in the corpus."""


def load_json(path: Path) -> dict[str, Any]:
    with path.open('r', encoding='utf-8') as fh:
        return json.load(fh)


def compact_text(parts: list[str]) -> str:
    return '\n'.join(part.strip() for part in parts if part and part.strip())


def required_text(data: dict[str, Any], field: str, path: Path) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise CorpusBuildError(f'{path}: missing or invalid required string {field!r}')
    return value.strip()


def text_list(data: dict[str, Any], field: str, path: Path) -> list[str]:
    value = data.get(field, [])
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise CorpusBuildError(f'{path}: {field!r} must be a list of strings')
    return [item.strip() for item in value if item.strip()]


def optional_mapping(data: dict[str, Any], field: str, path: Path) -> dict[str, Any]:
    value = data.get(field, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise CorpusBuildError(f'{path}: {field!r} must be an object when present')
    return value


def safe_scalar(data: dict[str, Any], field: str, path: Path) -> str | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise CorpusBuildError(f'{path}: {field!r} must be a string when present')
    return value.strip() or None


def identity_scalar(identity: dict[str, Any], field: str, path: Path) -> str | None:
    value = identity.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise CorpusBuildError(f'{path}: artifact_identity.{field!r} must be a string when present')
    return value.strip() or None


def description(data: dict[str, Any], field: str, path: Path) -> str | dict | None:
    value = data.get(field)
    if value is not None and not isinstance(value, (str, dict)):
        raise CorpusBuildError(f'{path}: {field} must be text or an explicit object')
    return value


def make_factor_doc(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    rid = required_text(data, 'report_id', path)
    factor_id = required_text(data, 'factor_id', path)
    text = compact_text([
        f'Factor record for {factor_id} ({rid}).',
        f"decision={data.get('decision')} iteration_no={data.get('iteration_no')} run_status={data.get('run_status')} final_status={data.get('final_status')}",
        'headline_metrics=' + json.dumps(data.get('headline_metrics', {}), ensure_ascii=False),
        'strengths=' + '; '.join(data.get('strengths', [])),
        'weaknesses=' + '; '.join(data.get('weaknesses', [])),
        'risks=' + '; '.join(data.get('risks', [])),
    ])
    return {
        'id': f'factor_record::{rid}',
        'doc_type': 'factor_record',
        'report_id': rid,
        'factor_id': factor_id,
        'decision': data.get('decision'),
        'created_at_utc': data.get('created_at_utc'),
        'tags': ['factor_record', str(data.get('decision', 'unknown')), factor_id],
        'metadata': {
            'iteration_no': data.get('iteration_no'),
            'run_status': data.get('run_status'),
            'final_status': data.get('final_status'),
            'headline_metrics': data.get('headline_metrics', {}),
        },
        'source_path': str(path.resolve()),
        'text': text,
    }


def make_knowledge_doc(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    rid = required_text(data, 'report_id', path)
    factor_id = required_text(data, 'factor_id', path)
    success_patterns = text_list(data, 'success_patterns', path)
    failure_patterns = text_list(data, 'failure_patterns', path)
    modification_hypotheses = text_list(data, 'modification_hypotheses', path)
    reuse_constraints = text_list(data, 'reuse_constraints', path)
    source_identity = optional_mapping(data, 'source_identity', path)
    evidence_identity = optional_mapping(data, 'evidence_identity', path)
    source_case_identity = optional_mapping(data, 'source_case_identity', path)
    artifact_identity = optional_mapping(data, 'artifact_identity', path)
    mathematical_object = safe_scalar(data, 'mathematical_object', path)
    reusable_operator = data.get('reusable_operator')
    if reusable_operator is not None and not isinstance(reusable_operator, (str, dict, list)):
        raise CorpusBuildError(f'{path}: reusable_operator must be string, object, or list when present')
    implementation_references = data.get('implementation_references', data.get('code_references', []))
    if implementation_references is None:
        implementation_references = []
    if not isinstance(implementation_references, list) or any(not isinstance(item, str) for item in implementation_references):
        raise CorpusBuildError(f'{path}: implementation_references must be a list of strings when present')
    implementation_references = [item.strip() for item in implementation_references if item.strip()]
    learning_and_innovation = optional_mapping(data, 'learning_and_innovation', path)
    advisory_projection = {
        # These fields are copied from Step6's explicit knowledge writeback;
        # this indexer never infers mechanism or diagnosis from performance.
        'advisory_only': True,
        'factor_family': safe_scalar(data, 'factor_family', path),
        'monetization_model': safe_scalar(data, 'monetization_model', path),
        'bias_type': safe_scalar(data, 'bias_type', path),
        'return_source_hypothesis': safe_scalar(data, 'return_source_hypothesis', path),
        'expected_failure_regimes': text_list(data, 'expected_failure_regimes', path),
        'failure_conditions': text_list(data, 'expected_failure_regimes', path),
        'objective_constraint_dependency': safe_scalar(data, 'objective_constraint_dependency', path),
        'constraint_sources': text_list(data, 'constraint_sources', path),
        'research_variant': safe_scalar(data, 'research_variant', path),
        'paper_replication_status': safe_scalar(data, 'paper_replication_status', path),
        'applicability_conditions': text_list(data, 'applicability_conditions', path),
        'regime_detection': description(data, 'regime_detection', path),
        'treatment_effect': description(data, 'treatment_effect', path),
        'evidence_class': safe_scalar(data, 'evidence_class', path),
        'validity_status': safe_scalar(data, 'validity_status', path),
        'invalidation_reason': safe_scalar(data, 'invalidation_reason', path),
        # These are explicit Step6 projections, never inferred by the indexer.
        'mathematical_object': mathematical_object,
        'reusable_operator': reusable_operator,
        'implementation_references': implementation_references,
        'reuse_constraints': reuse_constraints,
        'learning_and_innovation': learning_and_innovation,
        'research_compatibility_profile': safe_scalar(data, 'research_compatibility_profile', path),
        'next_research_tests_absence_reason': safe_scalar(data, 'next_research_tests_absence_reason', path),
        'identity': {
            'artifact_identity': artifact_identity,
            'source_identity': source_identity,
            'source_case_identity': source_case_identity,
            'evidence_identity': evidence_identity,
        },
        # Workspace exports retain a relative source reference deliberately:
        # it explains the copied advisory record without creating a cross-
        # workspace absolute-path dependency.
        'workspace_export_source': {
            'record_relative_ref': safe_scalar(data, 'source_record_relative_ref', path),
            'record_sha256': safe_scalar(data, 'source_record_sha256', path),
        },
        'modification_hypotheses': [
            {'text': hypothesis, 'status': 'candidate_not_verified'}
            for hypothesis in modification_hypotheses
        ],
        'rival_candidates': [
            {'text': hypothesis, 'status': 'candidate_not_verified'}
            for hypothesis in modification_hypotheses
        ],
    }
    search_text = compact_text([
        # Search is mechanism-first: no decision, identity, or taxonomy labels
        # are added as lexical weights.
        str(advisory_projection['return_source_hypothesis'] or ''),
        '; '.join(expected for expected in advisory_projection['expected_failure_regimes']),
        '; '.join(advisory_projection['applicability_conditions']),
        str(advisory_projection['regime_detection'] or ''),
        str(advisory_projection['objective_constraint_dependency'] or ''),
        '; '.join(advisory_projection['constraint_sources']),
        str(advisory_projection['mathematical_object'] or ''),
        json.dumps(advisory_projection['reusable_operator'], ensure_ascii=False, sort_keys=True) if advisory_projection['reusable_operator'] is not None else '',
        '; '.join(success_patterns),
        '; '.join(failure_patterns),
        '; '.join(reuse_constraints),
        'Candidate hypothesis, not verified: ' + '; '.join(modification_hypotheses),
    ])
    identity_summary = (
        'research_variant=' + str(advisory_projection['research_variant'] or 'unknown')
        + ' paper_replication_status=' + str(advisory_projection['paper_replication_status'] or 'unknown')
    )
    text = compact_text([
        identity_summary,
        f'Knowledge record for {factor_id} ({rid}).',
        f"decision={data.get('decision')}",
        search_text,
    ])
    return {
        'id': f'knowledge_record::{rid}',
        'doc_type': 'knowledge_record',
        'report_id': rid,
        'factor_id': factor_id,
        'decision': data.get('decision'),
        # Preserve existing Step6-consumer fields at the document top level.
        'factor_family': advisory_projection['factor_family'],
        'monetization_model': advisory_projection['monetization_model'],
        'bias_type': advisory_projection['bias_type'],
        'return_source_hypothesis': advisory_projection['return_source_hypothesis'],
        'expected_failure_regimes': advisory_projection['expected_failure_regimes'],
        'objective_constraint_dependency': advisory_projection['objective_constraint_dependency'],
        'constraint_sources': advisory_projection['constraint_sources'],
        'research_variant': advisory_projection['research_variant'],
        'paper_replication_status': advisory_projection['paper_replication_status'],
        'applicability_conditions': advisory_projection['applicability_conditions'],
        'regime_detection': advisory_projection['regime_detection'],
        'treatment_effect': advisory_projection['treatment_effect'],
        'evidence_class': advisory_projection['evidence_class'],
        'validity_status': advisory_projection['validity_status'],
        'invalidation_reason': advisory_projection['invalidation_reason'],
        'mathematical_object': advisory_projection['mathematical_object'],
        'reusable_operator': advisory_projection['reusable_operator'],
        'implementation_references': advisory_projection['implementation_references'],
        'reuse_constraints': reuse_constraints,
        'learning_and_innovation': advisory_projection['learning_and_innovation'],
        'research_compatibility_profile': advisory_projection['research_compatibility_profile'],
        'next_research_tests_absence_reason': advisory_projection['next_research_tests_absence_reason'],
        'knowledge_scope': safe_scalar(data, 'knowledge_scope', path),
        'artifact_identity': artifact_identity,
        'formula_hash': identity_scalar(artifact_identity, 'formula_hash', path),
        'source_identity': source_identity,
        'source_case_identity': source_case_identity,
        'evidence_identity': evidence_identity,
        'source_record_relative_ref': safe_scalar(data, 'source_record_relative_ref', path),
        'source_record_sha256': safe_scalar(data, 'source_record_sha256', path),
        'created_at_utc': data.get('created_at_utc'),
        'tags': ['knowledge_record', str(data.get('decision', 'unknown')), factor_id],
        'metadata': {
            'success_patterns': success_patterns,
            'failure_patterns': failure_patterns,
            'modification_hypotheses': modification_hypotheses,
        },
        'advisory_projection': advisory_projection,
        'source_path': str(path.resolve()),
        'search_text': search_text,
        # Keep the legacy corpus body while `search_text` remains mechanism-first.
        'text': text,
    }


def make_iteration_doc(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    rid = required_text(data, 'report_id', path)
    factor_id = required_text(data, 'factor_id', path)
    judgment = optional_mapping(data, 'research_judgment', path)
    evidence = optional_mapping(data, 'evidence_summary', path)
    loop = optional_mapping(data, 'loop_action', path)
    text = compact_text([
        f'Research iteration record for {factor_id} ({rid}).',
        f"iteration_no={data.get('iteration_no')} source_case_status={data.get('source_case_status')}",
        f"decision={judgment.get('decision')} thesis={judgment.get('thesis')}",
        'headline_metrics=' + json.dumps(evidence.get('headline_metrics', {}), ensure_ascii=False),
        'step5_lessons=' + '; '.join(evidence.get('step5_lessons', [])),
        'step5_next_actions=' + '; '.join(evidence.get('step5_next_actions', [])),
        'modification_targets=' + '; '.join(loop.get('modification_targets', [])),
        f"next_runner={loop.get('next_runner')} stop_reason={loop.get('stop_reason')}",
    ])
    return {
        'id': f'research_iteration::{rid}::{data.get("iteration_no")}',
        'doc_type': 'research_iteration',
        'report_id': rid,
        'factor_id': factor_id,
        'decision': judgment.get('decision'),
        'created_at_utc': None,
        'tags': ['research_iteration', str(judgment.get('decision', 'unknown')), factor_id],
        'metadata': {
            'iteration_no': data.get('iteration_no'),
            'source_case_status': data.get('source_case_status'),
            'backend_statuses': evidence.get('backend_statuses', {}),
            'headline_metrics': evidence.get('headline_metrics', {}),
            'modification_targets': loop.get('modification_targets', []),
        },
        'source_path': str(path.resolve()),
        'text': text,
    }


def make_research_episode_doc(path: Path, data: dict[str, Any]) -> dict[str, Any]:
    """Index wrapper facts only; never promote them to economic lessons."""
    rid = required_text(data, 'report_id', path)
    version = required_text(data, 'episode_version', path)
    if version != 'factorforge_research_episode_v1':
        raise CorpusBuildError(f'{path}: unsupported research episode version')
    if (data.get('formal_step6_completed') is not False or data.get('advisory_only') is not True
            or data.get('lessons_status') != 'NEEDS_RESEARCHER_REVIEW'):
        raise CorpusBuildError(f'{path}: episode must retain unfinished advisory status')
    observations = data.get('observations', [])
    if not isinstance(observations, list) or any(not isinstance(row, dict) for row in observations):
        raise CorpusBuildError(f'{path}: observations must be a list of objects')
    source_refs = text_list(data, 'source_refs', path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    facts = [f"{row.get('command')} status={row.get('status')} returncode={row.get('returncode')}" for row in observations]
    text = compact_text([
        f'Research episode wrapper facts for {rid}.',
        'NEEDS_RESEARCHER_REVIEW',
        f"run_status={data.get('run_status')} failure_stage={data.get('failure_stage')}",
        '; '.join(facts),
    ])
    return {
        'id': f'research_episode::{rid}::{digest}', 'doc_type': 'research_episode',
        'report_id': rid, 'factor_id': data.get('factor_id'), 'decision': None,
        'advisory_only': True, 'lessons_status': 'NEEDS_RESEARCHER_REVIEW',
        'formal_step6_completed': False,
        'source_refs': source_refs, 'metadata': {'run_status': data.get('run_status'), 'failure_stage': data.get('failure_stage')},
        'source_path': str(path.resolve()), 'text': text,
    }


def active_workspace_exports(exports: Path) -> list[tuple[Path, dict[str, Any]]]:
    """Select explicit corrections, never a newest-file guess or history rewrite."""
    records: dict[str, tuple[Path, dict[str, Any], bytes]] = {}
    for path in sorted(exports.glob('knowledge_record__*.json')):
        if path.is_symlink() or not path.is_file():
            raise CorpusBuildError(f'{path}: export must be a regular non-symlink file')
        raw = path.read_bytes()
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get('export_status') != 'LOCAL_PROJECT_ADVISORY_CANDIDATE_NOT_CANONICAL':
            raise CorpusBuildError(f'{path}: invalid workspace experience export')
        if (data.get('export_version') != 'factorforge_workspace_experience_export_v1'
                or data.get('advisory_only') is not True
                or data.get('same_factor_not_generalized') is not True
                or data.get('canonical_promotion_allowed') is not False):
            raise CorpusBuildError(f'{path}: invalid advisory export boundary')
        records[path.name] = (path, data, raw)
    parents: dict[str, str] = {}
    for name, (path, data, _) in records.items():
        revision = data.get('export_revision')
        if revision is None:
            continue
        if not isinstance(revision, dict) or not str(revision.get('reason') or '').strip():
            raise CorpusBuildError(f'{path}: invalid export correction')
        parent_name = revision.get('supersedes_file')
        if parent_name not in records or parent_name == name:
            raise CorpusBuildError(f'{path}: correction predecessor missing or self-referential')
        _, parent, parent_raw = records[parent_name]
        if revision.get('supersedes_sha256') != hashlib.sha256(parent_raw).hexdigest():
            raise CorpusBuildError(f'{path}: correction predecessor content changed')
        changed = {key for key in set(data) | set(parent)
                   if key != 'export_revision' and data.get(key) != parent.get(key)}
        declared = revision.get('changed_fields')
        if (not isinstance(declared, list) or any(not isinstance(key, str) for key in declared)
                or len(set(declared)) != len(declared) or set(declared) != changed):
            raise CorpusBuildError(f'{path}: correction changed_fields does not describe the actual edit')
        # This checks which fields changed, not whether new prose is true.
        # Economic interpretation still requires the researcher's source review.
        for field in ('report_id', 'factor_id', 'source_record_relative_ref', 'source_record_sha256',
                      'artifact_identity', 'export_status', 'advisory_only',
                      'same_factor_not_generalized', 'canonical_promotion_allowed', 'decision'):
            if data.get(field) != parent.get(field):
                raise CorpusBuildError(f'{path}: correction changes case identity or authority: {field}')
        parents[name] = parent_name
    for name in parents:
        seen: set[str] = set()
        cursor = name
        while cursor in parents:
            if cursor in seen:
                raise CorpusBuildError('cyclic workspace export corrections')
            seen.add(cursor)
            cursor = parents[cursor]
    superseded = set(parents.values())
    selected = [(path, data) for name, (path, data, _) in records.items() if name not in superseded]
    case_ids = [(data.get('report_id'), data.get('factor_id')) for _, data in selected]
    if len(set(case_ids)) != len(case_ids):
        raise CorpusBuildError('ambiguous active workspace export corrections')
    return selected


def build_corpus(objects_root: Path | str, *, project_root: Path | None = None) -> list[dict[str, Any]]:
    """Read existing workspace records into a retrieval corpus without writing."""
    root = Path(objects_root).expanduser().resolve()
    project_root = Path(project_root or REPO_ROOT).resolve()
    sources = (
        ('factor_library_all', 'factor_record__*.json', make_factor_doc),
        ('research_knowledge_base', 'knowledge_record__*.json', make_knowledge_doc),
        ('research_iteration_master', 'research_iteration_master__*.json', make_iteration_doc),
    )
    docs: list[dict[str, Any]] = []
    source_ids: dict[str, Path] = {}
    for directory, pattern, builder in sources:
        source_directory = root / directory
        if source_directory.is_symlink():
            raise CorpusBuildError(
                f'{source_directory}: retrieval source directory must not be a symlink'
            )
        if not source_directory.exists():
            continue
        if not source_directory.is_dir():
            raise CorpusBuildError(
                f'{source_directory}: retrieval source must be a directory'
            )
        for path in sorted(source_directory.glob(pattern)):
            if path.is_symlink():
                raise CorpusBuildError(
                    f'{path}: retrieval source record must not be a symlink'
                )
            try:
                resolved_path = path.resolve(strict=True)
            except OSError as exc:
                raise CorpusBuildError(
                    f'{path}: unable to resolve retrieval source record: {exc}'
                ) from exc
            if not resolved_path.is_relative_to(root):
                raise CorpusBuildError(
                    f'{path}: retrieval source record escapes objects root'
                )
            try:
                data = load_json(resolved_path)
            except (OSError, json.JSONDecodeError) as exc:
                raise CorpusBuildError(f'{resolved_path}: invalid JSON object: {exc}') from exc
            if not isinstance(data, dict):
                raise CorpusBuildError(f'{resolved_path}: JSON root must be an object')
            doc = builder(resolved_path, data)
            doc_id = doc.get('id')
            if not isinstance(doc_id, str) or not doc_id:
                raise CorpusBuildError(f'{path}: builder produced invalid retrieval id')
            if doc_id in source_ids:
                raise CorpusBuildError(
                f'duplicate retrieval id {doc_id!r}: {source_ids[doc_id]} and {resolved_path}'
            )
            source_ids[doc_id] = resolved_path
            docs.append(doc)
    # Local episode files are deliberately separate from Step6 knowledge.
    episode_root = root.parent / 'knowledge' / 'research_episodes' if root.name == 'objects' else root / 'knowledge' / 'research_episodes'
    if episode_root.is_symlink():
        raise CorpusBuildError(f'{episode_root}: research episode directory must not be a symlink')
    if episode_root.is_dir():
        for path in sorted(episode_root.glob('episode__*.json')):
            if path.is_symlink() or not path.is_file():
                raise CorpusBuildError(f'{path}: research episode must be a regular non-symlink file')
            data = load_json(path)
            doc = make_research_episode_doc(path, data)
            if doc['id'] in source_ids:
                raise CorpusBuildError(f'duplicate retrieval id {doc["id"]!r}')
            source_ids[doc['id']] = path
            docs.append(doc)
    # Candidate workspace exports are an input only to the default project
    # corpus.  A source workspace refresh must remain self-contained: pulling
    # the default corpus back into it would make its local receipt depend on
    # unrelated studies (and can create duplicate case ids).
    exports = project_root / 'knowledge' / '因子工厂' / 'workspace_experience_exports'
    include_workspace_exports = root == (project_root / 'objects').resolve()
    # Researcher-authored notes preserve useful evidence when a study never
    # reached native Step6. They cannot masquerade as completed Step6 records.
    notes = project_root / 'knowledge/因子工厂/research_notes'
    if include_workspace_exports:
        if notes.is_symlink():
            raise CorpusBuildError('research notes directory must not be a symlink')
        for path in sorted(notes.glob('*.json')):
            if path.is_symlink() or not path.is_file():
                raise CorpusBuildError('research note must be a regular file')
            data = load_json(path)
            if (data.get('note_version') != 'factorforge_research_note_v1'
                    or data.get('advisory_only') is not True
                    or data.get('canonical_promotion_allowed') is not False
                    or data.get('formal_step6_completed') is not False
                    or not data.get('source_identity') or not data.get('evidence_class')):
                raise CorpusBuildError('research note evidence/boundary missing')
            if data.get('validity_status') == 'withdrawn':
                if not str(data.get('invalidation_reason') or '').strip():
                    raise CorpusBuildError('withdrawn note requires reason')
                continue
            doc = make_knowledge_doc(path, data)
            doc.update(id='research_note::' + required_text(data, 'note_id', path),
                       doc_type='research_note', decision=None,
                       reported_research_recommendation=data.get('reported_research_recommendation'),
                       formal_step6_completed=False,
                       lessons_status='RESEARCHER_AUTHORED_REPORT_SUMMARY',
                       source_path=str(path.relative_to(project_root)))
            if doc['id'] in source_ids:
                raise CorpusBuildError('duplicate research note id')
            source_ids[doc['id']] = path
            docs.append(doc)
    if include_workspace_exports and exports.is_dir() and not exports.is_symlink():
        for path, data in active_workspace_exports(exports):
            if data.get('validity_status') == 'withdrawn':
                if not str(data.get('invalidation_reason') or '').strip():
                    raise CorpusBuildError(f'{path}: withdrawn export requires invalidation_reason')
                continue
            doc = make_knowledge_doc(path, data)
            if doc['id'] in source_ids:
                raise CorpusBuildError(f'duplicate retrieval id {doc["id"]!r}')
            # A default-project candidate seed is portable only by its
            # repository-relative export reference, never by a checkout path.
            doc['source_path'] = str(path.relative_to(project_root))
            source_ids[doc['id']] = path
            docs.append(doc)
    episode_exports = project_root / 'knowledge' / '因子工厂' / 'research_episode_exports'
    if include_workspace_exports:
        if episode_exports.is_symlink():
            raise CorpusBuildError(f'{episode_exports}: research episode export directory must not be a symlink')
        if episode_exports.is_dir():
            for path in sorted(episode_exports.glob('episode__*.json')):
                if path.is_symlink() or not path.is_file():
                    raise CorpusBuildError(f'{path}: research episode export must be a regular non-symlink file')
                doc = make_research_episode_doc(path, load_json(path))
                if doc['id'] in source_ids:
                    raise CorpusBuildError(f'duplicate retrieval id {doc["id"]!r}')
                source_ids[doc['id']] = path
                docs.append(doc)
    return docs


def _atomic_write(path: Path, content: str) -> None:
    """Replace one derived file only after its complete content is available.

    The index and manifest are separate derived outputs, so this deliberately
    makes no claim of a two-file transaction.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def refresh_retrieval_index(
    runtime_root: Path,
    *,
    output: Path | None = None,
    manifest: Path | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    """Refresh workspace-local derived retrieval files from existing objects.

    Source validation and serialization complete before either prior derived
    output is replaced.  This protects a usable old index from missing or bad
    source objects; it is not a canonical admission or a two-file transaction.
    """
    runtime_root = Path(runtime_root).expanduser().resolve()
    objects_root = runtime_root / 'objects'
    # A normal workspace indexes its own objects and must keep this hard
    # source-directory check.  The default project has one additional,
    # explicit source: create-only workspace experience exports.  Allow that
    # project root to rebuild from those exports even in a fresh checkout with
    # no local objects directory; `build_corpus` still rejects an empty or bad
    # export corpus below.
    if objects_root.exists() and not objects_root.is_dir():
        raise CorpusBuildError(f'{objects_root}: source objects directory must be a directory')
    if (not objects_root.exists() and runtime_root != Path(project_root or REPO_ROOT).resolve()
            and not (runtime_root / 'knowledge/research_episodes').is_dir()):
        raise CorpusBuildError(f'{objects_root}: source objects directory is missing')

    resolved_output = (
        Path(output).expanduser().resolve()
        if output is not None
        else runtime_root / 'knowledge' / 'retrieval' / 'factorforge_retrieval_index.jsonl'
    )
    resolved_manifest = (
        Path(manifest).expanduser().resolve()
        if manifest is not None
        else runtime_root / 'knowledge' / 'retrieval' / 'factorforge_retrieval_manifest.json'
    )
    if resolved_output == resolved_manifest:
        raise ValueError('output and manifest must be different paths')

    docs = build_corpus(objects_root, project_root=project_root)
    if not docs:
        raise CorpusBuildError(f'{objects_root}: no retrieval source documents found')

    # Serialize first so unsupported values cannot partially refresh output.
    index_content = ''.join(
        json.dumps(doc, ensure_ascii=False) + '\n' for doc in docs
    )
    summary: dict[str, Any] = {
        'doc_count': len(docs),
        'doc_types': sorted({doc['doc_type'] for doc in docs}),
        'field_guide': {
            'id': 'stable retrieval id',
            'doc_type': 'factor_record | knowledge_record | research_iteration',
            'report_id': 'report identifier',
            'factor_id': 'factor family identifier',
            'decision': 'promote_official | iterate | reject | needs_human_review',
            'tags': 'keyword and routing tags for lexical / metadata retrieval',
            'metadata': 'structured fields for hybrid filtering',
            'text': 'embedding/full-text corpus body',
            'source_path': 'existing workspace record path',
        },
        'derived_only': True,
        'output_path': str(resolved_output),
        'manifest_path': str(resolved_manifest),
    }
    manifest_content = json.dumps(summary, ensure_ascii=False, indent=2) + '\n'

    _atomic_write(resolved_output, index_content)
    _atomic_write(resolved_manifest, manifest_content)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description='Build a JSONL retrieval corpus from factor library / knowledge objects.')
    ap.add_argument('--runtime-root', default=None, help='Explicit Factor Forge runtime root (defaults to FACTORFORGE_ROOT or repo root).')
    ap.add_argument('--output', default=None, help='JSONL output path')
    ap.add_argument('--manifest', default=None, help='Manifest output path')
    args = ap.parse_args()

    runtime_root = Path(args.runtime_root).expanduser() if args.runtime_root else RUNTIME_ROOT
    summary = refresh_retrieval_index(
        runtime_root,
        output=Path(args.output) if args.output else None,
        manifest=Path(args.manifest) if args.manifest else None,
    )
    print(f"[WRITE] {summary['output_path']}")
    print(f"[WRITE] {summary['manifest_path']}")


if __name__ == '__main__':
    main()
