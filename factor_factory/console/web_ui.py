from __future__ import annotations

import json
import secrets
from html import escape
from typing import Any

from factor_factory.console.math_render import render_equation_statement
from factor_factory.console.models import PILOT_MODEL, ResearchJob, ResearchMessage


ACTIVE_STATUSES = {"QUEUED", "ALLOCATING", "RESEARCHING", "VERIFYING"}
NON_RESUMABLE_SECURITY_ERRORS = {
    "BLOCK_FACTORFORGE_CONSOLE_AGENT_WRITE_SCOPE_INVALID",
    "BLOCK_FACTORFORGE_CONSOLE_ISOLATION_AUDIT_FAILED",
    "BLOCK_FACTORFORGE_CONSOLE_CREDENTIAL_REGISTRY_INVALID",
    "BLOCK_FACTORFORGE_CONSOLE_RESUME_TRUST_INVALID",
    "BLOCK_FACTORFORGE_CONSOLE_AGENT_ORPHANED_WRITER",
    "BLOCK_FACTORFORGE_CONSOLE_CREDENTIAL_CLEANUP_FAILED",
}
GENERIC_RESUME_DISABLED_ERRORS = {
    "FACTORFORGE_CONSOLE_EXPLICIT_HUMAN_DECISION_REQUIRED",
}


STATUS_LABELS = {
    "QUEUED": "排队中",
    "ALLOCATING": "创建隔离工作区",
    "RESEARCHING": "研究中",
    "VERIFYING": "核验证据",
    "REVIEW_REQUIRED": "等待复核",
    "COMPLETED": "已完成",
    "BLOCKED": "已阻断",
    "FAILED": "运行失败",
    "CANCELLED": "已取消",
}


def render_login(error: str = "") -> str:
    error_html = f'<p class="form-error">{escape(error)}</p>' if error else ""
    body = f"""
    <main class="login-shell">
      <section class="login-panel">
        <p class="brand-mark">FACTOR FORGE</p>
        <h1>研究控制台</h1>
        <p class="muted">邀请测试版</p>
        {error_html}
        <form method="post" action="/login" class="login-form">
          <label for="password">访问口令</label>
          <input id="password" name="password" type="password" autocomplete="current-password" required autofocus>
          <button type="submit">进入控制台</button>
        </form>
      </section>
    </main>
    """
    return _page("登录 | Factor Forge", body, public=True)


def render_dashboard(jobs: list[ResearchJob], csrf_token: str) -> str:
    active = sum(job.execution_status in ACTIVE_STATUSES for job in jobs)
    waiting = sum(job.execution_status == "REVIEW_REQUIRED" for job in jobs)
    completed = sum(job.execution_status == "COMPLETED" for job in jobs)
    blocked = sum(job.execution_status in {"BLOCKED", "FAILED"} for job in jobs)
    body = [
        _shell_header("研究任务", csrf_token),
        '<main class="workspace">',
        '<section class="page-heading">',
        '<div><p class="eyebrow">RESEARCH OPERATIONS</p><h1>因子研究任务</h1></div>',
        '<a class="button primary" href="#new-research">发起研究</a>',
        '</section>',
        '<section class="status-strip" aria-label="任务状态摘要">',
        _status_stat("运行中", active, "blue"),
        _status_stat("等待复核", waiting, "amber"),
        _status_stat("已完成", completed, "green"),
        _status_stat("阻断或失败", blocked, "red"),
        '</section>',
        '<section class="job-section"><div class="section-heading"><h2>任务队列</h2><p>首版并发固定为 1</p></div>',
        _job_list(jobs),
        '</section>',
        '<section id="new-research" class="new-research">',
        '<div class="section-heading"><h2>发起完整研究</h2><p>研究路径和数据路径由服务器分配</p></div>',
        _research_form(csrf_token),
        '</section>',
        '</main>',
        _poll_script(None, jobs[0].updated_at_utc if jobs else "") if active else "",
    ]
    return _page("研究任务 | Factor Forge", "\n".join(body))


def render_job(job: ResearchJob, messages: list[ResearchMessage], csrf_token: str) -> str:
    result = job.result or {}
    body = [
        _shell_header("研究详情", csrf_token),
        '<main class="workspace">',
        '<nav class="breadcrumbs"><a href="/">研究任务</a><span>/</span><span>任务详情</span></nav>',
        '<section class="detail-heading">',
        '<div>',
        f'<p class="eyebrow">{escape(job.factor_id)}</p>',
        f'<h1>{escape(job.request.title)}</h1>',
        f'<p class="idea-summary">{escape(job.request.hypothesis)}</p>',
        '</div>',
        _status_badge(job.execution_status),
        '</section>',
        _identity_band(job),
        _workspace_nav(),
        _conversation_section(job, messages, result, csrf_token),
        _backtest_center_section(job, result),
        _stage_timeline(job, result),
        _decision_panel(job, result, csrf_token),
        _math_notebook_section(result),
        _data_implementation_section(result),
        _council_section(result),
        _artifact_section(job, result),
        _research_notebook_section(result),
        '</main>',
        _poll_script(job.job_id, job.updated_at_utc) if job.execution_status in ACTIVE_STATUSES else "",
    ]
    return _page(f"{job.request.title} | Factor Forge", "\n".join(item for item in body if item))


def render_not_found(message: str = "没有找到该研究任务") -> str:
    return _page(
        "未找到 | Factor Forge",
        f'<main class="login-shell"><section class="login-panel"><h1>未找到</h1><p>{escape(message)}</p><a class="button primary" href="/">返回任务列表</a></section></main>',
        public=True,
    )


def _shell_header(title: str, csrf_token: str) -> str:
    return f"""
    <header class="topbar">
      <a class="brand" href="/"><span class="brand-symbol">FF</span><span>Factor Forge</span></a>
      <div class="topbar-right"><span class="topbar-title">{escape(title)}</span>
        <form method="post" action="/logout" class="inline-form">
          <input type="hidden" name="csrf" value="{escape(csrf_token)}">
          <button class="quiet-button" type="submit">退出</button>
        </form>
      </div>
    </header>
    """


def _research_form(csrf_token: str) -> str:
    return f"""
    <form method="post" action="/research" class="research-form">
      <input type="hidden" name="csrf" value="{escape(csrf_token)}">
      <div class="field span-2"><label for="title">研究名称</label><input id="title" name="title" maxlength="160" placeholder="例如：隔夜消息扩散与开盘确认" required></div>
      <div class="field"><label for="factor-id">因子 ID（可选）</label><input id="factor-id" name="factor_id_hint" maxlength="64" placeholder="由系统生成也可以"></div>
      <div class="field"><label for="input-kind">输入类型</label><select id="input-kind" name="content_kind"><option value="hypothesis">经济假设</option><option value="report">研报摘录</option><option value="formula">公式 / 算子</option><option value="code">代码</option></select></div>
      <div class="field"><label for="model">研究模型</label><select id="model" name="model"><option value="{escape(PILOT_MODEL)}">DeepSeek V4 Flash</option></select></div>
      <div class="field span-2"><label for="hypothesis">研究输入</label><textarea id="hypothesis" name="hypothesis" rows="8" maxlength="20000" placeholder="粘贴经济假设、研报内容、公式或代码。请同时说明现象、可能的付款方、信息形成时间和可证伪条件。" required></textarea></div>
      <div class="field"><label for="universe">股票池</label><select id="universe" name="universe"><option value="a_share_all">全部 A 股（Data API 清洗口径）</option></select></div>
      <div class="field"><label>收益观察期</label><input type="hidden" name="forward_horizon" value="1d"><div class="fixed-contract">收盘后形成信号 → 下一交易日收盘成交 → 再下一交易日收盘退出（Pilot 固定）</div></div>
      <div class="field"><label for="sample-start">样本开始</label><input id="sample-start" name="sample_start" type="date" value="2016-01-01" required></div>
      <div class="field"><label for="sample-end">样本结束</label><input id="sample-end" name="sample_end" type="date" value="2025-07-11" required></div>
      <div class="field"><label>交易成本模型</label><input type="hidden" name="transaction_cost_bps" value="30"><div class="fixed-contract">换手 × 30 bps（Pilot 固定）</div></div>
      <div class="form-actions span-2"><p>提交后异步运行 Ultimate；每个因子分配独立 Git worktree，Data API 只读。</p><button class="button primary" type="submit">开始研究</button></div>
    </form>
    """


def _job_list(jobs: list[ResearchJob]) -> str:
    if not jobs:
        return '<div class="empty-state"><h3>还没有研究任务</h3><p>从下方提交第一个因子想法。</p></div>'
    rows = []
    for job in jobs:
        verdict = job.factor_verdict if job.factor_verdict != "UNKNOWN" else "尚无结论"
        rows.append(
            f"""
            <a class="job-row" href="/research/{escape(job.job_id)}">
              <div class="job-main"><strong>{escape(job.request.title)}</strong><span>{escape(job.factor_id)} · {escape(job.report_id)}</span></div>
              <div class="job-stage">{escape(_stage_label(job.current_stage))}</div>
              <div class="job-verdict verdict-{escape(job.factor_verdict.lower())}">{escape(verdict)}</div>
              <div>{_status_badge(job.execution_status)}</div>
              <time data-time="{escape(job.updated_at_utc)}">{escape(job.updated_at_utc[:16].replace('T', ' '))}</time>
            </a>
            """
        )
    return '<div class="job-table"><div class="job-table-head"><span>研究</span><span>阶段</span><span>因子结论</span><span>运行状态</span><span>更新时间</span></div>' + "".join(rows) + "</div>"


