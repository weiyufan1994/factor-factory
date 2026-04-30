#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OBJECTS = REPO_ROOT / 'objects'
DEFAULT_OUTPUT = REPO_ROOT / 'knowledge' / '因子工厂'

DIR_DASHBOARDS = '仪表盘'
DIR_FACTORS_ALL = '普通因子库'
DIR_FACTORS_OFFICIAL = '正式因子库'
DIR_KNOWLEDGE = '知识库'
DIR_ITERATIONS = '研究迭代'
DIR_AGENT = 'Agent'


def load_json(path: Path) -> dict[str, Any]:
    with path.open('r', encoding='utf-8') as fh:
        return json.load(fh)


def dump_frontmatter(meta: dict[str, Any]) -> str:
    lines = ['---']
    for key, value in meta.items():
        if isinstance(value, list):
            lines.append(f'{key}:')
            for item in value:
                lines.append(f'  - {json.dumps(item, ensure_ascii=False)}')
        else:
            lines.append(f'{key}: {json.dumps(value, ensure_ascii=False)}')
    lines.append('---')
    return '\n'.join(lines)


def bullets(title: str, values: list[Any]) -> str:
    out = [f'## {title}']
    if not values:
        out.append('- (none)')
    else:
        for item in values:
            out.append(f'- {item}')
    return '\n'.join(out)


def kv_section(title: str, mapping: dict[str, Any]) -> str:
    out = [f'## {title}']
    if not mapping:
        out.append('- (none)')
        return '\n'.join(out)
    for key, value in mapping.items():
        out.append(f'- `{key}`: `{value}`')
    return '\n'.join(out)


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + '\n', encoding='utf-8')
    print(f'[WRITE] {path}')


def render_factor_record(data: dict[str, Any], knowledge_exists: bool, iteration_exists: bool) -> str:
    report_id = data['report_id']
    factor_id = data['factor_id']
    metrics = data.get('headline_metrics', {})
    meta = {
        'report_id': report_id,
        'factor_id': factor_id,
        'decision': data.get('decision'),
        'iteration_no': data.get('iteration_no'),
        'run_status': data.get('run_status'),
        'final_status': data.get('final_status'),
        'tags': ['factor', 'library_all', str(data.get('decision', 'unknown'))],
    }
    links = []
    if knowledge_exists:
        links.append(f'- [[{DIR_KNOWLEDGE}/{report_id}|Knowledge Record]]')
    if iteration_exists:
        links.append(f'- [[{DIR_ITERATIONS}/{report_id}|Research Iteration]]')
    metric_lines = ['## Headline Metrics']
    if metrics:
        for k, v in metrics.items():
            metric_lines.append(f'- `{k}`: `{v}`')
    else:
        metric_lines.append('- (none)')
    sections = [
        dump_frontmatter(meta),
        f'# {factor_id} ({report_id})',
        '## Summary',
        f'- decision: `{data.get("decision")}`',
        f'- iteration_no: `{data.get("iteration_no")}`',
        f'- run_status: `{data.get("run_status")}`',
        f'- final_status: `{data.get("final_status")}`',
        *metric_lines,
        bullets('Strengths', data.get('strengths', [])),
        bullets('Weaknesses', data.get('weaknesses', [])),
        bullets('Risks', data.get('risks', [])),
        kv_section('Framework', {
            'factor_family': data.get('factor_family'),
            'monetization_model': data.get('monetization_model'),
            'bias_type': data.get('bias_type'),
            'objective_constraint_dependency': data.get('objective_constraint_dependency'),
            'crowding_risk': data.get('crowding_risk'),
        }),
        bullets('Constraint Sources', data.get('constraint_sources', [])),
        bullets('Expected Failure Regimes', data.get('expected_failure_regimes', [])),
        bullets('Improvement Frontier', data.get('improvement_frontier', [])),
        bullets('Review Checklist', data.get('review_checklist', [])),
        bullets('Revision Principles', data.get('revision_principles', [])),
        '## Links',
        *(links or ['- (none)']),
    ]
    return '\n\n'.join(sections)


