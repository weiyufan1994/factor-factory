#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
OBJ = FF / 'objects'
EVAL = FF / 'evaluations'
RUNS = FF / 'runs'
GEN = FF / 'generated_code'


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


def collect_object_files(report_id: str) -> dict[str, list[dict[str, Any]]]:
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


def collect_generated_code(report_id: str) -> list[dict[str, Any]]:
    root = GEN / report_id
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


def collect_run_files(report_id: str) -> list[dict[str, Any]]:
    root = RUNS / report_id
    if not root.exists():
        return []
    return [file_info(path) for path in sorted(root.glob('*'))]


def collect_evaluations(report_id: str) -> dict[str, Any]:
    root = EVAL / report_id
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--output', default=None)
    args = ap.parse_args()
    rid = args.report_id

    packet = {
        'report_id': rid,
        'factorforge_root': str(FF),
        'research_journal_path': str(OBJ / 'research_journal' / f'research_journal__{rid}.json'),
        'object_files': collect_object_files(rid),
        'generated_code': collect_generated_code(rid),
        'run_files': collect_run_files(rid),
        'evaluations': collect_evaluations(rid),
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

    out = Path(args.output) if args.output else OBJ / 'research_journal' / f'researcher_dossier__{rid}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(packet, ensure_ascii=False, indent=2), encoding='utf-8')
    print(str(out))


if __name__ == '__main__':
    main()