def _identity_band(job: ResearchJob) -> str:
    return f"""
    <section class="identity-band">
      <div><span>样本</span><strong>{escape(job.request.sample_start)} 至 {escape(job.request.sample_end)}</strong></div>
      <div><span>股票池</span><strong>{escape(job.request.universe)}</strong></div>
      <div><span>收益期</span><strong>{escape(job.request.forward_horizon)}</strong></div>
      <div><span>交易成本</span><strong>{job.request.transaction_cost_bps:g} bps</strong></div>
      <div><span>模型 / 隔离</span><strong>{escape(job.request.model or PILOT_MODEL)} · {'独立 worktree' if job.workspace_path else '等待分配'}</strong></div>
    </section>
    """


def _workspace_nav() -> str:
    return """
    <nav class="workspace-nav" aria-label="研究工作区">
      <a href="#conversation">Chatbox</a>
      <a href="#backtest">回测中心</a>
      <a href="#math">Math</a>
      <a href="#notebook">Research Notebook</a>
    </nav>
    """


def _conversation_section(
    job: ResearchJob,
    messages: list[ResearchMessage],
    result: dict[str, Any],
    csrf_token: str,
) -> str:
    message_rows = []
    kind_labels = {
        "hypothesis": "经济假设",
        "report": "研报摘录",
        "formula": "公式 / 算子",
        "code": "代码",
        "decision": "研究方向",
    }
    for message in messages:
        content = escape(message.content)
        if message.content_kind in {"formula", "code"}:
            content_html = f'<pre class="message-code">{content}</pre>'
        else:
            content_html = f'<p>{content}</p>'
        message_rows.append(
            f"""
            <article class="chat-message user-message">
              <header><strong>你</strong><span>{escape(kind_labels.get(message.content_kind, message.content_kind))} · #{message.sequence_no}</span></header>
              {content_html}
            </article>
            """
        )
    status_text = str(result.get("summary") or job.error_message or "研究任务已进入异步执行队列。")
    message_rows.append(
        f"""
        <article class="chat-message forge-message">
          <header><strong>Factor Forge</strong><span>{escape(STATUS_LABELS.get(job.execution_status, job.execution_status))}</span></header>
          <p>{escape(status_text)}</p>
        </article>
        """
    )
    can_resume = bool(
        job.execution_status in {"REVIEW_REQUIRED", "BLOCKED", "FAILED"}
        and job.workspace_path
        and result.get("host_attestation_id")
        and job.error_code not in NON_RESUMABLE_SECURITY_ERRORS
        and job.error_code not in GENERIC_RESUME_DISABLED_ERRORS
    )
    resume_button = (
        '<button class="button primary" type="submit" name="message_action" value="save_and_resume">保存并继续研究</button>'
        if can_resume
        else ""
    )
    return f"""
    <section id="conversation" class="content-section conversation-section">
      <div class="section-heading"><div><p class="section-kicker">INPUT WORKSPACE</p><h2>Chatbox</h2></div><p>消息在下一次代理运行开始时形成哈希快照</p></div>
      <div class="chat-thread">{''.join(message_rows)}</div>
      <form method="post" action="/research/{escape(job.job_id)}/messages" class="message-composer">
        <input type="hidden" name="csrf" value="{escape(csrf_token)}">
        <input type="hidden" name="idempotency_key" value="web-{secrets.token_hex(16)}">
        <div class="field"><label for="message-kind">输入类型</label><select id="message-kind" name="content_kind"><option value="decision">研究方向</option><option value="hypothesis">经济假设</option><option value="report">研报摘录</option><option value="formula">公式 / 算子</option><option value="code">代码</option></select></div>
        <div class="field composer-input"><label for="message-content">继续补充</label><textarea id="message-content" name="content" rows="5" maxlength="20000" placeholder="补充证据、反例、数学方向或 Council 应检验的问题。代码只作为研究文本，不会在宿主机执行。" required></textarea></div>
        <div class="composer-actions"><span>{escape(job.request.model or PILOT_MODEL)}</span><button class="button secondary" type="submit" name="message_action" value="save">保存上下文</button>{resume_button}</div>
      </form>
    </section>
    """


def _research_notebook_section(result: dict[str, Any]) -> str:
    notebook = result.get("research_notebook") if isinstance(result.get("research_notebook"), dict) else {}
    if not notebook:
        return '<section id="notebook" class="content-section"><div class="section-heading"><h2>Research Notebook</h2><p>尚未形成研究推理记录</p></div></section>'
    stages = notebook.get("stages") if isinstance(notebook.get("stages"), list) else []
    stage_html = []
    for index, stage in enumerate(stages, start=1):
        if not isinstance(stage, dict):
            continue
        stage_html.append(
            f"""
            <article class="notebook-step">
              <div class="notebook-index">{index:02d}</div>
              <div><h3>{escape(str(stage.get('title') or stage.get('id') or 'Research step'))}</h3>{_structured_value(stage.get('content'))}</div>
            </article>
            """
        )
    source = str(notebook.get("source_label") or "UNKNOWN SOURCE")
    revision = notebook.get("revision_number")
    revision_text = f" · revision {escape(str(revision))}" if revision not in (None, "") else ""
    return f"""
    <section id="notebook" class="content-section notebook-section">
      <div class="section-heading"><div><p class="section-kicker">AUDITABLE REASONING TRACE</p><h2>Research Notebook</h2></div><span class="evidence-badge badge-agent">{escape(source)}{revision_text}</span></div>
      <p class="section-note">展示经济假设、模型选择、估计量映射、证据更新和被证伪路线；不是模型的私有原始思维链。</p>
      <div class="notebook-flow">{''.join(stage_html)}</div>
    </section>
    """


def _math_notebook_section(result: dict[str, Any]) -> str:
    notebook = result.get("math_notebook") if isinstance(result.get("math_notebook"), dict) else {}
    if not notebook:
        return '<section id="math" class="content-section"><div class="section-heading"><h2>Math</h2><p>尚未形成结构化数学对象</p></div></section>'
    definitions = notebook.get("definitions") if isinstance(notebook.get("definitions"), dict) else {}
    definition_html = "".join(
        f'<div><dt>{escape(str(key).replace("_", " "))}</dt><dd>{escape(_format_value(value, long=True))}</dd></div>'
        for key, value in definitions.items()
    )
    equations = notebook.get("equations") if isinstance(notebook.get("equations"), list) else []
    equation_html = []
    for index, equation in enumerate(equations, start=1):
        if not isinstance(equation, dict):
            continue
        equation_html.append(
            f"""
            <figure class="equation-block">
              <figcaption>{escape(str(equation.get('title') or 'Equation'))}</figcaption>
              <div class="equation-expression">{render_equation_statement(str(equation.get('expression') or ''))}</div>
              <span class="equation-number">({index})</span>
            </figure>
            """
        )
    derivations = notebook.get("derivation_steps") if isinstance(notebook.get("derivation_steps"), list) else []
    derivation_html = []
    for item in derivations:
        if not isinstance(item, dict):
            continue
        derivation_html.append(
            f'<li><span>{escape(str(item.get("step") or ""))}</span><div><strong>{escape(str(item.get("title") or ""))}</strong>{_structured_value(item.get("statement"))}</div></li>'
        )
    falsifiers = _string_list(notebook.get("falsification_tests"))
    return f"""
    <section id="math" class="content-section math-section">
      <div class="section-heading"><div><p class="section-kicker">MODEL AND DERIVATION</p><h2>Math</h2></div><span class="evidence-badge badge-agent">{escape(str(notebook.get('evidence_class') or 'AGENT CLAIM'))}</span></div>
      <div class="math-chapter"><h3>Definitions</h3><dl class="math-definitions">{definition_html}</dl></div>
      <div class="math-chapter"><h3>Equations</h3>{''.join(equation_html) or '<p class="missing-proof">正式产物未提供可展示的方程。</p>'}</div>
      <div class="math-chapter"><h3>Derivation</h3><ol class="derivation-list">{''.join(derivation_html)}</ol></div>
      {_bullet_group('Falsification tests', falsifiers)}
    </section>
    """


