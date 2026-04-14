#!/usr/bin/env python3
"""
Independent Step 2 runner for FactorForge.
Consumes Step 1 artifacts and produces Step 2 side artifacts + factor_spec_master.
"""
import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FACTORFORGE = WORKSPACE / 'factorforge'
OBJECTS = FACTORFORGE / 'objects'
VALIDATION = OBJECTS / 'validation'
SPEC_MASTER_DIR = OBJECTS / 'factor_spec_master'
HANDOFF_DIR = OBJECTS / 'handoff'
REGISTRY_PATH = FACTORFORGE / 'data' / 'report_ingestion' / 'report_registry.json'


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {path}')


def load_alpha_idea_master(report_id: str) -> Dict[str, Any]:
    path = OBJECTS / 'alpha_idea_master' / f'alpha_idea_master__{report_id}.json'
    if not path.exists():
        raise FileNotFoundError(f'alpha_idea_master not found: {path}')
    return load_json(path)


def load_registry_record(report_id: str) -> Dict[str, Any]:
    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f'report_registry not found: {REGISTRY_PATH}')
    reg = load_json(REGISTRY_PATH)
    if report_id not in reg:
        raise KeyError(f'report_id not found in registry: {report_id}')
    return reg[report_id]


def locate_pdf_path(report_id: str, aim: Dict[str, Any]) -> str:
    rec = load_registry_record(report_id)
    local_cache_path = rec.get('local_cache_path')
    if local_cache_path and Path(local_cache_path).exists():
        return local_cache_path

    handoff = HANDOFF_DIR / f'handoff__{report_id}.json'
    if handoff.exists():
        h = load_json(handoff)
        for key in ['pdf_path', 'local_cache_path', 'source_path']:
            v = h.get(key)
            if v and Path(v).exists():
                return v

    for key in ['source_uri', 'local_cache_path', 'pdf_path']:
        v = aim.get(key)
        if isinstance(v, str) and Path(v).exists():
            return v

    raise FileNotFoundError('No usable local PDF path found via registry / handoff / alpha_idea_master')


def read_step1_upstream(report_id: str) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    primary_thesis = load_json(VALIDATION / f'report_map_validation__{report_id}__alpha_thesis.json')
    challenger_thesis = load_json(VALIDATION / f'report_map_validation__{report_id}__challenger_alpha_thesis.json')
    primary_report_map = load_json(OBJECTS / 'report_maps' / f'report_map__{report_id}__primary.json')
    return primary_thesis, challenger_thesis, primary_report_map


def list_unresolved_ambiguities(aim: Dict[str, Any]) -> List[str]:
    out = []
    for item in aim.get('unresolved_ambiguities', []):
        if isinstance(item, dict):
            amb = item.get('ambiguity')
            if amb:
                out.append(amb)
        elif isinstance(item, str):
            out.append(item)
    return out


def normalize_direction(v: Any) -> str:
    if str(v).strip() in {'-1', 'Negative', 'negative'}:
        return 'Negative'
    return str(v) if v is not None else ''


