#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from skills.factor_forge_step1.modules.report_ingestion.adapters.html_report_adapter import HtmlReportAdapter
from skills.factor_forge_step1.modules.report_ingestion.extractors.html_text_extractor import HtmlTextExtractor
from skills.factor_forge_step1.modules.report_ingestion.extractors.pdf_text_extractor import PdfTextExtractor
from skills.factor_forge_step1.modules.report_ingestion.registry.report_source_contract import normalize_report_source


def download_report(url: str) -> Path:
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in {'.pdf', '.html', '.htm'}:
        suffix = '.pdf'
    out_dir = ROOT / 'data' / 'report_ingestion' / 'raw' / 'downloads'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f'report_from_url{suffix}'
    with urlopen(url, timeout=30) as r:
        out_path.write_bytes(r.read())
    return out_path


def source_from_file(path: Path, title: str | None = None):
    suffix = path.suffix.lower()
    if suffix in {'.html', '.htm'}:
        adapter = HtmlReportAdapter(ROOT / 'data' / 'report_ingestion' / 'raw' / 'html')
        src = adapter.from_local_file(path, title=title or path.stem)
        src.local_cache_path = str(path)
        src.status = 'cached'
        return src, 'html'
    src = normalize_report_source(source_type='pdf', source_uri=str(path), title=title or path.stem)  # type: ignore[arg-type]
    src.local_cache_path = str(path)
    src.status = 'cached'
    return src, 'pdf'


def extract_text_blocks(source, kind: str) -> tuple[list[str], dict]:
    notes: list[str] = []
    meta: dict = {}
    try:
        if kind == 'pdf':
            extractor = PdfTextExtractor(ROOT / 'data' / 'report_ingestion' / 'raw' / 'extracted_text')
            artifact = extractor.extract(source)
            blocks = [b.text.strip() for b in artifact.blocks if b.text and b.text.strip()]
            return blocks, {'raw_text_path': artifact.raw_text_path, 'notes': artifact.extraction_notes}
        extractor = HtmlTextExtractor(ROOT / 'data' / 'report_ingestion' / 'raw' / 'extracted_text')
        artifact = extractor.extract(source)
        blocks = [b.text.strip() for b in artifact.blocks if b.text and b.text.strip()]
        if not blocks and source.local_cache_path:
            # HTML extractor is still skeletal; fallback to simple tag stripping.
            raw_html = Path(source.local_cache_path).read_text(encoding='utf-8', errors='ignore')
            text = re.sub(r'<[^>]+>', ' ', raw_html)
            text = re.sub(r'\s+', ' ', text).strip()
            blocks = [text] if text else []
        return blocks, {'raw_text_path': artifact.raw_text_path, 'notes': artifact.extraction_notes}
    except Exception as e:
        notes.append(f'auto extraction fallback: {e}')
        p = Path(source.local_cache_path or '')
        if p.exists() and p.suffix.lower() in {'.html', '.htm'}:
            raw_html = p.read_text(encoding='utf-8', errors='ignore')
            text = re.sub(r'<[^>]+>', ' ', raw_html)
            text = re.sub(r'\s+', ' ', text).strip()
            if text:
                return [text], {'raw_text_path': None, 'notes': notes}
        return [f'Report source: {source.source_uri}', f'Report title: {source.title or "unknown"}'], {'raw_text_path': None, 'notes': notes}


def split_candidates(text: str) -> list[str]:
    parts = re.split(r'[\n;；,，/| ]+', text)
    return [p.strip() for p in parts if p.strip()]


def dedupe(xs: list[str]) -> list[str]:
    out: list[str] = []
    for x in xs:
        if x and x not in out:
            out.append(x)
    return out


def detect_variables(text: str) -> list[str]:
    # Heuristic mapping keeps auto-intake deterministic and reviewable.
    mapping = [
        ('open', ['open', '开盘价']),
        ('high', ['high', '最高价']),
        ('low', ['low', '最低价']),
        ('close', ['close', '收盘价', '价格']),
        ('vol', ['volume', 'vol', '成交量']),
        ('amount', ['amount', '成交额']),
        ('pct_chg', ['pct_chg', 'return', '收益率', '涨跌幅']),
        ('market_cap', ['market cap', '市值']),
        ('turnover', ['turnover', '换手']),
        ('trade_time', ['minute', '分钟']),
    ]
    lower = text.lower()
    out: list[str] = []
    for name, pats in mapping:
        if any(p.lower() in lower for p in pats):
            out.append(name)
    if not out:
        out = ['close', 'vol', 'amount', 'pct_chg']
    return out