def _backtest_center_section(job: ResearchJob, result: dict[str, Any]) -> str:
    center = result.get("backtest_center") if isinstance(result.get("backtest_center"), dict) else {}
    metrics = center.get("metrics") if isinstance(center.get("metrics"), dict) else (
        result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    )
    evidence = result.get("metric_evidence") if isinstance(result.get("metric_evidence"), dict) else {}
    metric_cells = "".join(
        _metric_cell(
            _metric_label(key),
            value,
            evidence.get(key) if isinstance(evidence.get(key), dict) else {},
            metric_key=key,
        )
        for key, value in list(metrics.items())[:18]
    )
    artifacts = {
        str(item.get("artifact_id") or ""): item
        for item in (result.get("artifacts") or [])
        if isinstance(item, dict)
    }
    charts = center.get("charts") if isinstance(center.get("charts"), dict) else {}
    evidence_class = str(center.get("evidence_class") or "FORMAL UNVERIFIED")
    consistency = center.get("consistency") if isinstance(center.get("consistency"), dict) else {}
    conflict = consistency.get("status") == "CONFLICT" or evidence_class == "EVIDENCE CONFLICT"
    chart_evidence_label = "EVIDENCE CONFLICT" if conflict else evidence_class
    chart_evidence_class = "chart-evidence-conflict" if conflict else ""
    chart_order = [
        ("gross_nav_chart", "多头 Gross NAV"),
        ("net_nav_chart", "多头 Net NAV"),
        ("quantile_nav_chart", "Decile NAV"),
        ("long_short_diagnostic_chart", "Long-short diagnostic NAV"),
        ("rank_ic_chart", "Rank IC 时序"),
        ("pearson_ic_chart", "Pearson IC 时序"),
        ("coverage_chart", "样本覆盖"),
        ("quantile_counts_chart", "Decile 样本数量"),
    ]
    figures = []
    for role, label in chart_order:
        artifact_id = str(charts.get(role) or "")
        if not artifact_id or artifact_id not in artifacts:
            continue
        href = f"/artifact/{escape(job.job_id)}/{_url_path(artifact_id)}"
        figures.append(
            f'<figure><a href="{href}" target="_blank" rel="noopener"><img src="{href}" alt="{escape(label)}"></a><figcaption><strong>{escape(label)}</strong><span class="{chart_evidence_class}">{escape(chart_evidence_label)}</span></figcaption></figure>'
        )
    annual = center.get("annual_returns") if isinstance(center.get("annual_returns"), list) else []
    annual_rows = "".join(
        f'<tr><th>{escape(str(item.get("year") or ""))}</th><td>{_format_percent(item.get("gross_return"))}</td><td>{_format_percent(item.get("net_return"))}</td></tr>'
        for item in annual if isinstance(item, dict)
    )
    module_status = center.get("module_status") if isinstance(center.get("module_status"), dict) else {}
    monthly = center.get("monthly_returns") if isinstance(center.get("monthly_returns"), list) else []
    quantile = center.get("quantile_summary") if isinstance(center.get("quantile_summary"), list) else []
    drawdown = center.get("drawdown") if isinstance(center.get("drawdown"), dict) else {}
    turnover = center.get("turnover_profile") if isinstance(center.get("turnover_profile"), dict) else {}
    provenance = center.get("provenance") if isinstance(center.get("provenance"), dict) else {}
    return f"""
    <section id="backtest" class="content-section backtest-section">
      <div class="section-heading"><div><p class="section-kicker">FORMAL EVALUATION</p><h2>回测中心</h2></div><span class="evidence-badge {'badge-conflict' if conflict else 'badge-formal'}">{escape(evidence_class)}</span></div>
      <p class="section-note">只展示当前 report 的正式 Step4 证据；派生统计绑定原始文件 SHA。页面不会用汇总指标补画这些结果。</p>
      <div class="metric-grid">{metric_cells or '<p class="empty-inline">尚未生成正式指标</p>'}</div>
      <div class="backtest-band"><h3>证据覆盖</h3>{_module_status_table(module_status)}</div>
      <div class="backtest-band"><h3>NAV 与分组表现</h3><div class="chart-grid">{''.join(figures) or '<p class="missing-proof">尚未发布可核验的 NAV / IC 时序图。</p>'}</div></div>
      <div class="backtest-band"><h3>分年度收益率</h3><div class="table-scroll"><table class="annual-table"><thead><tr><th>年份</th><th>Gross</th><th>Net (30 bps)</th></tr></thead><tbody>{annual_rows or '<tr><td colspan="3">未生成正式年度收益时序</td></tr>'}</tbody></table></div></div>
      <div class="backtest-band"><h3>分月收益矩阵</h3>{_monthly_return_table(monthly, annual)}</div>
      <div class="backtest-band"><h3>Decile 诊断</h3>{_quantile_summary_table(quantile)}</div>
      <div class="backtest-band"><h3>回撤与换手</h3>{_risk_turnover_tables(drawdown, turnover)}</div>
      {_consistency_panel(consistency)}
      <div class="backtest-band"><h3>证据来源</h3>{_backtest_provenance_table(job, provenance)}</div>
    </section>
    """


def _module_status_table(module_status: dict[str, Any]) -> str:
    if not module_status:
        return '<p class="missing-proof">尚未生成模块覆盖合同。</p>'
    labels = {
        "available": "AVAILABLE",
        "not_produced": "NOT PRODUCED",
        "invalid_evidence": "INVALID EVIDENCE",
        "evidence_conflict": "EVIDENCE CONFLICT",
    }
    rows = "".join(
        f'<tr><th>{escape(_metric_label(key))}</th><td><span class="module-state module-{escape(str(value))}">{escape(labels.get(str(value), str(value).upper()))}</span></td></tr>'
        for key, value in module_status.items()
    )
    return f'<div class="table-scroll module-table"><table><thead><tr><th>模块</th><th>正式状态</th></tr></thead><tbody>{rows}</tbody></table></div>'


def _monthly_return_table(monthly: list[Any], annual: list[Any]) -> str:
    valid = [item for item in monthly if isinstance(item, dict) and item.get("year")]
    if not valid:
        return '<p class="missing-proof">未生成可核验的分月收益；页面不会从年化标量反推。</p>'
    years = sorted({int(item["year"]) for item in valid})
    annual_by_year = {
        int(item["year"]): item
        for item in annual
        if isinstance(item, dict) and item.get("year")
    }
    by_period = {
        (int(item["year"]), int(item["month"])): item
        for item in valid
        if item.get("month")
    }
    rows: list[str] = []
    for year in years:
        for key, label in (("gross_return", "Gross"), ("net_return", "Net")):
            cells = "".join(
                _return_cell((by_period.get((year, month)) or {}).get(key))
                for month in range(1, 13)
            )
            annual_value = (annual_by_year.get(year) or {}).get(key)
            rows.append(
                f'<tr><th>{year} {label}</th>{cells}{_return_cell(annual_value)}</tr>'
            )
    month_headers = "".join(f"<th>{month}月</th>" for month in range(1, 13))
    return f'<div class="table-scroll return-matrix"><table><thead><tr><th>期间</th>{month_headers}<th>全年</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>'


