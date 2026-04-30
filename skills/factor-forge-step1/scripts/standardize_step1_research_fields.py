#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(FF) not in sys.path:
    sys.path.append(str(FF))

from skills.factor_forge_step1.modules.report_ingestion.research_discipline import attach_step1_research_discipline  # type: ignore

OBJ = FF / 'objects'


def load_json(path: Path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {path}')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    args = ap.parse_args()
    rid = args.report_id
    path = OBJ / 'alpha_idea_master' / f'alpha_idea_master__{rid}.json'
    if not path.exists():
        raise SystemExit(f'STEP1_ALPHA_IDEA_MASTER_MISSING: {path}')
    aim = load_json(path)
    context = []
    for candidate in [
        OBJ / 'validation' / f'report_map_validation__{rid}__alpha_thesis.json',
        OBJ / 'validation' / f'report_map_validation__{rid}__challenger_alpha_thesis.json',
        OBJ / 'report_maps' / f'report_map__{rid}__primary.json',
    ]:
        if candidate.exists():
            context.append(load_json(candidate))
    enriched = attach_step1_research_discipline(aim, REPO_ROOT, *context)
    write_json(path, enriched)
    handoff = OBJ / 'handoff' / f'handoff__{rid}.json'
    if handoff.exists():
        h = load_json(handoff)
        h.setdefault('objects', {})['alpha_idea_master'] = enriched
        h['research_discipline'] = enriched.get('research_discipline') or {}
        write_json(handoff, h)


if __name__ == '__main__':
    main()