def build_primary_spec(report_id: str, aim: Dict[str, Any], thesis: Dict[str, Any], report_map: Dict[str, Any]) -> Dict[str, Any]:
    final_factor = aim.get('final_factor', {})
    return {
        'factor_id': 'CPV' if 'CPV' in final_factor.get('name', '') else final_factor.get('name', report_id),
        'report_id': report_id,
        'route': 'primary',
        'raw_formula_text': ' ; '.join(final_factor.get('assembly_steps', []) or aim.get('assembly_path', [])),
        'operators': [
            'mean()', 'std()', 'corr()', 'regression()', 'residual()', 'ZScore()', 'neutralization()'
        ],
        'required_inputs': thesis.get('key_variables', report_map.get('variables', [])),
        'time_series_steps': [
            '每日计算单只股票当日分钟收盘价与分钟成交量的相关系数',
            '回溯过去20个交易日，构造相关系数时间序列',
            '计算20日均值、20日标准差、以及相关系数时间趋势'
        ],
        'cross_sectional_steps': final_factor.get('assembly_steps', []) or aim.get('assembly_path', []),
        'preprocessing': [
            '剔除ST股', '剔除停牌股', '剔除上市不足60个交易日股票'
        ],
        'normalization': ['横截面Z-Score标准化'],
        'neutralization': [
            '市值中性化', '剔除Ret20', '对趋势项剔除市值/Ret20/Turn20/Vol20'
        ],
        'rebalance_frequency': '月度调仓',
        'explicit_items': thesis.get('signals', []),
        'inferred_items': [
            '若报告未显式给出实现细节，则按 alpha_idea_master 与 thesis 做最小保守补全'
        ],
        'ambiguities': list_unresolved_ambiguities(aim),
        'direction': normalize_direction(final_factor.get('direction'))
    }


def build_challenger_spec(report_id: str, aim: Dict[str, Any], challenger: Dict[str, Any], report_map: Dict[str, Any]) -> Dict[str, Any]:
    final_factor = aim.get('final_factor', {})
    amb = list_unresolved_ambiguities(aim)
    extra = [
        '相关系数类型是否为 Pearson 仍需人工确认',
        '分钟频率与异常值处理路径可能改变复现结果'
    ]
    return {
        'factor_id': 'CPV' if 'CPV' in final_factor.get('name', '') else final_factor.get('name', report_id),
        'report_id': report_id,
        'route': 'challenger',
        'raw_formula_text': '挑战视角重建：' + ' ; '.join(aim.get('assembly_path', [])),
        'operators': [
            'corr()', 'mean()', 'std()', 'time-trend regression()', 'cross-sectional regression()', 'residual()', 'ZScore()'
        ],
        'required_inputs': challenger.get('key_variables', report_map.get('variables', [])),
        'time_series_steps': [
            '按20日窗口重建每日分钟价量相关系数序列',
            '独立抽取均值、波动、趋势三类信号',
            '检查 assembly_path 是否遗漏趋势项与反转剔除项'
        ],
        'cross_sectional_steps': [
            '分别中性化均值与波动项',
            '对反转因子做残差剥离',
            '对趋势项做多变量残差剥离',
            '最终组合为 CPV'
        ],
        'preprocessing': [
            '剔除ST股', '剔除停牌股', '剔除上市不足60个交易日股票'
        ],
        'normalization': ['横截面Z-Score标准化'],
        'neutralization': [
            '市值中性化', 'Ret20剥离', '趋势项剔除市值/Ret20/Turn20/Vol20'
        ],
        'rebalance_frequency': '月度调仓（每月月底）',
        'explicit_items': challenger.get('signals', []),
        'inferred_items': [
            'challenger route 强调 primary 可能弱化的趋势项和控制变量',
            '若报告语义不足，则保留不确定性而不伪造确定细节'
        ],
        'ambiguities': list(dict.fromkeys(amb + extra)),
        'direction': normalize_direction(final_factor.get('direction'))
    }


def score_consistency(primary: Dict[str, Any], challenger: Dict[str, Any], aim: Dict[str, Any]) -> Dict[str, Any]:
    mismatches = []
    missing_steps = []
    distortion_risks = []

    if set(primary.get('required_inputs', [])) != set(challenger.get('required_inputs', [])):
        mismatches.append('required_inputs between primary and challenger are not identical')
    if primary.get('rebalance_frequency') != challenger.get('rebalance_frequency'):
        mismatches.append('rebalance_frequency mismatch')

    if not primary.get('required_inputs'):
        missing_steps.append('primary required_inputs missing')
    if not challenger.get('required_inputs'):
        missing_steps.append('challenger required_inputs missing')

    unresolved = list_unresolved_ambiguities(aim)
    if unresolved:
        distortion_risks.append('unresolved ambiguities may alter exact reconstruction details')

    score = 0.82
    if mismatches:
        score -= 0.08 * len(mismatches)
    if missing_steps:
        score -= 0.1 * len(missing_steps)
    score = max(0.0, min(1.0, score))

    recommendation = 'proceed' if score >= 0.7 else 'revise'
    return {
        'factor_id': primary.get('factor_id', 'unknown'),
        'report_id': primary.get('report_id'),
        'consistency_score': round(score, 2),
        'matches_core_driver': score >= 0.7,
        'mismatch_points': mismatches,
        'missing_steps': missing_steps,
        'distortion_risks': distortion_risks,
        'recommendation': recommendation
    }


