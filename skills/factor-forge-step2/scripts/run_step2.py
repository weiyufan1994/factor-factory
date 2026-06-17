#!/usr/bin/env python3
"""
Independent Step 2 runner for FactorForge.
Consumes Step 1 artifacts and produces Step 2 side artifacts + factor_spec_master.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FACTORFORGE = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
WORKSPACE = FACTORFORGE.parent
OBJECTS = FACTORFORGE / 'objects'
VALIDATION = OBJECTS / 'validation'
SPEC_MASTER_DIR = OBJECTS / 'factor_spec_master'
HANDOFF_DIR = OBJECTS / 'handoff'
REGISTRY_PATH = FACTORFORGE / 'data' / 'report_ingestion' / 'report_registry.json'
SUPPORTED_SOURCE_TYPES = {'pdf_report', 'paper_canonical_formula', 'natural_language_hypothesis'}
STEP2_SOURCE_CONTRACT_VERSION = 'factorforge_step2_source_contract_v2'
HYBRID_CONTRACT_VERSION = 'factorforge_hybrid_contract_v1'
DEFAULT_FORBIDDEN_CODE_PATTERNS = [
    r'shift\s*\(\s*-\d+',
    'future_return',
    'next_return',
    'forward_return',
    'label',
    'target',
    'future_',
    'lookahead',
    r'lead\s*\(',
]
SOURCE_TYPE_STEP2_PRODUCER = {
    'pdf_report': 'step2_pdf_report',
    'paper_canonical_formula': 'step12_canonical_formula_intake',
    'natural_language_hypothesis': 'step12_hypothesis_intake',
}

from factor_factory.artifact_identity import (
    build_artifact_identity,
    build_code_contract_hash,
    build_custom_block_hash,
    build_formula_hash,
    build_spec_hash,
    stable_hash,
)
from factor_factory.factor_families.base import FAMILY_PLUGIN_DECISION_VERSION
from factor_factory.formula import parse_formula, to_qlib_expression
from factor_factory.formula.field_aliases import build_standard_formula_fields_contract
from factor_factory.knowledge_context import retrieve_factor_knowledge_context
from factor_factory.mechanism_math.classifier import build_mechanism_math_contract, build_mechanism_math_contract_v2


def enforce_direct_step_policy(manifest_path: str | None = None) -> None:
    global FACTORFORGE, WORKSPACE, OBJECTS, VALIDATION, SPEC_MASTER_DIR, HANDOFF_DIR, REGISTRY_PATH
    if os.getenv('FACTORFORGE_ULTIMATE_RUN') == '1':
        return
    if os.getenv('FACTORFORGE_ALLOW_DIRECT_STEP') != '1':
        raise SystemExit(
            'BLOCKED_DIRECT_STEP: formal Step2 execution must enter via scripts/run_factorforge_ultimate.py. '
            'Direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.'
        )
    debug_raw = os.getenv('FACTORFORGE_DEBUG_ROOT')
    if not debug_raw:
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    debug_root = Path(debug_raw).expanduser().resolve()
    if not debug_root.exists():
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    canonical_root = FACTORFORGE.expanduser().resolve()
    if debug_root == canonical_root:
        raise SystemExit('BLOCKED_DIRECT_STEP: direct debug mode requires non-canonical FACTORFORGE_DEBUG_ROOT.')
    FACTORFORGE = debug_root
    WORKSPACE = FACTORFORGE.parent
    OBJECTS = FACTORFORGE / 'objects'
    VALIDATION = OBJECTS / 'validation'
    SPEC_MASTER_DIR = OBJECTS / 'factor_spec_master'
    HANDOFF_DIR = OBJECTS / 'handoff'
    REGISTRY_PATH = FACTORFORGE / 'data' / 'report_ingestion' / 'report_registry.json'
    os.environ['FACTORFORGE_ROOT'] = str(debug_root)


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


def normalize_source_type(aim: Dict[str, Any]) -> str:
    raw = str(aim.get('source_type') or aim.get('source_kind') or '').strip()
    if raw in {'pdf', 'html', 'report', 'research_report'}:
        return 'pdf_report'
    if not raw:
        return 'pdf_report'
    if raw not in SUPPORTED_SOURCE_TYPES:
        raise ValueError(f'unsupported source_type for Step2: {raw}')
    return raw


def formal_step2_producer(source_type: str) -> str:
    return SOURCE_TYPE_STEP2_PRODUCER[source_type]


def hybrid_contract_executable(contract: Dict[str, Any]) -> bool:
    operator_subgraph = contract.get('operator_subgraph') if isinstance(contract.get('operator_subgraph'), dict) else {}
    formula_ir = operator_subgraph.get('formula_ir') if isinstance(operator_subgraph.get('formula_ir'), dict) else {}
    custom_blocks = contract.get('custom_blocks')
    return bool(
        contract.get('hybrid_contract_version') == HYBRID_CONTRACT_VERSION
        and formula_ir
        and formula_ir.get('parse_status') == 'success'
        and isinstance(custom_blocks, list)
        and custom_blocks
        and contract.get('formula_hash')
        and contract.get('custom_block_hash')
        and contract.get('hybrid_hash')
    )


def direct_code_contract_available(primary: Dict[str, Any], aim: Dict[str, Any]) -> bool:
    return bool(explicit_direct_code_source_contract(primary, aim))


def formula_ir_executable(primary: Dict[str, Any]) -> bool:
    formula_ir = primary.get('formula_ir') if isinstance(primary.get('formula_ir'), dict) else {}
    return bool(formula_ir and formula_ir.get('parse_status') == 'success')


def explicit_direct_code_source_contract(primary: Dict[str, Any], aim: Dict[str, Any]) -> Dict[str, Any]:
    candidates: List[Dict[str, Any]] = []
    for payload in [primary, aim]:
        if not isinstance(payload, dict):
            continue
        raw_contract = payload.get('implementation_contract') if isinstance(payload.get('implementation_contract'), dict) else {}
        for candidate in [
            raw_contract.get('code_contract') if isinstance(raw_contract.get('code_contract'), dict) else {},
            payload.get('code_contract') if isinstance(payload.get('code_contract'), dict) else {},
            payload.get('direct_code_contract') if isinstance(payload.get('direct_code_contract'), dict) else {},
            (payload.get('canonical_spec') or {}).get('code_contract') if isinstance(payload.get('canonical_spec'), dict) and isinstance((payload.get('canonical_spec') or {}).get('code_contract'), dict) else {},
        ]:
            if candidate:
                candidates.append(candidate)

    for candidate in candidates:
        source = str(candidate.get('source_code') or candidate.get('code') or candidate.get('custom_source') or '').strip()
        if not source:
            continue
        source = source if source.endswith('\n') else source + '\n'
        imports = candidate.get('imports') or candidate.get('dependencies') or ['numpy', 'pandas']
        if not isinstance(imports, list):
            imports = [str(imports)]
        output_schema = candidate.get('output_schema') or {'columns': ['ts_code', 'trade_date', 'factor_value']}
        contract = {
            **candidate,
            'code_contract_version': candidate.get('code_contract_version') or 'factorforge_direct_code_contract_v1',
            'function_name': candidate.get('function_name') or candidate.get('entrypoint') or 'compute_factor',
            'entrypoint': candidate.get('entrypoint') or candidate.get('function_name') or 'compute_factor',
            'source_code': source,
            'code_hash': hashlib.sha256(source.encode('utf-8')).hexdigest(),
            'imports': imports,
            'dependencies': candidate.get('dependencies') or imports,
            'input_schema': candidate.get('input_schema') or {},
            'output_schema': output_schema,
            'required_fields': candidate.get('required_fields') or primary.get('required_inputs', []),
            'information_set_rules': candidate.get('information_set_rules') or ['no future-looking fields or negative shifts'],
            'forbidden_patterns': candidate.get('forbidden_patterns') or DEFAULT_FORBIDDEN_CODE_PATTERNS,
            'source_derivation': candidate.get('source_derivation') or {
                'derivation': 'source_code_preserved_from_formal_step2_raw_direct_code_contract',
                'not_fallback': True,
            },
        }
        return contract
    return {}


def infer_implementation_mode(source_type: str, primary: Dict[str, Any], aim: Dict[str, Any]) -> str:
    explicit = aim.get('implementation_mode') or primary.get('implementation_mode')
    if explicit:
        value = str(explicit)
        if value in {'operator', 'direct_code'}:
            return value
        if value == 'hybrid':
            hybrid_contract = build_hybrid_contract(primary, aim)
            if hybrid_contract_executable(hybrid_contract):
                return 'hybrid'
            return 'hybrid'
    if formula_ir_executable(primary):
        return 'operator'
    if direct_code_contract_available(primary, aim):
        return 'direct_code'
    if source_type == 'paper_canonical_formula':
        return 'operator'
    return 'operator'


def build_mode_decision(implementation_mode: str, primary: Dict[str, Any], aim: Dict[str, Any] | None = None) -> Dict[str, Any]:
    formula_ir = primary.get('formula_ir')
    parse_error = primary.get('formula_parse_error')
    direct_source_available = bool(explicit_direct_code_source_contract(primary, aim or {}))
    operator_success = (
        implementation_mode == 'operator'
        and isinstance(formula_ir, dict)
        and formula_ir.get('parse_status') == 'success'
    )
    return {
        'selected_mode': implementation_mode,
        'operator_attempted': True,
        'operator_result': 'success' if operator_success else ('failed' if parse_error else 'not_applicable'),
        'operator_failure_reason': None if operator_success else (parse_error or 'source requires non-operator implementation contract'),
        'hybrid_attempted': implementation_mode in {'hybrid', 'direct_code'},
        'hybrid_result': 'success' if implementation_mode == 'hybrid' else 'not_applicable',
        'hybrid_failure_reason': None if implementation_mode == 'hybrid' else 'not selected by Step2 contract',
        'direct_code_attempted': implementation_mode == 'direct_code',
        'direct_code_result': (
            'success' if implementation_mode == 'direct_code' and direct_source_available else
            'failed' if implementation_mode == 'direct_code' else
            'not_applicable'
        ),
        'direct_code_failure_reason': (
            None if implementation_mode == 'direct_code' and direct_source_available else
            'BLOCK_DIRECT_CODE_SOURCE_CONTRACT_MISSING: explicit direct_code mode requires source_code contract'
            if implementation_mode == 'direct_code' else
            'not selected by Step2 contract'
        ),
        'final_decision_reason': (
            'formula parsed into registered operator IR'
            if operator_success else
            'explicit source_code direct_code contract provided'
            if implementation_mode == 'direct_code' and direct_source_available else
            'direct_code selected explicitly but source_code contract is missing'
            if implementation_mode == 'direct_code' else
            'operator path selected; validator must confirm formula_ir'
        ),
    }


def build_hybrid_contract(primary: Dict[str, Any], aim: Dict[str, Any]) -> Dict[str, Any]:
    raw_contract = aim.get('implementation_contract') or primary.get('implementation_contract') or {}
    raw_operator = raw_contract.get('operator_subgraph') or primary.get('operator_subgraph') or {}
    formula_text = (
        raw_operator.get('formula_text')
        or primary.get('operator_subgraph_formula')
        or primary.get('raw_formula_text')
        or aim.get('operator_subgraph_formula')
        or aim.get('raw_formula')
        or ''
    )
    formula_ir = raw_operator.get('formula_ir')
    if not isinstance(formula_ir, dict) and formula_text:
        formula_ir = parse_formula(str(formula_text))
    operator_subgraph = {
        'formula_text': formula_text,
        'formula_ir_version': (formula_ir or {}).get('formula_ir_version'),
        'formula_ir': formula_ir or {},
        'operator_set': (formula_ir or {}).get('operator_set') or raw_operator.get('operator_set') or [],
        'required_fields': (formula_ir or {}).get('required_fields') or raw_operator.get('required_fields') or [],
        'resolved_fields': (formula_ir or {}).get('resolved_fields') or raw_operator.get('resolved_fields') or {},
        'formula_hash': (formula_ir or {}).get('formula_hash') or raw_operator.get('formula_hash') or stable_hash({'formula_text': formula_text}),
    }

    raw_blocks = raw_contract.get('custom_blocks') or primary.get('custom_blocks') or aim.get('custom_blocks') or []
    custom_blocks = []
    block_hash_inputs = []
    for idx, block in enumerate(raw_blocks if isinstance(raw_blocks, list) else [raw_blocks]):
        if not isinstance(block, dict):
            continue
        source_code = block.get('source_code') or block.get('code') or block.get('custom_source') or ''
        normalized = {
            'name': block.get('name') or f'custom_block_{idx + 1}',
            'purpose': block.get('purpose') or 'custom hybrid post-processing block',
            'function_name': block.get('function_name') or 'apply_custom_block',
            'input_schema': block.get('input_schema') or {'columns': ['ts_code', 'trade_date', 'operator_value'] + list(block.get('required_fields') or [])},
            'output_schema': block.get('output_schema') or {'columns': ['ts_code', 'trade_date', 'factor_value']},
            'required_fields': block.get('required_fields') or [],
            'forbidden_patterns': list(dict.fromkeys(DEFAULT_FORBIDDEN_CODE_PATTERNS + list(block.get('forbidden_patterns') or []))),
            'source_code': source_code,
        }
        block_hash = stable_hash({
            'source_code': source_code,
            'contract': {k: v for k, v in normalized.items() if k not in {'custom_block_hash'}},
        })
        normalized['custom_block_hash'] = block.get('custom_block_hash') or block_hash
        block_hash_inputs.append({'name': normalized['name'], 'custom_block_hash': normalized['custom_block_hash']})
        custom_blocks.append(normalized)

    custom_block_hash = raw_contract.get('custom_block_hash') or stable_hash(block_hash_inputs)
    required_custom_fields = []
    for block in custom_blocks:
        required_custom_fields.extend(str(field) for field in (block.get('required_fields') or []) if field)
    boundary = raw_contract.get('boundary') or {
        'operator_outputs': ['operator_value'],
        'custom_inputs': list(dict.fromkeys(['ts_code', 'trade_date', 'operator_value'] + required_custom_fields)),
        'custom_outputs': ['factor_value'],
        'protected_operator_outputs': ['operator_value'],
        'allow_operator_output_overwrite': False,
    }
    formula_hash = operator_subgraph.get('formula_hash')
    hybrid_hash = raw_contract.get('hybrid_hash') or stable_hash({
        'formula_hash': formula_hash,
        'custom_block_hash': custom_block_hash,
        'boundary': boundary,
    })
    return {
        'mode': 'hybrid',
        'implementation_mode': 'hybrid',
        'hybrid_contract_version': HYBRID_CONTRACT_VERSION,
        'operator_subgraph': operator_subgraph,
        'custom_blocks': custom_blocks,
        'boundary': boundary,
        'formula_hash': formula_hash,
        'custom_block_hash': custom_block_hash,
        'hybrid_hash': hybrid_hash,
    }


def explicit_family_plugin_selection(aim: Dict[str, Any], primary: Dict[str, Any]) -> Dict[str, Any]:
    """Propagate only explicit structured family-plugin declarations.

    Free-text mentions such as "shadow", "Williams", "candle", or price-volume shorthand
    may become suggestions, but they must not become executable plugin selection.
    """
    contract = aim.get('implementation_contract') or {}
    decision = aim.get('family_plugin_decision') or contract.get('family_plugin_decision') or {}
    family = aim.get('factor_family') or contract.get('factor_family') or primary.get('factor_family')
    plugin = aim.get('family_plugin') or contract.get('family_plugin') or primary.get('family_plugin')
    allowed = bool(aim.get('family_plugin_allowed') or contract.get('family_plugin_allowed') or primary.get('family_plugin_allowed'))
    if allowed and family and plugin:
        evidence = (
            decision.get('explicit_evidence')
            or aim.get('family_plugin_explicit_evidence')
            or contract.get('family_plugin_explicit_evidence')
            or primary.get('family_plugin_explicit_evidence')
            or []
        )
        evidence = as_list(evidence)
        return {
            'factor_family': str(family),
            'family_plugin': str(plugin),
            'family_plugin_allowed': True,
            'family_plugin_decision': {
                'decision_version': decision.get('decision_version') or FAMILY_PLUGIN_DECISION_VERSION,
                'plugin_selected': True,
                'plugin_id': str(plugin),
                'selection_reason': decision.get('selection_reason') or 'Explicit source artifact declared this family plugin.',
                'explicit_evidence': evidence,
                'not_selected_by_free_text': decision.get('not_selected_by_free_text', True),
                'human_review_required': bool(decision.get('human_review_required', not evidence)),
            },
        }

    suggestion_text = text_blob(aim, primary)
    if any(token in suggestion_text for token in ['shadow', 'williams', 'candlestick', '上影线', '下影线']):
        return {
            'family_plugin_suggestion': {
                'suggested_family': 'shadow_candlestick',
                'reason': 'source text mentions shadow/candlestick semantics',
                'formal_selection': False,
                'human_review_required': True,
            }
        }
    if 'price-volume' in suggestion_text or '价量' in suggestion_text:
        return {
            'family_plugin_suggestion': {
                'suggested_family': 'price_volume',
                'reason': 'source text mentions price-volume semantics',
                'formal_selection': False,
                'human_review_required': True,
            }
        }
    return {}


def load_source_context(report_id: str, aim: Dict[str, Any]) -> Dict[str, Any]:
    source_type = normalize_source_type(aim)
    if source_type == 'pdf_report':
        pdf_path = locate_pdf_path(report_id, aim)
        print(f'[FOUND] pdf_path={pdf_path}')
    else:
        pdf_path = None
        print(f'[SOURCE] {source_type}: no report_registry/PDF lookup required')
    primary_thesis, challenger_thesis, primary_report_map = read_step1_upstream(report_id)
    return {
        'source_type': source_type,
        'pdf_path': pdf_path,
        'primary_thesis': primary_thesis,
        'challenger_thesis': challenger_thesis,
        'primary_report_map': primary_report_map,
    }


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


def as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def text_blob(*objects: Any) -> str:
    return ' '.join(json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj for obj in objects).lower()


def infer_target_statistic(primary: Dict[str, Any], aim: Dict[str, Any]) -> str:
    step1_hint = ((aim.get('research_discipline') or {}).get('target_statistic_hint') or
                  (aim.get('math_discipline_review') or {}).get('target_statistic'))
    if step1_hint:
        return str(step1_hint)
    text = text_blob(primary.get('raw_formula_text'), primary.get('operators'), primary.get('time_series_steps'), primary.get('cross_sectional_steps'))
    if any(tok in text for tok in ['corr', '相关', 'cov']):
        return 'rolling dependence statistic used to forecast cross-sectional return ordering'
    if any(tok in text for tok in ['rank', 'zscore', 'bucket', 'quantile', '排序']):
        return 'cross-sectional ordering / standardized score statistic for future returns'
    if any(tok in text for tok in ['std', 'vol', '波动', '方差']):
        return 'conditional dispersion statistic linked to future returns'
    if any(tok in text for tok in ['argmax', 'argmin', 'ts_rank']):
        return 'time-series extremum/rank statistic linked to future returns'
    return 'conditional expected return or cross-sectional ranking effect inferred from the canonical spec'


def infer_step1_random_object_fallback(primary: Dict[str, Any], aim: Dict[str, Any]) -> str:
    text = text_blob(primary, aim)
    if any(tok in text for tok in ['volume', 'turnover', 'amount', '成交量', '换手', '价量']):
        return 'A-share liquidity/order-flow and price panel observed through tradable market data'
    if any(tok in text for tok in ['close', 'open', 'high', 'low', 'return', '价格', '收益', '影线']):
        return 'A-share daily/intraday price-return panel and cross-sectional return ordering'
    if any(tok in text for tok in ['revenue', 'profit', 'cash', '营收', '利润', '现金流', '合同负债']):
        return 'firm fundamental information state observed through accounting and disclosure fields'
    return 'report-defined security panel; researcher must restate the precise random object before promotion'


def infer_economic_mechanism(primary: Dict[str, Any], aim: Dict[str, Any], thesis: Dict[str, Any]) -> str:
    final_factor = aim.get('final_factor') or {}
    parts = [
        final_factor.get('economic_logic'),
        final_factor.get('behavioral_logic'),
        final_factor.get('causal_chain'),
        thesis.get('economic_logic'),
        thesis.get('behavioral_logic'),
        thesis.get('causal_chain'),
    ]
    mechanism = ' ; '.join(str(x) for x in parts if x)
    if mechanism.strip():
        return mechanism
    text = text_blob(primary)
    if any(tok in text for tok in ['volume', 'turnover', '成交量', '换手', '价量']):
        return 'Price-volume interaction may capture repeatable liquidity demand, attention, or temporary order-flow imbalance.'
    if any(tok in text for tok in ['revenue', 'profit', 'cash', '合同负债', '现金流']):
        return 'Fundamental feature changes may encode information diffusion before consensus reprices expected earnings.'
    return 'Economic mechanism is inferred but not yet fully explicit; Step6 must challenge whether it is risk premium, information advantage, constraint-driven arbitrage, or mixed.'


def infer_expected_failure_modes(primary: Dict[str, Any], consistency: Dict[str, Any], aim: Dict[str, Any]) -> List[str]:
    failures = []
    text = text_blob(primary, aim)
    if primary.get('ambiguities'):
        failures.append('Specification ambiguity can cause independent implementers to build different factors.')
    if consistency.get('distortion_risks'):
        failures.extend(str(x) for x in consistency.get('distortion_risks') or [])
    if any(tok in text for tok in ['rank', 'bucket', 'quantile', 'argmax', 'argmin', 'zscore']):
        failures.append('Boundary-sensitive ranking/normalization choices may overfit one sample or change behavior across regimes.')
    if any(tok in text for tok in ['turnover', 'volume', '分钟', 'intraday']):
        failures.append('Turnover, liquidity, and minute-data cleaning choices may consume or distort the theoretical spread.')
    if not failures:
        failures.append('The thesis may fail if signal evidence does not translate into a tradable, robust portfolio after costs and constraints.')
    return list(dict.fromkeys(failures))


def infer_innovative_idea_seeds(primary: Dict[str, Any], aim: Dict[str, Any]) -> List[str]:
    text = text_blob(primary, aim)
    seeds = []
    if any(tok in text for tok in ['corr', '相关']):
        seeds.append('Test whether the dependence statistic is more robust as a rank/quantile signal than as a raw correlation magnitude.')
    if any(tok in text for tok in ['volume', 'turnover', '成交量', '换手']):
        seeds.append('Explore separating permanent information volume shocks from temporary liquidity-pressure volume shocks.')
    if any(tok in text for tok in ['rank', 'zscore', 'bucket', 'quantile']):
        seeds.append('Run ablations for rank-only, zscore, winsorized, and neutralized variants to identify which operator carries the thesis.')
    if not seeds:
        seeds.append('Create one neighboring hypothesis that preserves the same return-source mechanism but changes the weakest operator.')
    return seeds


def build_reuse_instructions(primary: Dict[str, Any], aim: Dict[str, Any]) -> List[str]:
    return [
        'Future agents must preserve the author thesis before optimizing implementation details.',
        'Before Step3B coding, map every operator/window/neutralization choice to either explicit report evidence or an inferred assumption.',
        'If Step4 metrics are weak, revise the operator that most directly tests the return-source hypothesis rather than blindly adding complexity.',
    ]


def build_factor_knowledge_query(primary: Dict[str, Any], aim: Dict[str, Any], thesis: Dict[str, Any]) -> str:
    discipline = aim.get('research_discipline') or {}
    final_factor = aim.get('final_factor') or {}
    parts = [
        str(final_factor.get('name') or ''),
        str(final_factor.get('economic_logic') or ''),
        str(final_factor.get('behavioral_logic') or ''),
        str(final_factor.get('causal_chain') or ''),
        ' '.join(str(item) for item in final_factor.get('assembly_steps') or []),
        str(primary.get('raw_formula_text') or ''),
        ' '.join(str(item) for item in thesis.get('signals') or []),
        ' '.join(str(item) for item in thesis.get('key_variables') or []),
        json.dumps(discipline.get('economic_hypothesis') or {}, ensure_ascii=False),
        json.dumps(discipline.get('math_hypothesis_candidates') or [], ensure_ascii=False),
        str(discipline.get('initial_return_source_hypothesis') or ''),
        str(discipline.get('step1_random_object') or ''),
    ]
    return ' '.join(part for part in parts if part and part != '{}')


def retrieve_step2_factor_knowledge_context(primary: Dict[str, Any], aim: Dict[str, Any], thesis: Dict[str, Any]) -> Dict[str, Any]:
    query_text = build_factor_knowledge_query(primary, aim, thesis)
    try:
        return retrieve_factor_knowledge_context(text=query_text, top_k=5)
    except Exception as exc:
        return {
            'schema_version': 'factor_knowledge_context_v1',
            'node_count': 0,
            'nodes': [],
            'related_edges': [],
            'retrieval_error': str(exc),
            'query': {'text': query_text, 'top_k': 5},
        }


def summarize_factor_knowledge_context(context: Dict[str, Any]) -> List[str]:
    lessons: List[str] = []
    for node in context.get('nodes') or []:
        node_id = node.get('id') or 'unknown_graph_node'
        status = ','.join(str(item) for item in node.get('research_status') or [])
        summary = str(node.get('summary') or '').strip()
        lesson = f'Graph prior {node_id}'
        if status:
            lesson += f' [{status}]'
        if summary:
            lesson += f': {summary[:260]}'
        lessons.append(lesson)
    return lessons


def build_step2_research_contract(
    primary: Dict[str, Any],
    consistency: Dict[str, Any],
    aim: Dict[str, Any],
    thesis: Dict[str, Any],
) -> Dict[str, Any]:
    discipline = aim.get('research_discipline') or {}
    economic_hypothesis = discipline.get('economic_hypothesis') or {}
    math_hypothesis_candidates = discipline.get('math_hypothesis_candidates') or []
    formula_understanding = discipline.get('formula_understanding') or aim.get('formula_understanding') or {}
    economic_to_math_modelling = discipline.get('economic_to_math_modelling') or aim.get('economic_to_math_modelling') or {}
    factor_knowledge_context = (
        discipline.get('factor_knowledge_context')
        or (aim.get('learning_and_innovation') or {}).get('factor_knowledge_context')
        or retrieve_step2_factor_knowledge_context(primary, aim, thesis)
    )
    graph_lessons = summarize_factor_knowledge_context(factor_knowledge_context)
    prior_lessons = (
        (aim.get('research_discipline') or {}).get('similar_case_lessons_imported')
        or (aim.get('learning_and_innovation') or {}).get('similar_case_lessons_imported')
        or []
    )
    similar_case_lessons = list(dict.fromkeys([
        *[str(item) for item in prior_lessons if str(item).strip()],
        *graph_lessons,
    ]))
    if not similar_case_lessons:
        similar_case_lessons = ['No similar prior case was imported from Step1/graph; treat this as a cold-start prior and write back lessons after Step6.']
    return {
        'target_statistic': infer_target_statistic(primary, aim),
        'economic_mechanism': infer_economic_mechanism(primary, aim, thesis),
        'formula_understanding': formula_understanding,
        'economic_hypothesis': economic_hypothesis,
        'economic_to_math_modelling': economic_to_math_modelling,
        'math_hypothesis_candidates': math_hypothesis_candidates,
        'expected_failure_modes': infer_expected_failure_modes(primary, consistency, aim),
        'innovative_idea_seeds': infer_innovative_idea_seeds(primary, aim),
        'reuse_instruction_for_future_agents': build_reuse_instructions(primary, aim),
        'step1_random_object': (
            (aim.get('research_discipline') or {}).get('step1_random_object')
            or aim.get('step1_random_object')
            or infer_step1_random_object_fallback(primary, aim)
        ),
        'similar_case_lessons_imported': similar_case_lessons,
        'factor_knowledge_context': factor_knowledge_context,
        'knowledge_reference_contract': {
            'schema_version': 'factorforge_knowledge_reference_contract_v1',
            'source': 'factor_knowledge_graph' if (factor_knowledge_context.get('node_count') or 0) > 0 else 'cold_start_or_unavailable',
            'context_schema_version': factor_knowledge_context.get('schema_version'),
            'node_count': factor_knowledge_context.get('node_count') or 0,
            'edge_count': factor_knowledge_context.get('edge_count') or 0,
            'retrieval_error': factor_knowledge_context.get('retrieval_error'),
            'not_same_factor_unless_identity_matches': True,
        },
        'producer': 'step2_research_contract',
    }


def is_shadow_factor(final_factor: Dict[str, Any], thesis: Dict[str, Any]) -> bool:
    joined = ' '.join(str(x) for x in (thesis.get('signals', []) or []))
    return any(token in joined for token in ['candlestick_shadow_signal', 'williams_shadow_signal', 'shadow_composite_signal'])


def build_primary_spec(report_id: str, aim: Dict[str, Any], thesis: Dict[str, Any], report_map: Dict[str, Any]) -> Dict[str, Any]:
    final_factor = aim.get('final_factor', {})
    shadow_factor = is_shadow_factor(final_factor, thesis)
    return {
        'factor_id': final_factor.get('name', report_id),
        'report_id': report_id,
        'route': 'primary',
        'raw_formula_text': ' ; '.join(final_factor.get('assembly_steps', []) or aim.get('assembly_path', [])),
        'operators': [
            'mean()', 'std()', 'corr()', 'regression()', 'residual()', 'ZScore()', 'neutralization()'
        ],
        'required_inputs': thesis.get('key_variables', report_map.get('variables', [])),
        'time_series_steps': (
            [
                '每日计算标准化蜡烛上影线与下影线',
                '每日计算威廉上影线与威廉下影线',
                '回溯过去20个交易日，构造均值与标准差特征序列',
                '提取蜡烛上_std 与 威廉下_mean 作为综合因子核心部件'
            ]
            if shadow_factor else
            [
                '每日计算单只股票当日分钟收盘价与分钟成交量的相关系数',
                '回溯过去20个交易日，构造相关系数时间序列',
                '计算20日均值、20日标准差、以及相关系数时间趋势'
            ]
        ),
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
    shadow_factor = is_shadow_factor(final_factor, challenger)
    amb = list_unresolved_ambiguities(aim)
    extra = [
        '相关系数类型是否为 Pearson 仍需人工确认',
        '分钟频率与异常值处理路径可能改变复现结果'
    ]
    return {
        'factor_id': final_factor.get('name', report_id),
        'report_id': report_id,
        'route': 'challenger',
        'raw_formula_text': '挑战视角重建：' + ' ; '.join(aim.get('assembly_path', [])),
        'operators': [
            'corr()', 'mean()', 'std()', 'time-trend regression()', 'cross-sectional regression()', 'residual()', 'ZScore()'
        ],
        'required_inputs': challenger.get('key_variables', report_map.get('variables', [])),
        'time_series_steps': (
            [
                '按20日窗口重建标准化蜡烛上/下影线序列与威廉上/下影线序列',
                '独立抽取均值与波动两类影线信号',
                '检查综合因子是否明确由蜡烛上_std 与 威廉下_mean 组成'
            ]
            if shadow_factor else
            [
                '按20日窗口重建每日分钟价量相关系数序列',
                '独立抽取均值、波动、趋势三类信号',
                '检查 assembly_path 是否遗漏趋势项与反转剔除项'
            ]
        ),
        'cross_sectional_steps': (
            [
                '分别标准化蜡烛与威廉影线子因子',
                '对综合因子做市值与常用风格中性化检查',
                '验证不同参数M下综合影线因子稳健性',
                '最终组合为综合影线因子'
            ]
            if shadow_factor else
            [
                '分别中性化均值与波动项',
                '对反转因子做残差剥离',
                '对趋势项做多变量残差剥离',
                '最终组合为价量相关结构因子'
            ]
        ),
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
        'ambiguities': list(dict.fromkeys(amb + ([] if shadow_factor else extra))),
        'direction': normalize_direction(final_factor.get('direction'))
    }


def infer_formula_inputs(formula: str, fallback: List[Any]) -> List[str]:
    aliases = {'vol': 'volume', 'returns': 'return', 'ret': 'return'}
    tokens = re.findall(r'\b(?:open|high|low|close|vwap|volume|vol|amount|turnover|returns?|ret|adv\d*)\b', formula.lower())
    out: List[str] = []
    for token in tokens:
        out.append('volume' if token.startswith('adv') else aliases.get(token, token))
    out.extend(str(x) for x in fallback if x)
    return list(dict.fromkeys(out)) or ['close', 'volume']


def infer_formula_operators(formula: str, fallback: List[Any]) -> List[str]:
    known = [
        'rank', 'correlation', 'corr', 'sum', 'mean', 'std', 'delta', 'delay',
        'ts_rank', 'argmax', 'argmin', 'decay_linear', 'signedpower', 'scale',
        'indneutralize', 'regression', 'zscore',
    ]
    text = formula.lower()
    operators = [f'{name}()' for name in known if name in text]
    operators.extend(str(x) for x in fallback if x)
    return list(dict.fromkeys(operators)) or ['formula_expression()']


def build_primary_spec_from_pdf(report_id: str, aim: Dict[str, Any], thesis: Dict[str, Any], report_map: Dict[str, Any]) -> Dict[str, Any]:
    return build_primary_spec(report_id, aim, thesis, report_map)


def build_primary_spec_from_canonical_formula(report_id: str, aim: Dict[str, Any], thesis: Dict[str, Any], report_map: Dict[str, Any]) -> Dict[str, Any]:
    formula = str(aim.get('raw_formula') or thesis.get('raw_formula_text') or report_map.get('raw_formula') or '').strip()
    required_inputs = infer_formula_inputs(formula, as_list(thesis.get('key_variables') or report_map.get('variables')))
    operators = infer_formula_operators(formula, as_list(thesis.get('operators') or report_map.get('operators')))
    formula_ir = None
    formula_parse_error = None
    qlib_expression = None
    try:
        formula_ir = parse_formula(formula)
        if formula_ir.get('parse_status') == 'success':
            required_inputs = formula_ir.get('required_fields') or required_inputs
            operators = [f'{op}()' for op in (formula_ir.get('operator_set') or [])] or operators
        else:
            formula_parse_error = '; '.join(str(item) for item in (formula_ir.get('parse_errors') or [])) or 'formula parse failed'
        qlib_expression = to_qlib_expression(formula_ir)
    except Exception as exc:
        formula_parse_error = str(exc)
    return {
        'factor_id': aim.get('factor_id') or thesis.get('factor_id') or report_id,
        'report_id': report_id,
        'route': 'primary',
        'source_type': 'paper_canonical_formula',
        'producer': 'step2_canonical_formula_spec_builder',
        'raw_formula_text': formula,
        'formula_ir': formula_ir,
        'formula_parse_error': formula_parse_error,
        'qlib_expression': qlib_expression,
        'operators': operators,
        'required_inputs': required_inputs,
        'time_series_steps': [
            'Parse the canonical formula into its declared operator tree.',
            'Apply each rolling or lagged operator using only data available at the rebalance date.',
            'Preserve published window lengths and rank/correlation semantics unless Step3B records a reviewed deviation.',
        ],
        'cross_sectional_steps': [
            'Compute the canonical formula score for each stock.',
            'Apply cross-sectional ranking/normalization exactly where specified by the source formula.',
            'Pass the final score to Step4 as the long-side candidate signal.',
        ],
        'preprocessing': ['Apply the canonical Factor Forge universe filters and missing-data policy before formula evaluation.'],
        'normalization': ['Preserve formula-defined rank/scale operations; otherwise Step3B must document any added normalization.'],
        'neutralization': ['No neutralization is implied by the canonical formula unless Step3B/Step4 explicitly evaluates it as a variant.'],
        'rebalance_frequency': 'daily signal; portfolio rebalance cadence remains a Step4 evaluation setting',
        'implementation_assumptions': [
            'Declared formula operator semantics are treated as source-of-truth.',
            'Window alignment must avoid forward-looking data.',
        ],
        'explicit_items': [formula],
        'inferred_items': ['Data-field aliases must be resolved conservatively by Step3B.'],
        'ambiguities': as_list(aim.get('ambiguities')),
        'direction': aim.get('expected_direction') or 'formula_defined',
    }


def build_challenger_spec_from_canonical_formula(report_id: str, aim: Dict[str, Any], challenger: Dict[str, Any], report_map: Dict[str, Any]) -> Dict[str, Any]:
    spec = build_primary_spec_from_canonical_formula(report_id, aim, challenger, report_map)
    spec.update({
        'route': 'challenger',
        'producer': 'step2_canonical_formula_challenger_spec_builder',
        'time_series_steps': spec['time_series_steps'] + [
            'Independently audit every window and nested operator to catch off-by-one or rank-domain errors.'
        ],
        'inferred_items': spec['inferred_items'] + [
            'Challenger must flag source convention uncertainty instead of silently changing formula semantics.'
        ],
    })
    return spec


def build_primary_spec_from_hypothesis(report_id: str, aim: Dict[str, Any], thesis: Dict[str, Any], report_map: Dict[str, Any]) -> Dict[str, Any]:
    variables = list(dict.fromkeys(as_list(aim.get('candidate_variables')) + as_list(thesis.get('key_variables')) + as_list(report_map.get('variables'))))
    formula_text = str((aim.get('final_factor') or {}).get('assembly_steps', [''])[0] or thesis.get('raw_formula_text') or f'hypothesis_score({", ".join(str(x) for x in variables)})')
    return {
        'factor_id': (aim.get('final_factor') or {}).get('name') or aim.get('title') or report_id,
        'report_id': report_id,
        'route': 'primary',
        'source_type': 'natural_language_hypothesis',
        'producer': 'step2_hypothesis_spec_builder',
        'raw_formula_text': formula_text,
        'operators': list(dict.fromkeys(as_list(thesis.get('operators')) + ['change()', 'rank()', 'zscore()', 'lag_guard()'])),
        'required_inputs': variables or ['close', 'return'],
        'time_series_steps': [
            'Convert the stated hypothesis into lag-safe feature changes or levels.',
            'Apply disclosure-lag controls for any fundamental fields before scoring.',
            'Mark unresolved formula choices for human review instead of inventing precision.',
        ],
        'cross_sectional_steps': [
            'Transform the hypothesis strength into a cross-sectional score.',
            'Rank or z-score the score only after lag and availability checks are explicit.',
        ],
        'preprocessing': ['Use standard universe filters and enforce data availability at rebalance time.'],
        'normalization': ['Cross-sectional rank or z-score; exact choice requires review when the hypothesis is underspecified.'],
        'neutralization': ['Style/industry neutralization is an evaluation variant unless the hypothesis explicitly requires it.'],
        'rebalance_frequency': 'monthly by default for fundamental hypotheses unless Step3B justifies another cadence',
        'implementation_assumptions': [
            'Natural-language intake is a research contract, not executable code.',
            'Ambiguous variables and lags remain human-review items until resolved.',
        ],
        'explicit_items': [aim.get('raw_user_hypothesis') or thesis.get('signals')],
        'inferred_items': ['Formula expression is a conservative placeholder derived from the user hypothesis.'],
        'ambiguities': as_list(aim.get('ambiguities')),
        'direction': aim.get('expected_direction') or 'positive_if_hypothesis_strengthens',
    }


def build_challenger_spec_from_hypothesis(report_id: str, aim: Dict[str, Any], challenger: Dict[str, Any], report_map: Dict[str, Any]) -> Dict[str, Any]:
    spec = build_primary_spec_from_hypothesis(report_id, aim, challenger, report_map)
    spec.update({
        'route': 'challenger',
        'producer': 'step2_hypothesis_challenger_spec_builder',
        'time_series_steps': spec['time_series_steps'] + [
            'Challenge whether each proposed variable is observable before the target return window.'
        ],
        'inferred_items': spec['inferred_items'] + [
            'Challenger should ask for human confirmation when variable mapping or expected direction is not explicit.'
        ],
    })
    return spec


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


def build_factor_spec_master(report_id: str, aim: Dict[str, Any], primary: Dict[str, Any], consistency: Dict[str, Any], thesis: Dict[str, Any]) -> Dict[str, Any]:
    score = consistency.get('consistency_score', 1.0)
    source_type = normalize_source_type(aim)
    producer = formal_step2_producer(source_type)
    upstream_producer = aim.get('producer') or producer
    implementation_mode = infer_implementation_mode(source_type, primary, aim)
    branch_id = str(aim.get('branch_id') or 'main')
    run_id = str(aim.get('run_id') or 'run_001')
    parent_run_id = aim.get('parent_run_id')
    human_review_required = score < 0.7 or bool(aim.get('human_review_required'))
    chief_decision = None
    if human_review_required:
        chief_decision = f'CONSISTENCY_SCORE_TOO_LOW: {score} — needs chief review'
    research_contract = build_step2_research_contract(primary, consistency, aim, thesis)
    research_contract['producer'] = producer
    family_plugin_selection = explicit_family_plugin_selection(aim, primary)
    hybrid_contract = build_hybrid_contract(primary, aim) if implementation_mode == 'hybrid' else None
    direct_code_source_contract = explicit_direct_code_source_contract(primary, aim) if implementation_mode == 'direct_code' else {}
    formula_text = str(primary.get('raw_formula_text') or '')
    formula_ir = primary.get('formula_ir') if isinstance(primary.get('formula_ir'), dict) else {}
    canonical_required_fields = (
        formula_ir.get('required_fields')
        if isinstance(formula_ir, dict) and formula_ir.get('required_fields')
        else primary.get('required_inputs', [])
    )
    standard_formula_fields_contract = build_standard_formula_fields_contract(
        formula_text=formula_text,
        required_fields=canonical_required_fields,
        available_source_fields=[
            'amount',
            'close',
            'high',
            'low',
            'open',
            'pct_chg',
            'pre_close',
            'returns',
            'vol',
            'volume',
            'vwap',
        ],
    )

    master = {
        'contract_version': STEP2_SOURCE_CONTRACT_VERSION,
        'factor_id': primary.get('factor_id', report_id),
        'linked_idea_id': aim.get('report_id', report_id),
        'report_id': report_id,
        'source_type': source_type,
        'implementation_mode': implementation_mode,
        'producer': producer,
        'upstream_producer': upstream_producer,
        'source_metadata': {
            'factor_id': aim.get('factor_id'),
            'source_name': aim.get('source_name'),
            'source_url': aim.get('source_url'),
            'title': aim.get('title'),
            'window_start': aim.get('window_start'),
            'window_end': aim.get('window_end'),
        },
        'canonical_spec': {
            'formula_text': formula_text,
            'formula_ir': primary.get('formula_ir'),
            'formula_parse_error': primary.get('formula_parse_error'),
            'parse_status': ((primary.get('formula_ir') or {}).get('parse_status') if isinstance(primary.get('formula_ir'), dict) else None),
            'qlib_expression': primary.get('qlib_expression'),
            'operator_set': ((primary.get('formula_ir') or {}).get('operator_set') if isinstance(primary.get('formula_ir'), dict) else None) or primary.get('operators', []),
            'required_fields': canonical_required_fields,
            'resolved_fields': ((primary.get('formula_ir') or {}).get('resolved_fields') if isinstance(primary.get('formula_ir'), dict) else None) or {},
            'required_inputs': primary.get('required_inputs', []),
            'operators': primary.get('operators', []),
            'standard_formula_fields_contract': standard_formula_fields_contract,
            'time_series_steps': primary.get('time_series_steps', []),
            'cross_sectional_steps': primary.get('cross_sectional_steps', []),
            'preprocessing': primary.get('preprocessing', []),
            'normalization': primary.get('normalization', []),
            'neutralization': primary.get('neutralization', []),
            'rebalance_frequency': primary.get('rebalance_frequency', ''),
            'implementation_assumptions': primary.get('implementation_assumptions', []),
            'operator_subgraph': (hybrid_contract or {}).get('operator_subgraph'),
            'custom_blocks': (hybrid_contract or {}).get('custom_blocks') or primary.get('custom_blocks') or [],
            'boundary': (hybrid_contract or {}).get('boundary'),
        },
        'implementation_contract': {
            'implementation_mode': implementation_mode,
            'mode': implementation_mode,
            'branch_id': branch_id,
            'run_id': run_id,
            'parent_run_id': parent_run_id,
            'code_contract': (direct_code_source_contract or {
                'code_contract_version': 'factorforge_direct_code_contract_v1',
                'function_name': 'compute_factor',
                'entrypoint': 'compute_factor',
                'input_schema': {},
                'output_schema': {
                    'columns': ['ts_code', 'trade_date', 'factor_value'],
                },
                'required_fields': primary.get('required_inputs', []),
                'information_set_rules': ['no future-looking fields or negative shifts'],
                'forbidden_patterns': [
                    r'shift\s*\(\s*-\d+',
                    'future_return',
                    'next_return',
                    'label',
                    'target',
                    'future_',
                    'lookahead',
                ],
            }) if implementation_mode == 'direct_code' else None,
            'output_schema': {
                'columns': ['ts_code', 'trade_date', 'factor_value'],
            } if implementation_mode == 'direct_code' else None,
            'mode_contract': (
                'pure_formula_operator_graph'
                if implementation_mode == 'operator' else
                'agent_reviewed_direct_code_contract'
                if implementation_mode == 'direct_code' else
                'operator_subgraph_plus_custom_code_blocks'
            ),
            **(hybrid_contract or {}),
        },
        **{k: v for k, v in family_plugin_selection.items() if k in {'factor_family', 'family_plugin', 'family_plugin_allowed', 'family_plugin_decision', 'family_plugin_suggestion'}},
        'implementation_mode_decision': build_mode_decision(implementation_mode, primary, aim),
        'thesis': {
            'alpha_thesis': thesis.get('thesis_name') or (aim.get('final_factor') or {}).get('name'),
            'target_prediction': research_contract['target_statistic'],
            'economic_mechanism': research_contract['economic_mechanism'],
        },
        'math_discipline_review': {
            'step1_random_object': research_contract.get('step1_random_object'),
            'target_statistic': research_contract['target_statistic'],
            'information_set_legality': (aim.get('math_discipline_review') or {}).get('information_set_legality') or (aim.get('research_discipline') or {}).get('information_set_hint') or 'requires_researcher_confirmation_no_forward_leakage',
            'expected_failure_modes': research_contract['expected_failure_modes'],
        },
        'learning_and_innovation': {
            'similar_case_lessons_imported': research_contract['similar_case_lessons_imported'],
            'factor_knowledge_context_imported': research_contract.get('factor_knowledge_context') or {},
            'knowledge_reference_contract': research_contract.get('knowledge_reference_contract') or {},
            'innovative_idea_seeds': research_contract['innovative_idea_seeds'],
            'reuse_instruction_for_future_agents': research_contract['reuse_instruction_for_future_agents'],
        },
        'knowledge_reference_contract': research_contract.get('knowledge_reference_contract') or {},
        'research_contract': research_contract,
        'standard_formula_fields_contract': standard_formula_fields_contract,
        'ambiguities': list(dict.fromkeys(primary.get('ambiguities', []) + primary.get('inferred_items', []))),
        'human_review_required': human_review_required,
        'chief_decision': chief_decision,
        'opus_invoked': False
    }
    if family_plugin_selection.get('family_plugin_allowed'):
        for key in ['factor_family', 'family_plugin', 'family_plugin_allowed', 'family_plugin_decision']:
            master['implementation_contract'][key] = family_plugin_selection[key]
    elif family_plugin_selection.get('family_plugin_suggestion'):
        master['implementation_contract']['family_plugin_suggestion'] = family_plugin_selection['family_plugin_suggestion']
    mechanism_math_contract = (
        primary.get('mechanism_math_contract')
        or aim.get('mechanism_math_contract')
        or build_mechanism_math_contract(master)
    )
    if isinstance(mechanism_math_contract, dict):
        mechanism_math_contract.setdefault('source_economic_hypothesis', research_contract.get('economic_hypothesis') or {})
        mechanism_math_contract.setdefault('source_math_hypothesis_candidates', research_contract.get('math_hypothesis_candidates') or [])
    mechanism_math_contract_v2 = (
        primary.get('mechanism_math_contract_v2')
        or aim.get('mechanism_math_contract_v2')
        or build_mechanism_math_contract_v2(master)
    )
    master['mechanism_math_contract'] = mechanism_math_contract
    master['mechanism_math_contract_v2'] = mechanism_math_contract_v2
    master['canonical_spec']['mechanism_math_contract'] = mechanism_math_contract
    master['canonical_spec']['mechanism_math_contract_v2'] = mechanism_math_contract_v2
    master['math_discipline_review']['mechanism_math_contract_ref'] = {
        'math_model_status': mechanism_math_contract.get('math_model_status'),
        'model_family': mechanism_math_contract.get('model_family'),
        'state_or_object': mechanism_math_contract.get('state_or_object'),
        'target_functional': mechanism_math_contract.get('target_functional'),
        'monotonicity_claim': mechanism_math_contract.get('monotonicity_claim'),
    }
    spec_hash = build_spec_hash(master)
    formula_ir = (master.get('canonical_spec') or {}).get('formula_ir')
    formula_hash = (
        formula_ir.get('formula_hash')
        if implementation_mode in {'operator', 'hybrid'} and isinstance(formula_ir, dict) and formula_ir.get('formula_hash')
        else build_formula_hash(master)
    )
    code_contract_hash = build_code_contract_hash(master)
    if implementation_mode == 'hybrid' and hybrid_contract:
        formula_hash = hybrid_contract.get('formula_hash') or formula_hash
        custom_block_hash = hybrid_contract.get('custom_block_hash')
        hybrid_hash = hybrid_contract.get('hybrid_hash')
    else:
        custom_block_hash = build_custom_block_hash(master)
        hybrid_hash = stable_hash({'formula_hash': formula_hash, 'custom_block_hash': custom_block_hash})
    identity = build_artifact_identity(
        report_id=report_id,
        factor_id=str(master.get('factor_id') or report_id),
        source_type=source_type,
        implementation_mode=implementation_mode,
        contract_version=STEP2_SOURCE_CONTRACT_VERSION,
        producer=producer,
        upstream_producer=upstream_producer,
        spec_hash=spec_hash,
        branch_id=branch_id,
        run_id=run_id,
        parent_run_id=parent_run_id,
        artifact_role='factor_spec_master',
        formula_hash=formula_hash if implementation_mode in {'operator', 'hybrid'} else None,
        code_contract_hash=code_contract_hash if implementation_mode == 'direct_code' else None,
        custom_block_hash=custom_block_hash if implementation_mode == 'hybrid' else None,
        hybrid_hash=hybrid_hash if implementation_mode == 'hybrid' else None,
    )
    if family_plugin_selection.get('family_plugin_allowed'):
        identity['factor_family'] = family_plugin_selection.get('factor_family')
        identity['family_plugin'] = family_plugin_selection.get('family_plugin')
        identity['not_generic_fallback'] = True
    master['spec_hash'] = spec_hash
    master['artifact_identity'] = identity
    return master


def write_handoff_to_step3(report_id: str, factor_spec_master_path: Path) -> None:
    master = load_json(factor_spec_master_path)
    handoff = {
        'contract_version': STEP2_SOURCE_CONTRACT_VERSION,
        'report_id': report_id,
        'source_type': master.get('source_type'),
        'implementation_mode': master.get('implementation_mode'),
        'factor_family': master.get('factor_family'),
        'family_plugin': master.get('family_plugin'),
        'family_plugin_allowed': master.get('family_plugin_allowed'),
        'family_plugin_decision': master.get('family_plugin_decision'),
        'family_plugin_suggestion': master.get('family_plugin_suggestion'),
        'artifact_identity': {
            **(master.get('artifact_identity') or {}),
            'artifact_role': 'handoff_to_step3',
        },
        'spec_hash': master.get('spec_hash'),
        'producer': master.get('producer'),
        'upstream_producer': master.get('upstream_producer'),
        'step2_status': 'factor_spec_master_ready',
        'factor_spec_master_ref': factor_spec_master_path.name,
        'research_contract': master.get('research_contract') or {},
        'math_discipline_review': master.get('math_discipline_review') or {},
        'mechanism_math_contract': master.get('mechanism_math_contract') or {},
        'mechanism_math_contract_v2': master.get('mechanism_math_contract_v2') or {},
        'learning_and_innovation': master.get('learning_and_innovation') or {},
        'knowledge_reference_contract': master.get('knowledge_reference_contract') or {},
    }
    write_json(HANDOFF_DIR / f'handoff_to_step3__{report_id}.json', handoff)


def run_step2(report_id: str, dry_run: bool = False) -> None:
    print(f'Step 2 independent run for report_id={report_id}')
    print(f'dry_run={dry_run}')
    aim = load_alpha_idea_master(report_id)
    source_context = load_source_context(report_id, aim)
    source_type = source_context['source_type']
    primary_thesis = source_context['primary_thesis']
    challenger_thesis = source_context['challenger_thesis']
    primary_report_map = source_context['primary_report_map']
    print('[LOAD] Step 1 upstream artifacts ready')

    if source_type == 'paper_canonical_formula':
        primary = build_primary_spec_from_canonical_formula(report_id, aim, primary_thesis, primary_report_map)
        challenger = build_challenger_spec_from_canonical_formula(report_id, aim, challenger_thesis, primary_report_map)
    elif source_type == 'natural_language_hypothesis':
        primary = build_primary_spec_from_hypothesis(report_id, aim, primary_thesis, primary_report_map)
        challenger = build_challenger_spec_from_hypothesis(report_id, aim, challenger_thesis, primary_report_map)
    else:
        primary = build_primary_spec_from_pdf(report_id, aim, primary_thesis, primary_report_map)
        challenger = build_challenger_spec(report_id, aim, challenger_thesis, primary_report_map)
    consistency = score_consistency(primary, challenger, aim)
    master = build_factor_spec_master(report_id, aim, primary, consistency, primary_thesis)

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
    if not args.dry_run:
        enforce_direct_step_policy()
    run_step2(args.report_id, args.dry_run)
