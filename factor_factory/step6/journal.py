"""Assemble existing research evidence without interpreting or rewriting it."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from factor_factory.runtime_context import resolve_factorforge_context


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None


def file_info(path: Path) -> dict[str, Any]:
    exists = path.exists()
    return {
        'path': str(path),
        'exists': exists,
        'size': path.stat().st_size if exists else None,
        'mtime': path.stat().st_mtime if exists else None,
    }


def compact(value: Any, max_chars: int = 5000) -> Any:
    if value is None:
        return None
    text = json.dumps(value, ensure_ascii=False, indent=2)
    if len(text) <= max_chars:
        return value
    return {'truncated': True, 'preview': text[:max_chars]}


def collect_object_files(report_id: str, *, workspace_root: Path | str | None = None) -> dict[str, list[dict[str, Any]]]:
    OBJ = resolve_factorforge_context(workspace_root).factorforge_root / "objects"
    out: dict[str, list[dict[str, Any]]] = {}
    if not OBJ.exists():
        return out
    for path in sorted(OBJ.glob(f'**/*__{report_id}.json')):
        rel = path.relative_to(OBJ)
        family = rel.parts[0] if rel.parts else 'objects'
        out.setdefault(family, []).append({
            **file_info(path),
            'preview': compact(load_json(path), max_chars=3000),
        })
    return out


def collect_generated_code(report_id: str, *, workspace_root: Path | str | None = None) -> list[dict[str, Any]]:
    root = resolve_factorforge_context(workspace_root).factorforge_root / "generated_code" / report_id
    if not root.exists():
        return []
    files = []
    for path in sorted(root.glob('*')):
        item = file_info(path)
        if path.suffix in {'.py', '.json', '.md', '.txt'}:
            try:
                item['preview'] = path.read_text(encoding='utf-8')[:3000]
            except Exception:
                pass
        files.append(item)
    return files


def collect_run_files(report_id: str, *, workspace_root: Path | str | None = None) -> list[dict[str, Any]]:
    root = resolve_factorforge_context(workspace_root).factorforge_root / "runs" / report_id
    if not root.exists():
        return []
    return [file_info(path) for path in sorted(root.glob('*'))]


def collect_evaluations(report_id: str, *, workspace_root: Path | str | None = None) -> dict[str, Any]:
    root = resolve_factorforge_context(workspace_root).factorforge_root / "evaluations" / report_id
    if not root.exists():
        return {}
    out: dict[str, Any] = {}
    for backend_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        payload_path = backend_dir / 'evaluation_payload.json'
        artifacts = []
        payload = load_json(payload_path) if payload_path.exists() else None
        for path in sorted(backend_dir.glob('*')):
            artifacts.append(file_info(path))
        out[backend_dir.name] = {
            'payload': compact(payload, max_chars=5000),
            'artifacts': artifacts,
        }
    return out


def build_researcher_dossier(rid: str, *, workspace_root: Path | str | None = None) -> dict[str, Any]:
    root = resolve_factorforge_context(workspace_root).factorforge_root
    packet = {
        'report_id': rid,
        'factorforge_root': str(root),
        'research_journal_path': str(root / "objects" / 'research_journal' / f'research_journal__{rid}.json'),
        'object_files': collect_object_files(rid, workspace_root=root),
        'generated_code': collect_generated_code(rid, workspace_root=root),
        'run_files': collect_run_files(rid, workspace_root=root),
        'evaluations': collect_evaluations(rid, workspace_root=root),
        'researcher_questions': [
            'What was the author/source trying to capture?',
            'Did Step2 preserve that idea in the canonical spec?',
            'Did Step3B implement the idea faithfully?',
            'Do Step4 metrics support the return-source thesis or only a fragile implementation?',
            'What should be preserved in the knowledge base whether this succeeds or fails?',
            'If iterating, what should Step3B change and what would falsify the next iteration?',
        ],
        'producer': 'factor-forge-researcher.build_researcher_dossier',
    }
    return packet


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)
    packet = build_researcher_dossier(args.report_id)
    out = Path(args.output) if args.output else Path(packet["research_journal_path"]).with_name(f"researcher_dossier__{args.report_id}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(out))


if __name__ == "__main__":
    main()