def render_knowledge_record(data: dict[str, Any], factor_exists: bool, iteration_exists: bool) -> str:
    report_id = data['report_id']
    factor_id = data['factor_id']
    meta = {
        'report_id': report_id,
        'factor_id': factor_id,
        'decision': data.get('decision'),
        'tags': ['knowledge', str(data.get('decision', 'unknown'))],
    }
    links = []
    if factor_exists:
        links.append(f'- [[{DIR_FACTORS_ALL}/{report_id}|Factor Record]]')
    if iteration_exists:
        links.append(f'- [[{DIR_ITERATIONS}/{report_id}|Research Iteration]]')
    sections = [
        dump_frontmatter(meta),
        f'# Knowledge Record: {factor_id} ({report_id})',
        f'- decision: `{data.get("decision")}`',
        kv_section('Framework', {
            'factor_family': data.get('factor_family'),
            'monetization_model': data.get('monetization_model'),
            'bias_type': data.get('bias_type'),
            'objective_constraint_dependency': data.get('objective_constraint_dependency'),
            'crowding_risk': data.get('crowding_risk'),
            'capacity_constraints': data.get('capacity_constraints'),
            'implementation_risk': data.get('implementation_risk'),
        }),
        f'## Return Source Hypothesis\n- {data.get("return_source_hypothesis") or "(none)"}',
        bullets('Constraint Sources', data.get('constraint_sources', [])),
        bullets('Success Patterns', data.get('success_patterns', [])),
        bullets('Failure Patterns', data.get('failure_patterns', [])),
        bullets('Expected Failure Regimes', data.get('expected_failure_regimes', [])),
        bullets('Modification Hypotheses', data.get('modification_hypotheses', [])),
        bullets('Improvement Frontier', data.get('improvement_frontier', [])),
        bullets('Review Checklist', data.get('review_checklist', [])),
        bullets('Revision Principles', data.get('revision_principles', [])),
        kv_section('DD · View · Edge · Trade', data.get('dd_view_edge_trade', {})),
        bullets('Research Commentary', data.get('research_commentary', [])),
        '## Links',
        *(links or ['- (none)']),
    ]
    return '\n\n'.join(sections)