def detect_signals(text: str) -> list[str]:
    lower = text.lower()
    signals: list[str] = []
    shadow_context = any(token in text for token in ['上下影线', '上影线', '下影线', '蜡烛图', '威廉指标', '威廉上', '威廉下'])
    if shadow_context:
        signals.extend([
            'candlestick_shadow_signal',
            'williams_shadow_signal',
            'shadow_composite_signal',
        ])
    if ('corr' in lower or '相关' in text) and (
        'volume' in lower or 'vol' in lower or '量' in text
    ) and ('price' in lower or 'close' in lower or '价' in text):
        if not shadow_context:
            signals.append('price_volume_correlation')
    if 'trend' in lower or '趋势' in text:
        signals.append('trend_signal')
    if 'residual' in lower or '残差' in text or 'neutral' in lower or '中性' in text:
        signals.append('residualized_signal')
    if not signals:
        signals = ['cross_sectional_factor_signal']
    return dedupe(signals)


def detect_formula_lines(lines: list[str]) -> list[dict]:
    out: list[dict] = []
    for i, line in enumerate(lines):
        ll = line.lower()
        if any(k in ll for k in ['corr', 'mean', 'std', 'zscore', 'residual', '=']) or any(k in line for k in ['相关', '均值', '标准差', '中性']):
            out.append({'line': i + 1, 'text': line[:240]})
        if len(out) >= 12:
            break
    return out


def build_intake_payload(report_id: str, title: str, text_blocks: list[str], route: str) -> dict:
    # This auto-intake is intentionally conservative:
    # it bootstraps a runnable Step1/2 path and leaves ambiguities explicit for manual review.
    text = '\n'.join(text_blocks)
    lines = [x.strip() for x in re.split(r'[\r\n]+', text) if x.strip()]
    if not lines:
        lines = [title]
    joined = ' '.join(lines[:200])
    shadow_context = any(token in joined for token in ['上下影线', '上影线', '下影线', '蜡烛图', '威廉指标', '威廉上', '威廉下'])

    variables = detect_variables(joined)
    signals = detect_signals(joined)
    formula_clues = detect_formula_lines(lines)

    if 'ubl' in joined.lower() or shadow_context:
        factor_name = 'UBL'
    elif 'cpv' in joined.lower() or 'price_volume_correlation' in signals or '价量' in joined:
        factor_name = 'CPV'
    else:
        factor_name = 'AUTO_FACTOR'

    direction = 'Negative' if (
        any(k in joined.lower() for k in ['reversal', 'negative'])
        or ('反转' in joined)
        or ('月度IC 均值为-' in joined)
        or ('icir 为-' in joined.lower())
    ) else 'Positive'
    ambiguities = []
    if len(formula_clues) < 2:
        ambiguities.append('formula details are sparse in auto extraction output')
    if 'trade_time' not in variables and not shadow_context:
        ambiguities.append('minute frequency details may require manual confirmation')
    if route == 'challenger':
        ambiguities.append('challenger route requests stricter evidence alignment')

    section_map = []
    for idx, ln in enumerate(lines[:12], start=1):
        if len(ln) <= 80 or re.match(r'^\d+[\.\)]', ln):
            section_map.append({'id': f'sec_{idx:03d}', 'title': ln[:120]})

    subfactors = [{'name': s, 'summary': s.replace('_', ' ')} for s in signals]
    if shadow_context:
        assembly_steps = [
            'compute normalized candlestick upper/lower shadows from open/high/low/close',
            'compute Williams-style upper/lower shadow variants',
            'aggregate 20-day mean/std shadow features cross-sectionally',
            'combine candle_up_std and william_down_mean into composite UBL signal',
            'apply cross-sectional normalization',
        ]
    else:
        assembly_steps = [
            'extract minute/daily features',
            'build price-volume interaction signal',
            'apply cross-sectional normalization',
        ]
    if 'residualized_signal' in signals:
        assembly_steps.append('apply residualization / neutralization')
    if 'trend_signal' in signals:
        assembly_steps.append('merge trend and interaction components')

    return {
        'report_meta': {
            'title': title,
            'topic': 'factor research',
            'route': route,
        },
        'section_map': section_map,
        'variables': variables,
        'signals': signals,
        'subfactors': subfactors,
        'final_factor': {
            'name': factor_name,
            'assembly_steps': assembly_steps,
            'direction': direction,
            'alpha_strength': 'medium',
            'alpha_source': 'auto_ingestion',
            'economic_logic': 'Auto extracted from report text; requires analyst review.',
            'behavioral_logic': 'Auto extracted from report text; requires analyst review.',
            'causal_chain': 'Report hypothesis -> signal transformation -> cross-sectional ranking.',
        },
        'formula_clues': formula_clues,
        'code_clues': [],
        'implementation_clues': [{'note': 'generated by run_step12_from_report.py auto intake mode'}],
        'alpha_candidates': [{'name': factor_name, 'direction': direction}],
        'evidence_clues': [{'snippet': ln[:240]} for ln in lines[:8]],
        'ambiguities': dedupe(ambiguities),
    }