def _return_cell(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "<td>—</td>"
    tone = "return-positive" if number > 0 else "return-negative" if number < 0 else ""
    return f'<td class="{tone}">{escape(_format_percent(number))}</td>'


def _quantile_summary_table(rows: list[Any]) -> str:
    valid = [item for item in rows if isinstance(item, dict) and item.get("group")]
    if not valid:
        return '<p class="missing-proof">未生成正式 decile summary table。</p>'
    body = "".join(
        "<tr>"
        f'<th>{escape(str(item.get("group") or ""))}</th>'
        f'<td>{_format_percent(item.get("mean_daily_return"))}</td>'
        f'<td>{escape(_format_value(item.get("daily_ir")))}</td>'
        f'<td>{escape(_format_value(item.get("final_nav")))}</td>'
        f'<td>{escape(_format_value(item.get("member_count_min")))}</td>'
        f'<td>{escape(_format_value(item.get("member_count_median")))}</td>'
        f'<td>{escape(_format_value(item.get("member_count_max")))}</td>'
        "</tr>"
        for item in valid
    )
    return '<div class="table-scroll quantile-table"><table><thead><tr><th>组别</th><th>日均收益</th><th>Daily IR</th><th>Final NAV</th><th>最少样本</th><th>样本中位数</th><th>最多样本</th></tr></thead><tbody>' + body + "</tbody></table></div>"


def _risk_turnover_tables(drawdown: dict[str, Any], turnover: dict[str, Any]) -> str:
    risk_rows = "".join(
        "<tr>"
        f'<th>{escape(label)}</th>'
        f'<td>{_format_percent(item.get("max_drawdown"))}</td>'
        f'<td>{escape(str(item.get("peak_date") or "—"))}</td>'
        f'<td>{escape(str(item.get("trough_date") or "—"))}</td>'
        f'<td>{escape(_recovery_label(item))}</td>'
        f'<td>{escape(_format_value(item.get("underwater_days")))}</td>'
        f'<td>{escape(_format_value(item.get("max_recovery_days")))}</td>'
        "</tr>"
        for key, label in (("gross", "Gross"), ("net", "Net"))
        if isinstance((item := drawdown.get(key)), dict) and item
    )
    risk_table = (
        '<div class="table-scroll risk-table"><table><thead><tr><th>序列</th><th>最大回撤</th><th>峰值日</th><th>谷底日</th><th>恢复日</th><th>最大回撤水下天数</th><th>最长恢复天数</th></tr></thead><tbody>'
        + risk_rows
        + "</tbody></table></div>"
        if risk_rows
        else '<p class="missing-proof">未生成可核验的 NAV 回撤几何。</p>'
    )
    turnover_table = (
        '<div class="table-scroll turnover-table"><table><thead><tr><th>日均换手</th><th>中位数</th><th>P95</th><th>最大值</th><th>有效期数</th></tr></thead><tbody><tr>'
        f'<td>{_format_percent(turnover.get("mean_daily"))}</td>'
        f'<td>{_format_percent(turnover.get("median_daily"))}</td>'
        f'<td>{_format_percent(turnover.get("p95_daily"))}</td>'
        f'<td>{_format_percent(turnover.get("max_daily"))}</td>'
        f'<td>{escape(_format_value(turnover.get("measurement_count")))}</td>'
        "</tr></tbody></table></div>"
        if turnover
        else '<p class="missing-proof">未生成正式 long-side turnover table。</p>'
    )
    return f'<div class="risk-turnover-stack">{risk_table}{turnover_table}</div>'


def _recovery_label(item: dict[str, Any]) -> str:
    if item.get("recovery_date"):
        return str(item["recovery_date"])
    if item.get("recovered") and item.get("max_drawdown") == 0:
        return "无回撤"
    return "尚未恢复"


def _consistency_panel(consistency: dict[str, Any]) -> str:
    checks = consistency.get("checks") if isinstance(consistency.get("checks"), list) else []
    conflicts = [item for item in checks if isinstance(item, dict) and item.get("status") == "CONFLICT"]
    if not conflicts:
        return ""
    rows = "".join(
        f'<li><strong>{escape(str(item.get("check") or "formal evidence"))}</strong><span>{escape(_consistency_detail(item))}</span></li>'
        for item in conflicts
    )
    return f'<div class="evidence-conflict-panel"><strong>正式证据存在冲突</strong><ul>{rows}</ul></div>'


def _consistency_detail(item: dict[str, Any]) -> str:
    missing = item.get("missing_roles")
    invalid = item.get("invalid_roles")
    role_parts = []
    if isinstance(missing, list) and missing:
        role_parts.append("missing: " + ", ".join(str(value) for value in missing))
    if isinstance(invalid, list) and invalid:
        role_parts.append("invalid: " + ", ".join(str(value) for value in invalid))
    if role_parts:
        return " · ".join(role_parts)
    if item.get("detail"):
        return str(item["detail"])
    if item.get("mismatches"):
        return "mismatch: " + ", ".join(str(value) for value in item["mismatches"])
    prefix = f'{item.get("group")}: ' if item.get("group") else ""
    return (
        prefix
        + f'series={_format_value(item.get("series_value"))} · '
        + f'formal={_format_value(item.get("formal_scalar_value"))}'
    )


def _backtest_provenance_table(job: ResearchJob, provenance: dict[str, Any]) -> str:
    sources = provenance.get("sources") if isinstance(provenance.get("sources"), dict) else {}
    if not sources:
        return '<p class="missing-proof">尚无正式回测来源清单。</p>'
    rows: list[str] = []
    for role, source in sources.items():
        if not isinstance(source, dict):
            continue
        artifact_id = str(source.get("artifact_id") or "")
        href = f"/artifact/{escape(job.job_id)}/{_url_path(artifact_id)}" if artifact_id else ""
        source_link = (
            f'<a href="{href}" target="_blank" rel="noopener">{escape(artifact_id)}</a>'
            if href
            else "—"
        )
        sha = str(source.get("sha256") or "")
        rows.append(
            f'<tr><th>{escape(_metric_label(str(role)))}</th><td>{source_link}</td><td title="{escape(sha)}">{escape(sha[:16] + "…" if sha else "—")}</td></tr>'
        )
    return '<div class="table-scroll provenance-table"><table><thead><tr><th>角色</th><th>正式产物</th><th>SHA-256</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>"


def _structured_value(value: Any, *, depth: int = 0) -> str:
    if value in (None, "", {}, []):
        return '<p class="missing-proof">Not yet produced.</p>'
    if depth > 4:
        return f'<p>{escape(_format_value(value, long=True))}</p>'
    if isinstance(value, dict):
        rows = "".join(
            f'<div><dt>{escape(str(key).replace("_", " "))}</dt><dd>{_structured_value(child, depth=depth + 1)}</dd></div>'
            for key, child in value.items()
            if child not in (None, "", {}, [])
        )
        return f'<dl class="structured-record">{rows}</dl>'
    if isinstance(value, list):
        return '<ul class="structured-list">' + "".join(
            f'<li>{_structured_value(item, depth=depth + 1)}</li>' for item in value[:40]
        ) + "</ul>"
    return f'<p>{escape(_format_value(value, long=True))}</p>'


def _stage_timeline(job: ResearchJob, result: dict[str, Any]) -> str:
    stages = result.get("stages") if isinstance(result.get("stages"), list) else []
    defaults = [
        ("机制与数学对象", "mechanism"),
        ("数据可行性", "data"),
        ("因子实现", "implementation"),
        ("回测与稳健性", "evaluation"),
        ("Council 与结论", "council"),
    ]
    mapped = {str(item.get("id")): item for item in stages if isinstance(item, dict)}
    items = []
    for label, stage_id in defaults:
        item = mapped.get(stage_id, {})
        status = str(item.get("status") or _infer_stage_status(job, stage_id))
        items.append(
            f'<li class="stage stage-{escape(status.lower())}"><span class="stage-dot"></span><div><strong>{escape(label)}</strong><span>{escape(_stage_status_label(status))}</span></div></li>'
        )
    return '<section class="timeline-section"><h2>研究进度</h2><ol class="stage-list">' + "".join(items) + "</ol></section>"


def _decision_panel(job: ResearchJob, result: dict[str, Any], csrf_token: str) -> str:
    blockers = _string_list(result.get("blockers"))
    next_actions = _string_list(result.get("next_actions"))
    summary = str(result.get("summary") or job.error_message or "研究证据正在生成。")
    action = ""
    can_resume = bool(
        job.execution_status in {"REVIEW_REQUIRED", "BLOCKED", "FAILED"}
        and job.workspace_path
        and result.get("host_attestation_id")
        and job.error_code not in NON_RESUMABLE_SECURITY_ERRORS
        and job.error_code not in GENERIC_RESUME_DISABLED_ERRORS
    )
    if can_resume:
        action = f"""
        <form method="post" action="/research/{escape(job.job_id)}/resume" class="inline-form">
          <input type="hidden" name="csrf" value="{escape(csrf_token)}">
          <button class="button secondary" type="submit">从现有证据继续</button>
        </form>
        """
    elif job.execution_status == "QUEUED":
        action = f"""
        <form method="post" action="/research/{escape(job.job_id)}/cancel" class="inline-form">
          <input type="hidden" name="csrf" value="{escape(csrf_token)}">
          <button class="button danger" type="submit">取消排队</button>
        </form>
        """
    return f"""
    <section class="decision-panel verdict-{escape(job.factor_verdict.lower())}">
      <div class="decision-head"><div><span>因子结论</span><strong>{escape(job.factor_verdict)}</strong></div><div><span>研究协议</span><strong>{escape(job.protocol_status)}</strong></div><div><span>Council</span><strong>{escape(job.council_status)}</strong></div><div><span>正式证明资格</span><strong>{'是' if job.formal_proof_eligible else '否'}</strong></div></div>
      <p>{escape(summary)}</p>
      {_bullet_group('阻断原因', blockers)}
      {_bullet_group('下一步', next_actions)}
      {action}
    </section>
    """


def _metric_section(result: dict[str, Any]) -> str:
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    if not metrics:
        return '<section class="content-section"><div class="section-heading"><h2>回测结果</h2><p>尚未生成正式指标</p></div></section>'
    preferred = [
        ("rank_ic_mean", "Rank IC"),
        ("rank_icir", "Rank ICIR"),
        ("pearson_ic_mean", "Pearson IC"),
        ("long_side_annual_return", "多头年化"),
        ("cost_adjusted_annual_return", "成本后年化"),
        ("turnover", "日均换手"),
        ("long_side_max_drawdown", "多头最大回撤"),
        ("long_side_recovery_days", "修复天数"),
        ("fama_macbeth_t", "Fama-MacBeth t"),
        ("monotonicity", "分组单调性"),
    ]
    cells = []
    used: set[str] = set()
    for key, label in preferred:
        if key not in metrics:
            continue
        used.add(key)
        cells.append(_metric_cell(label, metrics[key]))
    for key, value in metrics.items():
        if key not in used and len(cells) < 14:
            cells.append(_metric_cell(key.replace("_", " "), value))
    return '<section class="content-section"><div class="section-heading"><h2>回测结果</h2><p>仅展示已落盘的正式证据</p></div><div class="metric-grid">' + "".join(cells) + "</div></section>"


def _method_section(result: dict[str, Any]) -> str:
    method = result.get("research_method") if isinstance(result.get("research_method"), dict) else {}
    if not method:
        return ""
    fields = [
        ("研究问题", method.get("research_question")),
        ("经济机制", method.get("economic_mechanism")),
        ("数学对象", method.get("mathematical_object")),
        ("估计量", method.get("factor_estimator")),
        ("付款方假设", method.get("payer_hypothesis")),
        ("可证伪条件", method.get("falsification")),
        ("备择解释", method.get("alternative_hypotheses")),
    ]
    rows = "".join(_definition_row(label, value) for label, value in fields if value)
    return '<section class="content-section"><div class="section-heading"><h2>研究方法</h2><p>经济机制与数学对象</p></div><dl class="definition-list">' + rows + "</dl></section>"


def _data_implementation_section(result: dict[str, Any]) -> str:
    contract = result.get("data_implementation") if isinstance(result.get("data_implementation"), dict) else {}
    if not contract:
        return ""
    fields = [
        ("数据集", contract.get("datasets")),
        ("信息时点", contract.get("information_set")),
        ("因子公式", contract.get("formula")),
        ("实现方式", contract.get("implementation_mode")),
        ("IS / OOS", contract.get("is_oos_boundary")),
        ("成本模型", contract.get("cost_model")),
        ("数据缺口", contract.get("data_gaps")),
    ]
    rows = "".join(_definition_row(label, value) for label, value in fields if value)
    return '<section class="content-section"><div class="section-heading"><h2>数据与实现</h2><p>Data API 只读复用</p></div><dl class="definition-list">' + rows + "</dl></section>"


def _chart_section(job: ResearchJob, result: dict[str, Any]) -> str:
    artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), list) else []
    images = [item for item in artifacts if isinstance(item, dict) and item.get("kind") == "image"][:8]
    if not images:
        return ""
    figures = []
    for item in images:
        artifact_id = str(item.get("artifact_id") or "")
        label = str(item.get("label") or artifact_id)
        href = f"/artifact/{escape(job.job_id)}/{_url_path(artifact_id)}"
        figures.append(f'<figure><a href="{href}" target="_blank" rel="noopener"><img src="{href}" alt="{escape(label)}" loading="lazy"></a><figcaption>{escape(label)}</figcaption></figure>')
    return '<section class="content-section"><div class="section-heading"><h2>图表证据</h2><p>正式回测输出</p></div><div class="chart-grid">' + "".join(figures) + "</div></section>"


