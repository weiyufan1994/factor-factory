#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARENT = ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

RUNNER_PATH = ROOT / 'skills' / 'factor-forge-step2' / 'scripts' / 'run_step2.py'
spec = importlib.util.spec_from_file_location('factorforge_step2_runner', RUNNER_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f'cannot load Step 2 runner from {RUNNER_PATH}')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
run_step2 = module.run_step2


def copy_fixture(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def main() -> None:
    report_id = 'STEP2_SAMPLE_CPV'
    fixture_root = ROOT / 'fixtures' / 'step2'

    # install fixture objects into current runner-expected paths
    copy_fixture(fixture_root / 'alpha_idea_master__sample.json', ROOT / 'objects' / 'alpha_idea_master' / f'alpha_idea_master__{report_id}.json')
    copy_fixture(fixture_root / 'report_map_validation__sample__alpha_thesis.json', ROOT / 'objects' / 'validation' / f'report_map_validation__{report_id}__alpha_thesis.json')
    copy_fixture(fixture_root / 'report_map_validation__sample__challenger_alpha_thesis.json', ROOT / 'objects' / 'validation' / f'report_map_validation__{report_id}__challenger_alpha_thesis.json')
    copy_fixture(fixture_root / 'report_map__sample__primary.json', ROOT / 'objects' / 'report_maps' / f'report_map__{report_id}__primary.json')

    registry_path = ROOT / 'data' / 'report_ingestion' / 'report_registry.json'
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    if registry_path.exists():
        registry = json.loads(registry_path.read_text(encoding='utf-8'))
    else:
        registry = {}
    registry[report_id] = {
        'local_cache_path': str((fixture_root / 'sample_report_stub.pdf').resolve())
    }
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding='utf-8')

    run_step2(report_id, dry_run=False)


if __name__ == '__main__':
    main()
