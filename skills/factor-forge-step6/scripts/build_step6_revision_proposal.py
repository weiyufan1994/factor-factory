#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
LEGACY_WORKSPACE = Path('/home/ubuntu/.openclaw/workspace')
FF = Path(os.getenv('FACTORFORGE_ROOT') or (LEGACY_WORKSPACE / 'factorforge' if (LEGACY_WORKSPACE / 'factorforge').exists() else REPO_ROOT))
OBJ = FF / 'objects'


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'[WRITE] {path}')


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def infer_revision_direction(factor_id: str, modification_targets: list[str]) -> str:
    joined = ' | '.join(modification_targets).lower()
    if factor_id.upper() == 'UBL' or 'shadow' in joined or 'monotonicity' in joined:
        return '保持原始因子经济语义，但直接修改因子表达式/Step3B 代码，使高因子值更线性、单调地对应更强 long-side 收益'
    if 'qlib' in joined or 'payload' in joined:
        return '先修复评估稳定性与执行一致性，再决定是否大改因子公式'
    return '保持原始因子语义，优先做表达式方向、输入变换、窗口与归一化的可解释修订，而不是改组合或分位数组交易方式'


def infer_revision_logic(factor_id: str, modification_targets: list[str]) -> list[str]:
    steps = [
        '保留当前 Step3B 实现作为 base implementation，不直接覆盖原始实现',
        '新分支必须直接修改因子表达式或 Step3B 代码本身，不能通过 short、long-short、decile trading 或 portfolio expression 来补救',
        '优先检查高因子值是否真的代表更强的经济状态；如果不是，修订符号、输入比例、非线性压缩或窗口定义',
        '完成后重新跑 Step4/5/6，只用 long-side 收益、表达式单调性和稳健性判断是否继续',
    ]
    if factor_id.upper() == 'UBL':
        steps.insert(1, '针对影线类因子，先尝试平滑 + 截尾 + 重新标准化，而不是直接改影线定义')
    if any('monotonicity' in item.lower() for item in modification_targets):
        steps.append('重点观察分组单调性是否改善，而不只看单一 IC 指标')
    return steps


def infer_planned_actions(signal_column: str) -> list[str]:
    return [
        f'审查 `{signal_column}` 的经济方向：高值必须代表更高预期 long-side 收益，否则调整公式符号或变量排列',
        f'只在 Step3B 因子表达式/代码内做窗口、输入比例、线性化、截尾或标准化修改',
        '用分位数组只检查单调性和 top-group long-side 表现，不把分位数组当交易组合',
        '保留原始行身份与输出 schema，不改变 Step4 下游接口或组合表达式',
    ]


def extract_historical_analogues(iteration: dict) -> list[dict]:
    retrieval = iteration.get('retrieval_context') or {}
    rows = []
    for item in (retrieval.get('similar_cases') or [])[:3]:
        rows.append({
            'report_id': item.get('report_id'),
            'factor_id': item.get('factor_id'),
            'doc_type': item.get('doc_type'),
            'decision': item.get('decision'),
            'score': item.get('score'),
            'overlap_terms': item.get('overlap_terms') or [],
            'source_path': item.get('source_path'),
        })
    return rows


def build_subagent_taskbook(branches: list[dict], report_id: str) -> list[dict]:
    taskbook = []
    for idx, branch in enumerate(branches, start=1):
        branch_id = str(branch.get('branch_id') or f'branch_{idx}')
        taskbook.append({
            'branch_id': branch_id,
            'suggested_agent_role': 'research_worker',
            'write_scope': [
                f'factorforge/generated_code/{report_id}/{branch_id}/',
                f'factorforge/evaluations/{report_id}/{branch_id}/',
            ],
            'task': branch.get('goal'),
            'method': branch.get('method'),
            'must_not_do': [
                'do not overwrite the current canonical Step3B implementation',
                'do not hide failed runs',
                'do not claim improvement without Step4 evidence and validator output',
            ],
            'required_evidence': [
                'formula or parameter delta from base',
                'Step4 metric comparison versus base',
                'failure signature if the branch fails',
                'recommendation: promote branch, keep exploring, or kill branch',
            ],
        })
    return taskbook