def _council_section(result: dict[str, Any]) -> str:
    council = result.get("council") if isinstance(result.get("council"), dict) else {}
    if not council:
        return ""
    routes = council.get("routes") if isinstance(council.get("routes"), list) else []
    route_html = "".join(
        f'<li>{_structured_value(item)}</li>'
        for item in routes[:20]
    )
    synthesis = council.get("synthesis") or council.get("summary")
    questions = _string_list(council.get("questions"))
    mutation = council.get("mutation")
    return f'''<section class="content-section council-section"><div class="section-heading"><div><p class="section-kicker">ADVERSARIAL REVISION</p><h2>Council</h2></div><p>独立路线、数学反例与 mutation</p></div>{_bullet_group('Council questions', questions)}<div class="council-synthesis"><strong>综合判断</strong>{_structured_value(synthesis)}</div>{f'<div class="mutation-panel"><strong>Selected mutation</strong>{_structured_value(mutation)}</div>' if mutation else ''}<ul class="council-routes">{route_html}</ul></section>'''


def _artifact_section(job: ResearchJob, result: dict[str, Any]) -> str:
    artifacts = result.get("artifacts") if isinstance(result.get("artifacts"), list) else []
    if not artifacts:
        return ""
    rows = []
    for item in artifacts[:100]:
        if not isinstance(item, dict):
            continue
        artifact_id = str(item.get("artifact_id") or "")
        label = str(item.get("label") or artifact_id)
        kind = str(item.get("kind") or "file")
        href = f"/artifact/{escape(job.job_id)}/{_url_path(artifact_id)}"
        rows.append(f'<li><a href="{href}" target="_blank" rel="noopener">{escape(label)}</a><span>{escape(kind)}</span></li>')
    return '<section class="content-section"><div class="section-heading"><h2>研究产物</h2><p>受控读取，不暴露服务器路径</p></div><ul class="artifact-list">' + "".join(rows) + "</ul></section>"


def _event_section(events: list[dict[str, Any]]) -> str:
    if not events:
        return ""
    rows = "".join(
        f'<li><time data-time="{escape(str(item.get("created_at_utc") or ""))}">{escape(str(item.get("created_at_utc") or "")[:16].replace("T", " "))}</time><strong>{escape(str(item.get("event_type") or ""))}</strong><span>{escape(str(item.get("message") or ""))}</span></li>'
        for item in events
    )
    return '<section class="content-section"><div class="section-heading"><h2>任务记录</h2><p>控制面事件</p></div><ol class="event-list">' + rows + "</ol></section>"


def _status_badge(status: str) -> str:
    return f'<span class="status-badge status-{escape(status.lower())}">{escape(STATUS_LABELS.get(status, status))}</span>'


def _status_stat(label: str, value: int, tone: str) -> str:
    return f'<div class="status-stat tone-{tone}"><span>{escape(label)}</span><strong>{value}</strong></div>'


def _metric_cell(
    label: str,
    value: Any,
    evidence: dict[str, Any] | None = None,
    *,
    metric_key: str = "",
) -> str:
    evidence = evidence or {}
    evidence_class = str(evidence.get("evidence_class") or "FORMAL UNVERIFIED")
    source = str(evidence.get("artifact_id") or "")
    source_label = _compact_metric_source(source)
    primary, detail = _metric_value_parts(metric_key, value)
    detail_html = f'<em>{escape(detail)}</em>' if detail else ""
    diagnostic = (
        str(value.get("diagnostic_block_reason") or "") if isinstance(value, dict) else ""
    )
    required_for_acceptance = (
        value.get("required_for_acceptance") if isinstance(value, dict) else None
    )
    diagnostic_label = (
        "Formal blocker"
        if isinstance(value, dict)
        and (
            required_for_acceptance is True
            or str(value.get("status") or "").upper() in {"BLOCKED", "INVALID"}
        )
        else (
            "Diagnostic limitation"
            if required_for_acceptance is False
            else "Acceptance role unknown"
        )
    )
    diagnostic_html = (
        f'<details class="metric-diagnostic"><summary>{diagnostic_label}</summary>'
        f'<code>{escape(diagnostic)}</code></details>'
        if diagnostic
        else ""
    )
    source_exact = source if source else "source pending"
    source_html = (
        '<details class="metric-source"><summary>'
        f"{escape(evidence_class)} · {escape(source_label)}</summary>"
        f"<code>{escape(source_exact)}</code></details>"
    )
    return f'<div class="metric-cell"><span>{escape(label)}</span><strong>{escape(primary)}</strong>{detail_html}{diagnostic_html}{source_html}</div>'


def _metric_value_parts(metric_key: str, value: Any) -> tuple[str, str]:
    if not isinstance(value, dict):
        return _format_value(value), ""

    if metric_key == "monotonicity":
        score = value.get("monotonicity_score", value.get("score"))
        status = str(value.get("status") or "").upper()
        required_for_acceptance = value.get("required_for_acceptance")
        acceptance_blocked = status in {"BLOCKED", "INVALID"} or (
            required_for_acceptance is True
            and bool(value.get("diagnostic_block_reason"))
        )
        if acceptance_blocked:
            primary = "Blocked"
        elif status == "UNAVAILABLE":
            if required_for_acceptance is True:
                primary = "Unavailable"
            elif required_for_acceptance is False:
                primary = "Diagnostic unavailable"
            else:
                primary = "Role unknown"
        elif isinstance(score, (int, float)) and not isinstance(score, bool):
            primary = _format_value(score)
        else:
            diagnostic = str(value.get("monotonicity_diagnostic") or "").lower()
            if "not_above" in diagnostic or "non_monot" in diagnostic:
                primary = "Non-monotone"
            else:
                primary = status.replace("_", " ").title() if status else "Not reported"
        details = []
        if value.get("bucket_count") not in (None, ""):
            details.append(f"{_format_value(value.get('bucket_count'))} buckets")
        if value.get("period_count") not in (None, ""):
            details.append(f"{_format_value(value.get('period_count'))} periods")
        if isinstance(score, (int, float)) and not isinstance(score, bool) and acceptance_blocked:
            details.append(f"reported score {_format_value(score)}")
        reason = _compact_diagnostic_reason(value.get("diagnostic_block_reason"))
        if reason:
            details.append(reason)
        return primary, " · ".join(details[:3])

    primary_fields = {
        "rank_ic": "mean",
        "ic": "mean",
        "icir": "value",
        "fama_macbeth": "lambda_mean",
        "long_side_after_cost": "net_return_annual",
        "turnover": "daily_turnover",
        "trading_cost": "annual_cogs",
        "drawdown": "max_drawdown",
        "monotonicity": "score",
    }
    field = primary_fields.get(metric_key)
    if field not in value:
        field = next((name for name in ("value", "mean", "score") if name in value), None)
    if field is None:
        return _format_value(value, long=True), ""

    raw_primary = value.get(field)
    percent_fields = {
        "max_drawdown",
        "net_return_annual",
        "annual_cogs",
        "daily_turnover",
    }
    primary = _format_percent(raw_primary) if field in percent_fields else _format_value(raw_primary)
    detail_labels = {
        "period_count": "periods",
        "t_stat": "t-stat",
        "recovery_days": "recovery days",
        "bucket_count": "buckets",
    }
    details = [
        f"{detail_labels.get(name, name.replace('_', ' '))}: {_format_value(item)}"
        for name, item in value.items()
        if name != field
    ]
    return primary, " · ".join(details[:3])


def _compact_metric_source(source: str) -> str:
    name = str(source or "").rsplit("/", 1)[-1]
    lowered = name.lower()
    aliases = (
        ("factor_proof_certificate", "factor proof certificate"),
        ("factor_evaluation", "factor evaluation"),
        ("backtest_master", "backtest master"),
        ("metric_verifier", "metric verifier"),
    )
    for marker, label in aliases:
        if marker in lowered:
            return label
    if not name:
        return "source pending"
    return name if len(name) <= 34 else f"{name[:31]}..."


