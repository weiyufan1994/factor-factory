#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skills.factor_forge_step1.modules.report_ingestion.adapters.html_report_adapter import HtmlReportAdapter
from skills.factor_forge_step1.modules.report_ingestion.orchestration.wiring import build_step1_pipeline


def main() -> None:
    root = ROOT
    fixture_html = root / 'fixtures' / 'step1' / 'sample_factor_report.html'
    fixture_intake = root / 'fixtures' / 'step1' / 'sample_intake_response.json'

    if not fixture_html.exists():
        raise FileNotFoundError(f'missing fixture html: {fixture_html}')
    if not fixture_intake.exists():
        raise FileNotFoundError(f'missing fixture intake: {fixture_intake}')

    adapter = HtmlReportAdapter(root / 'data' / 'report_ingestion' / 'raw' / 'html')
    source = adapter.from_local_file(fixture_html, title='Sample Factor Report — CPV Mini Fixture')
    pipeline = build_step1_pipeline(root)

    response_text = fixture_intake.read_text(encoding='utf-8')
    result = pipeline.run_pdf_skill(source=source, response_text=response_text)
    print(json.dumps({
        'report_id': source.report_id,
        'status': result.get('status'),
        'artifacts': result,
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