def render_iteration_record(data: dict[str, Any], factor_exists: bool, knowledge_exists: bool) -> str:
    report_id = data['report_id']
    factor_id = data['factor_id']
    evidence = data.get('evidence_summary', {})
    judgment = data.get('research_judgment', {})
    framework = judgment.get('factor_investing_framework', {})
    loop = data.get('loop_action', {})
    metrics = evidence.get('headline_metrics', {})
    meta = {
        'report_id': report_id,
        'factor_id': factor_id,
        'decision': judgment.get('decision'),
        'iteration_no': data.get('iteration_no'),
        'tags': ['iteration', str(judgment.get('decision', 'unknown'))],
    }
    links = []
    if factor_exists:
        links.append(f'- [[{DIR_FACTORS_ALL}/{report_id}|Factor Record]]')
    if knowledge_exists:
        links.append(f'- [[{DIR_KNOWLEDGE}/{report_id}|Knowledge Record]]')
    metric_lines = ['## Evidence Metrics']
    if metrics:
        for k, v in metrics.items():
            metric_lines.append(f'- `{k}`: `{v}`')
    else:
        metric_lines.append('- (none)')
    sections = [
        dump_frontmatter(meta),
        f'# Research Iteration: {factor_id} ({report_id})',
        '## Evidence Summary',
        f'- source_case_status: `{data.get("source_case_status")}`',
        f'- run_status: `{evidence.get("run_status")}`',
        f'- backend_statuses: `{evidence.get("backend_statuses")}`',
        *metric_lines,
        bullets('Step5 Lessons', evidence.get('step5_lessons', [])),
        bullets('Step5 Next Actions', evidence.get('step5_next_actions', [])),
        '## Research Judgment',
        f'- decision: `{judgment.get("decision")}`',
        f'- thesis: {judgment.get("thesis")}',
        bullets('Strengths', judgment.get('strengths', [])),
        bullets('Weaknesses', judgment.get('weaknesses', [])),
        bullets('Risks', judgment.get('risks', [])),
        kv_section('Framework', {
            'factor_family': framework.get('factor_family'),
            'monetization_model': framework.get('monetization_model'),
            'bias_type': framework.get('bias_type'),
            'objective_constraint_dependency': framework.get('objective_constraint_dependency'),
            'crowding_risk': framework.get('crowding_risk'),
            'capacity_constraints': framework.get('capacity_constraints'),
            'implementation_risk': framework.get('implementation_risk'),
        }),
        f'## Return Source Hypothesis\n- {framework.get("return_source_hypothesis") or "(none)"}',
        bullets('Constraint Sources', framework.get('constraint_sources', [])),
        bullets('Expected Failure Regimes', framework.get('expected_failure_regimes', [])),
        bullets('Improvement Frontier', framework.get('improvement_frontier', [])),
        bullets('Review Checklist', framework.get('review_checklist', [])),
        bullets('Revision Principles', framework.get('revision_principles', [])),
        kv_section('DD · View · Edge · Trade', framework.get('dd_view_edge_trade', {})),
        bullets('Research Commentary', framework.get('research_commentary', [])),
        '## Loop Action',
        f'- should_modify_step3b: `{loop.get("should_modify_step3b")}`',
        f'- next_runner: `{loop.get("next_runner")}`',
        f'- stop_reason: `{loop.get("stop_reason")}`',
        bullets('Modification Targets', loop.get('modification_targets', [])),
        '## Links',
        *(links or ['- (none)']),
    ]
    return '\n\n'.join(sections)


def render_index(title: str, rows: list[str]) -> str:
    body = ['# ' + title, '']
    body.extend(rows or ['- (empty)'])
    return '\n'.join(body) + '\n'


def render_agent_note() -> str:
    return '\n\n'.join([
        dump_frontmatter({
            'agent': 'FactorForge Researcher',
            'owner': 'Bernard on Mac',
            'tags': ['agent', 'factorforge', 'researcher'],
        }),
        '# FactorForge Researcher Agent',
        '## 身份',
        '- 承担者：Mac 上的 Bernard',
        '- 职责：全流程因子研究员，而不是批量脚本执行器。',
        '- 默认知识库：本 Obsidian vault `因子工厂`、结构化 JSON 对象、retrieval index、Mac 本地 BGE-M3 embedding 服务。',
        '## 默认规则',
        '- 每个正式因子研究都必须 researcher-led。',
        '- Step1/2 要理解研报或论文作者的思路。',
        '- Step3 要检查数据和代码是否忠实保留原 thesis。',
        '- Step4 要解释 metric、图表、组合收益和交易可实现性。',
        '- Step5/6 要写入普通因子库、正式因子库和知识库。',
        '- 失败因子也必须沉淀失败原因和可复用经验。',
        '- 需要迭代时，先写 revision brief，再回 Step3B。',
        '## 关键入口',
        f'- [[{DIR_FACTORS_ALL}/|普通因子库]]',
        f'- [[{DIR_FACTORS_OFFICIAL}/|正式因子库]]',
        f'- [[{DIR_KNOWLEDGE}/|知识库]]',
        f'- [[{DIR_ITERATIONS}/|研究迭代]]',
    ])


