from __future__ import annotations

import json
from html import escape
from typing import Any

from factor_factory.console.models import ResearchJob


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


def render_job(job: ResearchJob, events: list[dict[str, Any]], csrf_token: str) -> str:
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
        _stage_timeline(job, result),
        _decision_panel(job, result, csrf_token),
        _metric_section(result),
        _method_section(result),
        _data_implementation_section(result),
        _chart_section(job, result),
        _council_section(result),
        _artifact_section(job, result),
        _event_section(events),
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
      <div class="field span-2"><label for="hypothesis">因子想法与经济假设</label><textarea id="hypothesis" name="hypothesis" rows="8" maxlength="20000" placeholder="描述现象、可能的付款方、信息形成时间、希望检验的数学关系和你认为会失败的条件。" required></textarea></div>
      <div class="field"><label for="universe">股票池</label><select id="universe" name="universe"><option value="a_share_all">全部 A 股（Data API 清洗口径）</option></select></div>
      <div class="field"><label>收益观察期</label><input type="hidden" name="forward_horizon" value="1d"><div class="fixed-contract">收盘后形成信号 → 下一交易日收盘成交 → 再下一交易日收盘退出（Pilot 固定）</div></div>
      <div class="field"><label for="sample-start">样本开始</label><input id="sample-start" name="sample_start" type="date" value="2016-01-01" required></div>
      <div class="field"><label for="sample-end">样本结束</label><input id="sample-end" name="sample_end" type="date" value="2025-07-11" required></div>
      <div class="field"><label>交易成本模型</label><input type="hidden" name="transaction_cost_bps" value="30"><div class="fixed-contract">换手 × 30 bps（Pilot 固定）</div></div>
      <div class="form-actions span-2"><p>提交后立即分配独立 Git worktree；现有 Data API 只读。</p><button class="button primary" type="submit">进入研究队列</button></div>
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
      <div><span>隔离状态</span><strong>{'已分配独立 worktree' if job.workspace_path else '等待分配'}</strong></div>
    </section>
    """


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
        f'<li><strong>{escape(str(item.get("route_family") or item.get("role") or "路线"))}</strong><span>{escape(str(item.get("verdict") or item.get("status") or ""))}</span><p>{escape(str(item.get("summary") or item.get("finding") or ""))}</p></li>'
        for item in routes if isinstance(item, dict)
    )
    synthesis = escape(str(council.get("synthesis") or council.get("summary") or ""))
    return f'<section class="content-section"><div class="section-heading"><h2>Council</h2><p>独立路线与综合判断</p></div><p class="council-synthesis">{synthesis}</p><ul class="council-routes">{route_html}</ul></section>'


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


def _metric_cell(label: str, value: Any) -> str:
    return f'<div class="metric-cell"><span>{escape(label)}</span><strong>{escape(_format_value(value))}</strong></div>'


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
.page-heading { margin-bottom:22px; }.page-heading h1,.detail-heading h1 { margin:2px 0 0; font-size:28px; line-height:1.2; }.eyebrow,.brand-mark { margin:0; color:var(--blue); font-size:12px; font-weight:800; text-transform:uppercase; }.muted,.section-heading p { color:var(--muted); }
.button { display:inline-flex; min-height:38px; align-items:center; justify-content:center; padding:8px 14px; border:1px solid transparent; border-radius:5px; font-weight:700; text-decoration:none; cursor:pointer; }.button.primary { background:var(--green); color:#fff; }.button.secondary { border-color:var(--blue); color:var(--blue); background:#fff; }.button.danger { border-color:var(--red); color:var(--red); background:#fff; }
.status-strip { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); border:1px solid var(--line); background:var(--surface); border-radius:6px; overflow:hidden; }.status-stat { padding:16px 18px; display:flex; justify-content:space-between; border-right:1px solid var(--line); }.status-stat:last-child{border-right:0}.status-stat span { color:var(--muted); }.status-stat strong { font-size:21px; }.tone-blue strong{color:var(--blue)}.tone-amber strong{color:var(--amber)}.tone-green strong{color:var(--green)}.tone-red strong{color:var(--red)}
.job-section,.new-research,.content-section,.timeline-section { margin-top:34px; }.section-heading { margin-bottom:12px; border-bottom:1px solid var(--line); padding-bottom:9px; }.section-heading h2,.timeline-section h2 { margin:0; font-size:18px; }.section-heading p { margin:0; }
.job-table { border:1px solid var(--line); border-radius:6px; overflow:hidden; background:var(--surface); }.job-table-head,.job-row { display:grid; grid-template-columns:minmax(280px,2fr) minmax(150px,1fr) 120px 135px 150px; align-items:center; gap:12px; padding:11px 14px; }.job-table-head { background:#e9edec; color:var(--muted); font-size:12px; font-weight:700; }.job-row { min-height:68px; text-decoration:none; border-top:1px solid var(--line); }.job-row:hover { background:#f7faf8; }.job-main { display:grid; gap:3px; }.job-main strong { font-size:15px; }.job-main span,.job-row time,.job-stage { color:var(--muted); font-size:12px; overflow-wrap:anywhere; }
.status-badge { display:inline-flex; min-height:26px; align-items:center; padding:3px 8px; border:1px solid var(--line); border-radius:999px; white-space:nowrap; font-size:12px; font-weight:700; }.status-researching,.status-verifying,.status-allocating { color:var(--blue); background:var(--blue-soft); border-color:#bad4df; }.status-completed { color:var(--green); background:var(--green-soft); border-color:#b9d8c7; }.status-blocked,.status-failed { color:var(--red); background:var(--red-soft); border-color:#e7bdb7; }.status-review_required,.status-queued { color:var(--amber); background:var(--amber-soft); border-color:#e6d09f; }
.verdict-accept{color:var(--green)}.verdict-reject,.verdict-block{color:var(--red)}.verdict-iterate,.verdict-partial{color:var(--amber)}
.research-form { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px 18px; padding:20px; border:1px solid var(--line); border-radius:6px; background:var(--surface); }.field { display:grid; gap:6px; }.field label { font-weight:700; }.field input,.field textarea,.field select,.fixed-contract { width:100%; border:1px solid #aeb8bc; border-radius:4px; padding:9px 10px; background:#fff; color:var(--ink); }.fixed-contract { background:#f3f6f5; color:var(--muted); }.field textarea { resize:vertical; min-height:160px; }.span-2 { grid-column:span 2; }.form-actions { display:flex; align-items:center; justify-content:space-between; gap:20px; border-top:1px solid var(--line); padding-top:16px; }.form-actions p { margin:0; color:var(--muted); }
.breadcrumbs { display:flex; gap:8px; color:var(--muted); margin-bottom:22px; }.breadcrumbs a { color:var(--blue); }.detail-heading { align-items:flex-start; }.detail-heading>div { max-width:900px; }.idea-summary { max-width:900px; white-space:pre-line; color:#3d4a50; font-size:15px; }.identity-band { margin-top:22px; display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); border:1px solid var(--line); background:#fff; border-radius:6px; }.identity-band div { padding:13px 15px; border-right:1px solid var(--line); display:grid; gap:2px; }.identity-band div:last-child{border-right:0}.identity-band span { color:var(--muted); font-size:12px; }.identity-band strong { overflow-wrap:anywhere; }
.stage-list { list-style:none; margin:12px 0 0; padding:0; display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); border:1px solid var(--line); border-radius:6px; overflow:hidden; }.stage { min-height:70px; padding:13px; display:flex; gap:10px; align-items:flex-start; background:#fff; border-right:1px solid var(--line); }.stage:last-child{border-right:0}.stage-dot { width:9px; height:9px; border-radius:50%; margin-top:6px; background:#aab3b6; flex:none; }.stage>div { display:grid; }.stage span:last-child { color:var(--muted); font-size:12px; }.stage-done .stage-dot,.stage-pass .stage-dot{background:var(--green)}.stage-active .stage-dot{background:var(--blue)}.stage-blocked .stage-dot{background:var(--red)}
.decision-panel { margin-top:26px; padding:18px; border:1px solid var(--line); border-left:4px solid var(--blue); background:#fff; border-radius:5px; }.decision-panel.verdict-accept{border-left-color:var(--green)}.decision-panel.verdict-reject,.decision-panel.verdict-block{border-left-color:var(--red)}.decision-head { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:16px; }.decision-head div { display:grid; }.decision-head span { color:var(--muted); font-size:12px; }.decision-head strong { font-size:16px; }.decision-list { margin-top:12px; }.decision-list ul { margin:6px 0 0; padding-left:20px; }
.metric-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); border:1px solid var(--line); background:#fff; border-radius:6px; overflow:hidden; }.metric-cell { min-height:82px; display:grid; align-content:center; gap:4px; padding:12px 14px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); }.metric-cell span { color:var(--muted); font-size:12px; }.metric-cell strong { font-size:20px; overflow-wrap:anywhere; }
.definition-list { margin:0; border:1px solid var(--line); background:#fff; border-radius:6px; overflow:hidden; }.definition-list>div { display:grid; grid-template-columns:180px minmax(0,1fr); border-top:1px solid var(--line); }.definition-list>div:first-child{border-top:0}.definition-list dt { padding:12px 14px; background:#eef1f0; font-weight:700; }.definition-list dd { margin:0; padding:12px 14px; white-space:pre-line; overflow-wrap:anywhere; }
.chart-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }.chart-grid figure { margin:0; border:1px solid var(--line); border-radius:6px; background:#fff; overflow:hidden; }.chart-grid img { display:block; width:100%; aspect-ratio:16/9; object-fit:contain; background:#fff; }.chart-grid figcaption { padding:9px 11px; border-top:1px solid var(--line); color:var(--muted); }
.council-synthesis { padding:14px; margin:0 0 12px; background:var(--blue-soft); border-left:4px solid var(--blue); }.council-routes { list-style:none; margin:0; padding:0; display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }.council-routes li { border:1px solid var(--line); background:#fff; border-radius:5px; padding:12px; }.council-routes li>span { float:right; color:var(--muted); }.council-routes p { margin:8px 0 0; }
.artifact-list,.event-list { list-style:none; margin:0; padding:0; border:1px solid var(--line); background:#fff; border-radius:6px; overflow:hidden; }.artifact-list li { display:flex; justify-content:space-between; gap:20px; padding:10px 12px; border-top:1px solid var(--line); }.artifact-list li:first-child,.event-list li:first-child{border-top:0}.artifact-list a { color:var(--blue); overflow-wrap:anywhere; }.artifact-list span { color:var(--muted); }.event-list li { display:grid; grid-template-columns:150px 190px minmax(0,1fr); gap:12px; padding:9px 12px; border-top:1px solid var(--line); }.event-list time { color:var(--muted); }
.empty-state { padding:32px; border:1px dashed #aeb8bc; background:#fff; text-align:center; border-radius:6px; }.empty-state h3{margin:0 0 4px}.empty-state p{margin:0;color:var(--muted)}
.login-shell { min-height:100vh; display:grid; place-items:center; padding:24px; background:#e9edec; }.login-panel { width:min(420px,100%); padding:30px; background:#fff; border:1px solid var(--line); border-radius:6px; box-shadow:0 12px 36px rgba(24,33,38,.12); }.login-panel h1 { margin:4px 0; font-size:28px; }.login-panel .muted { margin:0 0 24px; }.login-form { display:grid; gap:9px; }.login-form label { font-weight:700; }.login-form input { padding:10px; border:1px solid #aeb8bc; border-radius:4px; }.login-form button { margin-top:8px; min-height:40px; border:0; border-radius:4px; background:var(--green); color:#fff; font-weight:700; cursor:pointer; }.form-error { padding:9px 10px; color:var(--red); background:var(--red-soft); border:1px solid #e7bdb7; }
@media (max-width:900px){.workspace{padding:22px 16px 52px}.topbar{padding:0 16px}.status-strip{grid-template-columns:repeat(2,1fr)}.job-table-head{display:none}.job-row{grid-template-columns:1fr auto}.job-stage,.job-verdict,.job-row time{grid-column:1}.identity-band{grid-template-columns:repeat(2,1fr)}.identity-band div{border-bottom:1px solid var(--line)}.stage-list{grid-template-columns:1fr}.stage{border-right:0;border-bottom:1px solid var(--line)}.metric-grid{grid-template-columns:repeat(2,1fr)}.decision-head{grid-template-columns:repeat(2,1fr)}.chart-grid,.council-routes{grid-template-columns:1fr}}
@media (max-width:600px){.topbar-title{display:none}.page-heading,.detail-heading,.section-heading{align-items:flex-start;flex-direction:column}.research-form{grid-template-columns:1fr}.span-2{grid-column:span 1}.form-actions{align-items:stretch;flex-direction:column}.identity-band{grid-template-columns:1fr}.identity-band div{border-right:0}.metric-grid{grid-template-columns:1fr}.definition-list>div{grid-template-columns:1fr}.event-list li{grid-template-columns:1fr}.decision-head{grid-template-columns:1fr}.status-strip{grid-template-columns:1fr}.status-stat{border-right:0;border-bottom:1px solid var(--line)}}
"""