def build_selection_policy(program_search_policy: dict, math_discipline: dict) -> dict:
    method_library = program_search_policy.get('method_library') or {}
    return {
        'reward_components': [
            'rank_ic_ir_delta',
            'long_side_sharpe_delta',
            'volatility_drag_delta',
            'max_drawdown_delta',
            'recovery_time_delta',
            'factor_value_return_monotonicity_delta',
            'regime_and_year_stability',
            'library_novelty',
            'complexity_penalty',
            'overfit_penalty',
        ],
        'hard_constraints': [
            'information_set_legality must remain valid',
            'kill_criteria from Step6 must be checked after each branch',
            'no branch may use short selling, direct decile trading, long-short spread, or portfolio-expression repair as adoption basis',
            'all approved revisions must change factor expression or Step3B code itself',
            'no branch may be promoted from a single in-sample improvement only',
        ] + list(math_discipline.get('kill_criteria') or []),
        'method_library_snapshot': {
            key: {
                'use_when': value.get('use_when'),
                'guardrail': value.get('guardrail'),
            }
            for key, value in method_library.items()
        },
    }


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--report-id', required=True)
    args = ap.parse_args()
    report_id = args.report_id

    iteration_path = OBJ / 'research_iteration_master' / f'research_iteration_master__{report_id}.json'
    handoff3b_path = OBJ / 'handoff' / f'handoff_to_step3b__{report_id}.json'
    handoff4_path = OBJ / 'handoff' / f'handoff_to_step4__{report_id}.json'
    if not iteration_path.exists() or not handoff3b_path.exists() or not handoff4_path.exists():
        raise SystemExit('STEP6_PROPOSAL_INVALID: missing iteration/handoff objects')

    iteration = load_json(iteration_path)
    handoff3b = load_json(handoff3b_path)
    handoff4 = load_json(handoff4_path)

    factor_id = str(iteration.get('factor_id') or report_id)
    signal_column = str(handoff4.get('signal_column') or f'{factor_id.lower()}_factor')
    current_impl_ref = str(handoff4.get('factor_impl_ref') or handoff4.get('factor_impl_stub_ref') or '')
    modification_targets = list(handoff3b.get('modification_targets') or [])
    iteration_no = int(iteration.get('iteration_no') or 1)
    proposed_impl_ref = f'generated_code/{report_id}/factor_impl__{report_id}__iter{iteration_no}.py'
    research_memo = ((iteration.get('research_judgment') or {}).get('research_memo') or {})
    math_discipline = research_memo.get('math_discipline_review') or {}
    program_search_policy = research_memo.get('program_search_policy') or ((iteration.get('research_judgment') or {}).get('program_search_policy') or {})
    revision_taxonomy = research_memo.get('revision_taxonomy') or ((iteration.get('research_judgment') or {}).get('revision_taxonomy') or {})
    diversity_position = research_memo.get('diversity_position') or ((iteration.get('research_judgment') or {}).get('diversity_position') or {})
    search_branches = ((program_search_policy.get('recommended_next_search') or {}).get('branches')) or []

    proposal = {
        'report_id': report_id,
        'factor_id': factor_id,
        'iteration_no': iteration_no,
        'current_impl_ref': current_impl_ref,
        'proposed_impl_ref': proposed_impl_ref,
        'proposal_status': 'pending_human_approval',
        'research_basis': {
            'decision': ((iteration.get('research_judgment') or {}).get('decision')),
            'thesis': ((iteration.get('research_judgment') or {}).get('thesis')),
            'strengths': ((iteration.get('research_judgment') or {}).get('strengths')) or [],
            'weaknesses': ((iteration.get('research_judgment') or {}).get('weaknesses')) or [],
            'risks': ((iteration.get('research_judgment') or {}).get('risks')) or [],
        },
        'proposal': {
            'revision_direction': infer_revision_direction(factor_id, modification_targets),
            'revision_logic': infer_revision_logic(factor_id, modification_targets),
            'planned_actions': infer_planned_actions(signal_column),
            'math_discipline_review': math_discipline,
            'revision_operator': math_discipline.get('revision_operator'),
            'generalization_argument': math_discipline.get('generalization_argument'),
            'overfit_risk': math_discipline.get('overfit_risk') or [],
            'kill_criteria': math_discipline.get('kill_criteria') or [],
            'target_return_source': ((iteration.get('research_judgment') or {}).get('factor_investing_framework') or {}).get('monetization_model'),
            'target_constraint_sources': ((iteration.get('research_judgment') or {}).get('factor_investing_framework') or {}).get('constraint_sources') or [],
            'modification_targets': modification_targets,
            'historical_analogues': extract_historical_analogues(iteration),
            'program_search_policy': program_search_policy,
            'revision_taxonomy': revision_taxonomy,
            'diversity_position': diversity_position,
            'candidate_branches': search_branches,
            'subagent_taskbook': build_subagent_taskbook(search_branches, report_id),
            'selection_and_reward_policy': build_selection_policy(program_search_policy, math_discipline),
            'review_answers': {
                'return_source_hypothesis': ((iteration.get('research_judgment') or {}).get('factor_investing_framework') or {}).get('return_source_hypothesis'),
                'expected_failure_regimes': ((iteration.get('research_judgment') or {}).get('factor_investing_framework') or {}).get('expected_failure_regimes') or [],
                'objective_constraint_dependency': ((iteration.get('research_judgment') or {}).get('factor_investing_framework') or {}).get('objective_constraint_dependency'),
                'constraint_sources': ((iteration.get('research_judgment') or {}).get('factor_investing_framework') or {}).get('constraint_sources') or [],
            },
            'why_revision_is_more_reasonable': [
                '这次修改先围绕收益来源假说展开，而不是只为了美化单一 metric。',
                '它保留原始因子语义，只增强更可能承载收益来源的部分，因此可解释性与可回退性更好。',
                '若修改后结果改善，我们可以更有把握地说改善来自收益来源强化，而不是偶然调参。',
            ],
            'questions_for_human': [
                '这轮是否允许并行开多个表达式分支：一个 exploit 参数搜索、一个 explore 公式突变、一个机制假说挑战？',
                '你更想先批准哪一类 Step3B 修改：方向/符号修订、窗口参数搜索、输入比例重写，还是线性化/截尾？',
                '是否有你特别想加入的行业/市值分桶诊断？这些只能用于检验 long-side 单调性，不能作为 decile 交易方案。',
            ],
        },
        'approval': {
            'status': 'pending',
            'approved_by': None,
            'approved_at_utc': None,
            'approver_notes': None,
        },
        'created_at_utc': utc_now(),
        'producer': 'step6',
    }

    out = OBJ / 'research_iteration_master' / f'revision_proposal__{report_id}.json'
    write_json(out, proposal)