def main() -> None:
    ap = argparse.ArgumentParser(description='Export factor library / knowledge base objects into an Obsidian-friendly vault.')
    ap.add_argument('--output-root', default=str(DEFAULT_OUTPUT), help='Vault output root (default: knowledge/因子工厂)')
    args = ap.parse_args()

    out = Path(args.output_root).resolve()
    factor_dir = OBJECTS / 'factor_library_all'
    official_dir = OBJECTS / 'factor_library_official'
    knowledge_dir = OBJECTS / 'research_knowledge_base'
    iteration_dir = OBJECTS / 'research_iteration_master'

    factor_files = sorted(factor_dir.glob('factor_record__*.json'))
    official_files = sorted(official_dir.glob('factor_record__*.json')) if official_dir.exists() else []
    knowledge_files = sorted(knowledge_dir.glob('knowledge_record__*.json'))
    iteration_files = sorted(iteration_dir.glob('research_iteration_master__*.json'))

    factor_ids = {p.stem.replace('factor_record__', '') for p in factor_files}
    knowledge_ids = {p.stem.replace('knowledge_record__', '') for p in knowledge_files}
    iteration_ids = {p.stem.replace('research_iteration_master__', '') for p in iteration_files}

    factor_rows = []
    for path in factor_files:
        rid = path.stem.replace('factor_record__', '')
        data = load_json(path)
        note = out / DIR_FACTORS_ALL / f'{rid}.md'
        write(note, render_factor_record(data, rid in knowledge_ids, rid in iteration_ids))
        factor_rows.append(f'- [[{DIR_FACTORS_ALL}/{rid}|{rid}]] · `{data.get("factor_id")}` · `{data.get("decision")}`')

    official_rows = []
    for path in official_files:
        rid = path.stem.replace('factor_record__', '')
        data = load_json(path)
        note = out / DIR_FACTORS_OFFICIAL / f'{rid}.md'
        write(note, render_factor_record(data, rid in knowledge_ids, rid in iteration_ids))
        official_rows.append(f'- [[{DIR_FACTORS_OFFICIAL}/{rid}|{rid}]] · `{data.get("factor_id")}` · `{data.get("decision")}`')

    knowledge_rows = []
    for path in knowledge_files:
        rid = path.stem.replace('knowledge_record__', '')
        data = load_json(path)
        note = out / DIR_KNOWLEDGE / f'{rid}.md'
        write(note, render_knowledge_record(data, rid in factor_ids, rid in iteration_ids))
        knowledge_rows.append(f'- [[{DIR_KNOWLEDGE}/{rid}|{rid}]] · `{data.get("factor_id")}` · `{data.get("decision")}`')

    iteration_rows = []
    for path in iteration_files:
        rid = path.stem.replace('research_iteration_master__', '')
        data = load_json(path)
        note = out / DIR_ITERATIONS / f'{rid}.md'
        write(note, render_iteration_record(data, rid in factor_ids, rid in knowledge_ids))
        iteration_rows.append(f'- [[{DIR_ITERATIONS}/{rid}|{rid}]] · `{data.get("factor_id")}` · `iter {data.get("iteration_no")}` · `{data.get("research_judgment", {}).get("decision")}`')

    write(out / DIR_DASHBOARDS / '普通因子库.md', render_index('普通因子库', factor_rows))
    write(out / DIR_DASHBOARDS / '正式因子库.md', render_index('正式因子库', official_rows))
    write(out / DIR_DASHBOARDS / '知识库.md', render_index('知识库', knowledge_rows))
    write(out / DIR_DASHBOARDS / '研究迭代.md', render_index('研究迭代', iteration_rows))
    write(out / DIR_AGENT / 'FactorForge Researcher Agent.md', render_agent_note())
    write(
        out / 'Home.md',
        render_index(
            '因子工厂',
            [
                f'- [[{DIR_AGENT}/FactorForge Researcher Agent|FactorForge Researcher Agent]]',
                f'- [[{DIR_DASHBOARDS}/普通因子库|普通因子库]]',
                f'- [[{DIR_DASHBOARDS}/正式因子库|正式因子库]]',
                f'- [[{DIR_DASHBOARDS}/知识库|知识库]]',
                f'- [[{DIR_DASHBOARDS}/研究迭代|研究迭代]]',
            ],
        ),
    )


if __name__ == '__main__':
    main()