def _compact_diagnostic_reason(value: Any) -> str:
    reason = str(value or "").strip()
    if not reason:
        return ""
    token, _, suffix = reason.partition(":")
    token = token.removeprefix("BLOCK_FACTORFORGE_METRIC_VERIFIER_")
    summary = token.replace("_", " ").lower()
    return f"{summary} ({suffix})" if suffix else summary


def _metric_label(key: str) -> str:
    labels = {
        "ic": "Pearson IC",
        "rank_ic": "Rank IC",
        "icir": "ICIR",
        "fama_macbeth": "Fama-MacBeth risk premium",
        "long_side_after_cost": "Long side after cost",
        "turnover": "Turnover",
        "trading_cost": "Trading cost",
        "drawdown": "Maximum drawdown",
        "recovery": "Recovery",
        "monotonicity": "Quantile monotonicity",
        "gross_final_nav": "Gross final NAV",
        "net_final_nav": "Net final NAV",
        "long_short_final_nav": "Long-short final NAV",
        "gross_sharpe": "Gross Sharpe",
        "net_sharpe": "Net Sharpe",
        "annual_volatility": "Annual volatility",
        "gross_net_nav": "Gross / net NAV",
        "formal_step4_pack": "Required formal Step4 pack",
        "quantile_nav": "Quintile / decile NAV",
        "quantile_summary": "Decile summary",
        "long_short": "Long-short diagnostic",
        "annual_returns": "Annual returns",
        "monthly_returns": "Monthly returns",
        "rank_ic_timeseries": "Rank IC timeseries",
        "pearson_ic_timeseries": "Pearson IC timeseries",
        "coverage": "Signal coverage",
        "drawdown_geometry": "Drawdown geometry",
        "turnover_profile": "Turnover profile",
        "cost_sensitivity": "Cost sensitivity",
        "benchmark_excess": "Benchmark / excess NAV",
        "ic_decay": "IC decay",
        "stability_slices": "Year / regime stability",
        "factor_exposure": "Industry / size / liquidity exposure",
        "gross_nav_chart": "Gross NAV chart",
        "net_nav_chart": "Net NAV chart",
        "quantile_nav_chart": "Decile NAV chart",
        "quantile_counts_chart": "Decile counts chart",
        "long_short_diagnostic_chart": "Long-short NAV chart",
        "rank_ic_chart": "Rank IC chart",
        "pearson_ic_chart": "Pearson IC chart",
        "coverage_chart": "Coverage chart",
        "long_side_nav_table": "Gross / net NAV table",
        "long_side_turnover_table": "Turnover table",
        "quantile_summary_table": "Decile summary table",
        "quantile_nav_table": "Decile NAV table",
        "quantile_counts_table": "Decile counts table",
        "quantile_returns_table": "Decile returns table",
        "long_short_returns_table": "Long-short returns table",
        "long_short_nav_table": "Long-short NAV table",
    }
    return labels.get(key, key.replace("_", " ").title())