def write_intake_files(report_id: str, primary: dict, challenger: dict) -> tuple[Path, Path]:
    out_dir = ROOT / 'runs' / 'step1_auto_intake' / report_id
    out_dir.mkdir(parents=True, exist_ok=True)
    p1 = out_dir / 'primary_intake.json'
    p2 = out_dir / 'challenger_intake.json'
    p1.write_text(json.dumps(primary, ensure_ascii=False, indent=2), encoding='utf-8')
    p2.write_text(json.dumps(challenger, ensure_ascii=False, indent=2), encoding='utf-8')
    return p1, p2


def run_step12_from_intake(report_file: Path, primary_json: Path, challenger_json: Path, report_id: str | None, title: str | None, skip_step2: bool) -> int:
    # Reuse the Step1+2 runner so object formats stay identical to the manual-intake path.
    cmd = [
        sys.executable,
        str(ROOT / 'scripts' / 'run_step12_from_intake.py'),
        '--report-file',
        str(report_file),
        '--primary-intake-json',
        str(primary_json),
        '--challenger-intake-json',
        str(challenger_json),
    ]
    if report_id:
        cmd += ['--report-id', report_id]
    if title:
        cmd += ['--title', title]
    if skip_step2:
        cmd.append('--skip-step2')

    result = subprocess.run(cmd, check=False)
    return result.returncode


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-file', help='Local report file path (.pdf/.html).')
    ap.add_argument('--report-url', help='Remote report URL (will be downloaded).')
    ap.add_argument('--report-id', help='Optional fixed report_id.')
    ap.add_argument('--title', help='Optional report title.')
    ap.add_argument('--skip-step2', action='store_true')
    args = ap.parse_args()

    if not args.report_file and not args.report_url:
        raise SystemExit('Either --report-file or --report-url is required.')

    report_file = Path(args.report_file).expanduser().resolve() if args.report_file else download_report(args.report_url)  # type: ignore[arg-type]
    if not report_file.exists():
        raise FileNotFoundError(f'report file not found: {report_file}')

    source, kind = source_from_file(report_file, title=args.title)
    if args.report_id:
        source.report_id = args.report_id

    blocks, meta = extract_text_blocks(source, kind)
    primary = build_intake_payload(source.report_id, source.title or report_file.stem, blocks, route='primary')
    challenger = build_intake_payload(source.report_id, source.title or report_file.stem, blocks, route='challenger')
    primary['report_meta']['auto_extract_notes'] = meta.get('notes', [])
    challenger['report_meta']['auto_extract_notes'] = meta.get('notes', [])
    if meta.get('raw_text_path'):
        primary['report_meta']['raw_text_path'] = meta['raw_text_path']
        challenger['report_meta']['raw_text_path'] = meta['raw_text_path']

    p1, p2 = write_intake_files(source.report_id, primary, challenger)
    rc = run_step12_from_intake(
        report_file=report_file,
        primary_json=p1,
        challenger_json=p2,
        report_id=source.report_id,
        title=args.title or report_file.stem,
        skip_step2=args.skip_step2,
    )
    if rc != 0:
        raise SystemExit(rc)

    summary = {
        'report_id': source.report_id,
        'report_file': str(report_file),
        'auto_primary_intake': str(p1),
        'auto_challenger_intake': str(p2),
        'raw_text_path': meta.get('raw_text_path'),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