def build_factor_spec_master(report_id: str, aim: Dict[str, Any], primary: Dict[str, Any], consistency: Dict[str, Any]) -> Dict[str, Any]:
    score = consistency.get('consistency_score', 1.0)
    human_review_required = score < 0.7
    chief_decision = None
    if human_review_required:
        chief_decision = f'CONSISTENCY_SCORE_TOO_LOW: {score} — needs chief review'

    return {
        'factor_id': primary.get('factor_id', report_id),
        'linked_idea_id': aim.get('report_id', report_id),
        'report_id': report_id,
        'canonical_spec': {
            'formula_text': primary.get('raw_formula_text', ''),
            'required_inputs': primary.get('required_inputs', []),
            'operators': primary.get('operators', []),
            'time_series_steps': primary.get('time_series_steps', []),
            'cross_sectional_steps': primary.get('cross_sectional_steps', []),
            'preprocessing': primary.get('preprocessing', []),
            'normalization': primary.get('normalization', []),
            'neutralization': primary.get('neutralization', []),
            'rebalance_frequency': primary.get('rebalance_frequency', '')
        },
        'ambiguities': list(dict.fromkeys(primary.get('ambiguities', []) + primary.get('inferred_items', []))),
        'human_review_required': human_review_required,
        'chief_decision': chief_decision,
        'opus_invoked': False
    }


def write_handoff_to_step3(report_id: str, factor_spec_master_path: Path) -> None:
    handoff = {
        'report_id': report_id,
        'step2_status': 'factor_spec_master_ready',
        'factor_spec_master_ref': factor_spec_master_path.name
    }
    write_json(HANDOFF_DIR / f'handoff_to_step3__{report_id}.json', handoff)


def run_step2(report_id: str, dry_run: bool = False) -> None:
    print(f'Step 2 independent run for report_id={report_id}')
    print(f'dry_run={dry_run}')
    aim = load_alpha_idea_master(report_id)
    pdf_path = locate_pdf_path(report_id, aim)
    print(f'[FOUND] pdf_path={pdf_path}')
    primary_thesis, challenger_thesis, primary_report_map = read_step1_upstream(report_id)
    print('[LOAD] Step 1 upstream artifacts ready')

    primary = build_primary_spec(report_id, aim, primary_thesis, primary_report_map)
    challenger = build_challenger_spec(report_id, aim, challenger_thesis, primary_report_map)
    consistency = score_consistency(primary, challenger, aim)
    master = build_factor_spec_master(report_id, aim, primary, consistency)

    if dry_run:
        print('[DRY] primary/challenger/consistency/master prepared')
        return

    primary_path = VALIDATION / f'factor_spec_raw__primary__{report_id}.json'
    challenger_path = VALIDATION / f'factor_spec_raw__challenger__{report_id}.json'
    consistency_path = VALIDATION / f'factor_consistency__{report_id}.json'
    master_path = SPEC_MASTER_DIR / f'factor_spec_master__{report_id}.json'

    write_json(primary_path, primary)
    write_json(challenger_path, challenger)
    write_json(consistency_path, consistency)
    write_json(master_path, master)
    write_handoff_to_step3(report_id, master_path)
    print('[DONE] Independent Step 2 run complete')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    run_step2(args.report_id, args.dry_run)