def _format_percent(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{number * 100:.2f}%"


def _definition_row(label: str, value: Any) -> str:
    return f'<div><dt>{escape(label)}</dt><dd>{escape(_format_value(value, long=True))}</dd></div>'


def _bullet_group(label: str, values: list[str]) -> str:
    if not values:
        return ""
    return f'<div class="decision-list"><strong>{escape(label)}</strong><ul>{"".join(f"<li>{escape(item)}</li>" for item in values)}</ul></div>'


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value:
        return [str(value)]
    return []


def _format_value(value: Any, *, long: bool = False) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        if abs(value) < 1 and value != 0:
            return f"{value:.4f}"
        return f"{value:.3f}"
    if isinstance(value, (int, str)):
        return str(value)
    if isinstance(value, list):
        return "；".join(_format_value(item, long=True) for item in value[:12])
    if isinstance(value, dict):
        if long:
            return "；".join(f"{key}: {_format_value(item, long=True)}" for key, item in list(value.items())[:12])
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _stage_label(stage: str) -> str:
    labels = {
        "queued": "等待执行",
        "allocating_workspace": "创建隔离工作区",
        "researching": "机制、实现与回测",
        "verifying": "证据核验",
        "review_required": "等待复核",
        "completed": "研究完成",
        "blocked": "研究阻断",
        "resume_requested": "准备继续",
    }
    return labels.get(stage, stage.replace("_", " "))


def _infer_stage_status(job: ResearchJob, stage_id: str) -> str:
    if job.execution_status in {"COMPLETED", "BLOCKED", "FAILED"}:
        return "done" if job.execution_status == "COMPLETED" else "blocked"
    order = ["mechanism", "data", "implementation", "evaluation", "council"]
    current_map = {
        "queued": -1,
        "allocating_workspace": -1,
        "researching": 0,
        "verifying": 4,
        "review_required": 4,
    }
    current = current_map.get(job.current_stage, 0)
    index = order.index(stage_id)
    if index < current:
        return "done"
    if index == current:
        return "active"
    return "pending"


def _stage_status_label(status: str) -> str:
    return {"done": "已生成", "active": "进行中", "pending": "等待", "blocked": "阻断", "pass": "通过"}.get(status.lower(), status)


def _url_path(value: str) -> str:
    from urllib.parse import quote

    return "/".join(quote(part, safe="") for part in value.split("/") if part)


def _poll_script(job_id: str | None, last_updated: str) -> str:
    target = f"/api/research/{job_id}" if job_id else "/api/jobs"
    return f"""
    <script>
    (() => {{
      const last = {json.dumps(last_updated)};
      setTimeout(async () => {{
        try {{
          const response = await fetch("{target}", {{headers: {{"Accept": "application/json"}}}});
          if (!response.ok) return;
          const payload = await response.json();
          const updated = payload.updated_at_utc || payload.latest_updated_at_utc || "";
          if (!last || (updated && updated !== last)) location.reload();
        }} catch (_) {{}}
      }}, 6000);
    }})();
    </script>
    """


def _page(title: str, body: str, *, public: bool = False) -> str:
    page_class = "public-page" if public else "app-page"
    return f"""<!doctype html>
<html lang="zh-CN" class="{page_class}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <title>{escape(title)}</title>
  <style>{_css()}</style>
</head>
<body>{body}</body>
</html>"""


def _css() -> str:
    return """
:root { color-scheme: light; --ink:#182126; --muted:#627078; --line:#d7dddf; --surface:#fff; --canvas:#f3f5f4; --green:#1f6d4c; --green-soft:#e6f2eb; --red:#a83b32; --red-soft:#fae9e6; --amber:#8b5c12; --amber-soft:#f8eed7; --blue:#27627a; --blue-soft:#e4f0f5; }
* { box-sizing:border-box; }
html { letter-spacing:0; background:var(--canvas); }
body { margin:0; color:var(--ink); background:var(--canvas); font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; font-size:14px; line-height:1.55; }
a { color:inherit; }
button,input,select,textarea { font:inherit; letter-spacing:0; }
.topbar { height:58px; padding:0 28px; display:flex; align-items:center; justify-content:space-between; background:#182126; color:#fff; border-bottom:1px solid #0d1417; position:sticky; top:0; z-index:10; }
.brand { display:flex; align-items:center; gap:10px; text-decoration:none; font-weight:700; }
.brand-symbol { width:30px; height:30px; display:grid; place-items:center; background:#fff; color:#182126; border-radius:4px; font-size:12px; }
.topbar-right { display:flex; align-items:center; gap:20px; }.topbar-title { color:#c7d0d3; }.inline-form { display:inline; margin:0; }
.quiet-button { border:0; padding:6px 0; color:#fff; background:transparent; cursor:pointer; }.quiet-button:hover { text-decoration:underline; }
.workspace { max-width:1240px; margin:0 auto; padding:30px 28px 72px; }
.page-heading,.detail-heading,.section-heading { display:flex; align-items:flex-end; justify-content:space-between; gap:24px; }
.page-heading { margin-bottom:22px; }.page-heading h1,.detail-heading h1 { margin:2px 0 0; font-size:28px; line-height:1.2; }.detail-heading h1,.eyebrow { overflow-wrap:anywhere; }.eyebrow,.brand-mark { margin:0; color:var(--blue); font-size:12px; font-weight:800; text-transform:uppercase; }.muted,.section-heading p { color:var(--muted); }
.button { display:inline-flex; min-height:38px; align-items:center; justify-content:center; padding:8px 14px; border:1px solid transparent; border-radius:5px; font-weight:700; text-decoration:none; cursor:pointer; }.button.primary { background:var(--green); color:#fff; }.button.secondary { border-color:var(--blue); color:var(--blue); background:#fff; }.button.danger { border-color:var(--red); color:var(--red); background:#fff; }
.status-strip { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); border:1px solid var(--line); background:var(--surface); border-radius:6px; overflow:hidden; }.status-stat { padding:16px 18px; display:flex; justify-content:space-between; border-right:1px solid var(--line); }.status-stat:last-child{border-right:0}.status-stat span { color:var(--muted); }.status-stat strong { font-size:21px; }.tone-blue strong{color:var(--blue)}.tone-amber strong{color:var(--amber)}.tone-green strong{color:var(--green)}.tone-red strong{color:var(--red)}
.job-section,.new-research,.content-section,.timeline-section { margin-top:34px; }.content-section { max-width:100%; min-width:0; overflow-x:clip; }.section-heading { margin-bottom:12px; border-bottom:1px solid var(--line); padding-bottom:9px; }.section-heading h2,.timeline-section h2 { margin:0; font-size:18px; }.section-heading p { margin:0; }
.job-table { border:1px solid var(--line); border-radius:6px; overflow:hidden; background:var(--surface); }.job-table-head,.job-row { display:grid; grid-template-columns:minmax(280px,2fr) minmax(150px,1fr) 120px 135px 150px; align-items:center; gap:12px; padding:11px 14px; }.job-table-head { background:#e9edec; color:var(--muted); font-size:12px; font-weight:700; }.job-row { min-height:68px; text-decoration:none; border-top:1px solid var(--line); }.job-row:hover { background:#f7faf8; }.job-main { display:grid; gap:3px; }.job-main strong { font-size:15px; }.job-main span,.job-row time,.job-stage { color:var(--muted); font-size:12px; overflow-wrap:anywhere; }
.status-badge { display:inline-flex; min-height:26px; align-items:center; padding:3px 8px; border:1px solid var(--line); border-radius:999px; white-space:nowrap; font-size:12px; font-weight:700; }.status-researching,.status-verifying,.status-allocating { color:var(--blue); background:var(--blue-soft); border-color:#bad4df; }.status-completed { color:var(--green); background:var(--green-soft); border-color:#b9d8c7; }.status-blocked,.status-failed { color:var(--red); background:var(--red-soft); border-color:#e7bdb7; }.status-review_required,.status-queued { color:var(--amber); background:var(--amber-soft); border-color:#e6d09f; }
.verdict-accept{color:var(--green)}.verdict-reject,.verdict-block{color:var(--red)}.verdict-iterate,.verdict-partial{color:var(--amber)}
.research-form { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px 18px; padding:20px; border:1px solid var(--line); border-radius:6px; background:var(--surface); }.field { display:grid; gap:6px; }.field label { font-weight:700; }.field input,.field textarea,.field select,.fixed-contract { width:100%; border:1px solid #aeb8bc; border-radius:4px; padding:9px 10px; background:#fff; color:var(--ink); }.fixed-contract { background:#f3f6f5; color:var(--muted); }.field textarea { resize:vertical; min-height:160px; }.span-2 { grid-column:span 2; }.form-actions { display:flex; align-items:center; justify-content:space-between; gap:20px; border-top:1px solid var(--line); padding-top:16px; }.form-actions p { margin:0; color:var(--muted); }
.breadcrumbs { display:flex; gap:8px; color:var(--muted); margin-bottom:22px; }.breadcrumbs a { color:var(--blue); }.detail-heading { align-items:flex-start; }.detail-heading>div { width:100%; min-width:0; max-width:900px; }.idea-summary { max-width:900px; white-space:pre-line; overflow-wrap:anywhere; color:#3d4a50; font-size:15px; }.identity-band { margin-top:22px; display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); border:1px solid var(--line); background:#fff; border-radius:6px; }.identity-band div { padding:13px 15px; border-right:1px solid var(--line); display:grid; gap:2px; }.identity-band div:last-child{border-right:0}.identity-band span { color:var(--muted); font-size:12px; }.identity-band strong { overflow-wrap:anywhere; }
.stage-list { list-style:none; margin:12px 0 0; padding:0; display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); border:1px solid var(--line); border-radius:6px; overflow:hidden; }.stage { min-height:70px; padding:13px; display:flex; gap:10px; align-items:flex-start; background:#fff; border-right:1px solid var(--line); }.stage:last-child{border-right:0}.stage-dot { width:9px; height:9px; border-radius:50%; margin-top:6px; background:#aab3b6; flex:none; }.stage>div { display:grid; }.stage span:last-child { color:var(--muted); font-size:12px; }.stage-done .stage-dot,.stage-pass .stage-dot{background:var(--green)}.stage-active .stage-dot{background:var(--blue)}.stage-blocked .stage-dot{background:var(--red)}
.decision-panel { margin-top:26px; padding:18px; border:1px solid var(--line); border-left:4px solid var(--blue); background:#fff; border-radius:5px; }.decision-panel.verdict-accept{border-left-color:var(--green)}.decision-panel.verdict-reject,.decision-panel.verdict-block{border-left-color:var(--red)}.decision-head { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:16px; }.decision-head div { display:grid; }.decision-head span { color:var(--muted); font-size:12px; }.decision-head strong { font-size:16px; }.decision-list { margin-top:12px; }.decision-list ul { margin:6px 0 0; padding-left:20px; }
.metric-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); border:1px solid var(--line); background:#fff; border-radius:6px; overflow:hidden; }.metric-cell { min-width:0; min-height:112px; display:grid; align-content:center; gap:5px; padding:12px 14px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); }.metric-cell span { color:var(--muted); font-size:12px; }.metric-cell strong { min-width:0; font-size:20px; overflow-wrap:anywhere; word-break:normal; }.metric-cell em { color:var(--muted); font-size:11px; line-height:1.45; font-style:normal; overflow-wrap:anywhere; }.metric-diagnostic,.metric-source { min-width:0; font-size:10px; color:var(--red); }.metric-source { color:var(--muted); }.metric-diagnostic summary,.metric-source summary { cursor:pointer; overflow-wrap:anywhere; }.metric-diagnostic code,.metric-source code { display:block; max-height:84px; margin-top:4px; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; }.metric-diagnostic code { color:var(--red); }.metric-source code { color:var(--muted); }
.definition-list { margin:0; border:1px solid var(--line); background:#fff; border-radius:6px; overflow:hidden; }.definition-list>div { display:grid; grid-template-columns:180px minmax(0,1fr); border-top:1px solid var(--line); }.definition-list>div:first-child{border-top:0}.definition-list dt { padding:12px 14px; background:#eef1f0; font-weight:700; }.definition-list dd { margin:0; padding:12px 14px; white-space:pre-line; overflow-wrap:anywhere; }
.chart-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }.chart-grid figure { margin:0; border:1px solid var(--line); border-radius:6px; background:#fff; overflow:hidden; }.chart-grid img { display:block; width:100%; aspect-ratio:16/9; object-fit:contain; background:#fff; }.chart-grid figcaption { padding:9px 11px; border-top:1px solid var(--line); color:var(--muted); }
.council-synthesis { padding:14px; margin:0 0 12px; background:var(--blue-soft); border-left:4px solid var(--blue); }.council-routes { list-style:none; margin:0; padding:0; display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }.council-routes li { border:1px solid var(--line); background:#fff; border-radius:5px; padding:12px; }.council-routes li>span { float:right; color:var(--muted); }.council-routes p { margin:8px 0 0; }
.artifact-list,.event-list { list-style:none; margin:0; padding:0; border:1px solid var(--line); background:#fff; border-radius:6px; overflow:hidden; }.artifact-list li { display:flex; justify-content:space-between; gap:20px; padding:10px 12px; border-top:1px solid var(--line); }.artifact-list li:first-child,.event-list li:first-child{border-top:0}.artifact-list a { color:var(--blue); overflow-wrap:anywhere; }.artifact-list span { color:var(--muted); }.event-list li { display:grid; grid-template-columns:150px 190px minmax(0,1fr); gap:12px; padding:9px 12px; border-top:1px solid var(--line); }.event-list time { color:var(--muted); }
.workspace-nav { margin-top:16px; display:flex; gap:4px; padding:4px; border:1px solid var(--line); background:#fff; position:sticky; top:66px; z-index:8; overflow-x:auto; }.workspace-nav a { padding:7px 11px; color:var(--muted); text-decoration:none; white-space:nowrap; border-bottom:2px solid transparent; }.workspace-nav a:hover { color:var(--ink); border-bottom-color:var(--blue); }
.section-kicker { margin:0 0 2px; color:var(--blue); font-size:11px; font-weight:800; letter-spacing:0; }.section-note { margin:-2px 0 16px; color:var(--muted); }
.conversation-section { scroll-margin-top:112px; }.chat-thread { display:grid; gap:10px; max-height:560px; overflow:auto; padding:14px; border:1px solid var(--line); background:#e9edec; }.chat-message { width:min(820px,92%); padding:12px 14px; border:1px solid var(--line); background:#fff; }.chat-message.user-message { justify-self:end; border-left:3px solid var(--green); }.chat-message.forge-message { justify-self:start; border-left:3px solid var(--blue); }.chat-message header { display:flex; justify-content:space-between; gap:16px; margin-bottom:6px; }.chat-message header span { color:var(--muted); font-size:11px; }.chat-message p { margin:0; white-space:pre-line; }.message-code { margin:0; padding:10px; overflow:auto; background:#f3f5f4; border:1px solid var(--line); white-space:pre-wrap; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px; }
.message-composer { display:grid; grid-template-columns:190px minmax(0,1fr); gap:12px; padding:14px; border:1px solid var(--line); border-top:0; background:#fff; }.message-composer .composer-input { grid-column:2; grid-row:1 / span 2; }.message-composer textarea { min-height:116px; }.composer-actions { grid-column:1 / -1; display:flex; justify-content:flex-end; align-items:center; gap:8px; border-top:1px solid var(--line); padding-top:12px; }.composer-actions span { margin-right:auto; color:var(--muted); font-size:12px; }
.notebook-section,.math-section,.backtest-section { scroll-margin-top:112px; }.evidence-badge { display:inline-flex; align-items:center; min-height:27px; padding:3px 8px; border:1px solid var(--line); font-size:11px; font-weight:800; white-space:nowrap; }.badge-agent { color:var(--blue); background:var(--blue-soft); }.badge-formal { color:var(--green); background:var(--green-soft); }.badge-conflict { color:var(--red); background:var(--red-soft); }
.notebook-flow { border-top:1px solid var(--line); }.notebook-step { display:grid; grid-template-columns:56px minmax(0,1fr); gap:18px; padding:20px 0; border-bottom:1px solid var(--line); }.notebook-index { color:var(--blue); font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:18px; font-weight:800; }.notebook-step h3 { margin:0 0 10px; font-size:16px; }.structured-record { margin:0; border:1px solid var(--line); background:#fff; }.structured-record>div { display:grid; grid-template-columns:minmax(140px,220px) minmax(0,1fr); border-top:1px solid var(--line); }.structured-record>div:first-child { border-top:0; }.structured-record dt { padding:8px 10px; background:#eef1f0; font-size:12px; font-weight:700; overflow-wrap:anywhere; }.structured-record dd { margin:0; padding:8px 10px; min-width:0; }.structured-record p { margin:0; white-space:pre-line; }.structured-list { margin:0; padding-left:20px; }.structured-list>li { margin:5px 0; }
.math-section { font-family:Georgia,"Times New Roman","Songti SC",serif; }.math-section .section-heading,.math-section .section-note,.math-section .evidence-badge { font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif; }.math-chapter { margin-top:22px; }.math-chapter>h3 { margin:0 0 10px; padding-bottom:6px; border-bottom:1px solid var(--ink); font-size:16px; }.math-definitions { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); margin:0; border:1px solid var(--line); background:#fff; }.math-definitions>div { padding:12px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); }.math-definitions dt { font-variant:small-caps; color:var(--muted); }.math-definitions dd { margin:4px 0 0; overflow-wrap:anywhere; }.equation-block { position:relative; margin:0; min-height:88px; display:grid; align-content:center; padding:18px 64px 18px 22px; border-bottom:1px solid var(--line); background:#fff; }.equation-block:first-of-type { border-top:1px solid var(--line); }.equation-block figcaption { color:var(--muted); font-size:12px; }.equation-expression { margin-top:8px; font-family:"STIX Two Math","Cambria Math",Georgia,serif; font-size:17px; line-height:1.7; white-space:pre-wrap; overflow-wrap:anywhere; }.equation-number { position:absolute; right:20px; top:50%; transform:translateY(-50%); }.derivation-list { list-style:none; margin:0; padding:0; }.derivation-list>li { display:grid; grid-template-columns:34px minmax(0,1fr); gap:12px; padding:14px 0; border-bottom:1px solid var(--line); }.derivation-list>li>span { width:28px; height:28px; display:grid; place-items:center; border:1px solid var(--ink); border-radius:50%; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; }.derivation-list strong { display:block; margin-bottom:7px; }
.equation-statement { display:grid; gap:8px; }.equation-line { min-width:0; }.equation-line-label { display:block; margin-bottom:3px; color:var(--muted); font-size:12px; font-variant:small-caps; }.equation-annotation { margin:3px 0 0; color:#46545a; font-size:14px; line-height:1.5; }.equation-overflow { color:var(--muted); font-size:12px; }.equation-overflow summary { cursor:pointer; }.equation-overflow pre { max-height:180px; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; }.rendered-math { display:block; max-width:100%; overflow-x:auto; overflow-y:hidden; padding:3px 0; }.rendered-math math { min-width:max-content; font-size:1.05em; }.equation-source { display:block; white-space:pre-wrap; font-family:"STIX Two Math","Cambria Math",Georgia,serif; }
.backtest-band { margin-top:24px; }.backtest-band h3 { margin:0 0 10px; font-size:15px; }.metric-cell small { color:var(--muted); font-size:10px; overflow-wrap:anywhere; }.chart-grid figcaption { display:flex; justify-content:space-between; gap:12px; }.chart-grid figcaption span { color:var(--green); font-size:10px; font-weight:800; }.chart-grid figcaption .chart-evidence-conflict { color:var(--red); }.table-scroll { overflow:auto; border:1px solid var(--line); background:#fff; }.table-scroll table { width:100%; border-collapse:collapse; }.table-scroll th,.table-scroll td { padding:9px 12px; border-bottom:1px solid var(--line); text-align:right; white-space:nowrap; }.table-scroll th:first-child,.table-scroll td:first-child { text-align:left; }.table-scroll thead th { color:var(--muted); background:#eef1f0; font-size:12px; }.annual-table { min-width:480px; }.module-table table { min-width:520px; }.module-table th:first-child { width:70%; }.module-state { display:inline-block; min-width:118px; padding:2px 6px; border:1px solid var(--line); text-align:center; font-size:10px; font-weight:800; }.module-available { color:var(--green); background:var(--green-soft); }.module-not_produced { color:var(--muted); background:#eef1f0; }.module-invalid_evidence,.module-evidence_conflict { color:var(--red); background:var(--red-soft); }.return-matrix table { min-width:1080px; }.return-matrix td { font-variant-numeric:tabular-nums; }.return-positive { color:var(--green); background:#f1f8f4; }.return-negative { color:var(--red); background:#fff3f1; }.quantile-table table { min-width:800px; }.risk-turnover-stack { display:grid; gap:12px; }.risk-table table { min-width:900px; }.turnover-table table { min-width:620px; }.provenance-table table { min-width:900px; }.provenance-table th:first-child { width:190px; }.provenance-table td:nth-child(2) { max-width:600px; white-space:normal; overflow-wrap:anywhere; text-align:left; }.provenance-table a { color:var(--blue); }.evidence-conflict-panel { margin-top:18px; padding:14px; border-left:4px solid var(--red); background:var(--red-soft); color:var(--red); }.evidence-conflict-panel ul { margin:8px 0 0; padding-left:20px; }.evidence-conflict-panel li { margin:5px 0; }.evidence-conflict-panel li span { margin-left:8px; font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11px; }.missing-proof { padding:12px; margin:0; color:var(--muted); background:#fff; border:1px dashed #aeb8bc; }.missing-proof p { margin:4px 0 0; }.empty-inline { padding:14px; margin:0; color:var(--muted); }.mutation-panel { margin:12px 0; padding:14px; border-left:4px solid var(--amber); background:var(--amber-soft); }.council-synthesis>strong,.mutation-panel>strong { display:block; margin-bottom:6px; }
.empty-state { padding:32px; border:1px dashed #aeb8bc; background:#fff; text-align:center; border-radius:6px; }.empty-state h3{margin:0 0 4px}.empty-state p{margin:0;color:var(--muted)}
.login-shell { min-height:100vh; display:grid; place-items:center; padding:24px; background:#e9edec; }.login-panel { width:min(420px,100%); padding:30px; background:#fff; border:1px solid var(--line); border-radius:6px; box-shadow:0 12px 36px rgba(24,33,38,.12); }.login-panel h1 { margin:4px 0; font-size:28px; }.login-panel .muted { margin:0 0 24px; }.login-form { display:grid; gap:9px; }.login-form label { font-weight:700; }.login-form input { padding:10px; border:1px solid #aeb8bc; border-radius:4px; }.login-form button { margin-top:8px; min-height:40px; border:0; border-radius:4px; background:var(--green); color:#fff; font-weight:700; cursor:pointer; }.form-error { padding:9px 10px; color:var(--red); background:var(--red-soft); border:1px solid #e7bdb7; }
@media (max-width:900px){.workspace{padding:22px 16px 52px}.topbar{padding:0 16px}.status-strip{grid-template-columns:repeat(2,1fr)}.job-table-head{display:none}.job-row{grid-template-columns:1fr auto}.job-stage,.job-verdict,.job-row time{grid-column:1}.identity-band{grid-template-columns:repeat(2,1fr)}.identity-band div{border-bottom:1px solid var(--line)}.stage-list{grid-template-columns:1fr}.stage{border-right:0;border-bottom:1px solid var(--line)}.metric-grid{grid-template-columns:repeat(2,1fr)}.decision-head{grid-template-columns:repeat(2,1fr)}.chart-grid,.council-routes{grid-template-columns:1fr}.math-definitions{grid-template-columns:1fr}}
@media (max-width:600px){.topbar-title{display:none}.page-heading,.detail-heading,.section-heading{align-items:flex-start;flex-direction:column}.research-form{grid-template-columns:1fr}.span-2{grid-column:span 1}.form-actions{align-items:stretch;flex-direction:column}.identity-band{grid-template-columns:1fr}.identity-band div{border-right:0}.metric-grid{grid-template-columns:1fr}.definition-list>div,.structured-record>div{grid-template-columns:1fr}.event-list li{grid-template-columns:1fr}.decision-head{grid-template-columns:1fr}.status-strip{grid-template-columns:1fr}.status-stat{border-right:0;border-bottom:1px solid var(--line)}.message-composer{grid-template-columns:1fr}.message-composer .composer-input{grid-column:1;grid-row:auto}.composer-actions{grid-column:1;align-items:stretch;flex-direction:column}.composer-actions span{margin-right:0}.chat-message{width:100%}.notebook-step{grid-template-columns:38px minmax(0,1fr)}.equation-block{padding-right:42px}.workspace-nav{top:58px}}
"""
