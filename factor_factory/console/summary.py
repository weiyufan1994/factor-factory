from __future__ import annotations

from html import escape
from pathlib import Path

from factor_factory.console.models import CampaignSummary, ConsoleTask


def render_dashboard(summaries: list[CampaignSummary], tasks: list[ConsoleTask] | None = None) -> str:
    tasks = tasks or []
    body = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>Factor Forge Console</title>",
        "<style>",
        _css(),
        "</style>",
        "</head>",
        "<body>",
        "<main>",
        "<h1>Factor Forge Console</h1>",
        _render_task_launcher(),
        '<section id="dashboard">',
        "<h2>Dashboard</h2>",
        _render_dashboard_table(summaries),
        "</section>",
        _render_tasks(tasks),
    ]
    for summary in summaries:
        body.append(_render_campaign(summary))
        body.append(_render_data_gap(summary))
        body.append(_render_queue(summary))
        body.append(_render_artifacts(summary))
    body.extend(["</main>", "</body>", "</html>"])
    return "\n".join(body)


def _render_task_launcher() -> str:
    default_catalog = "/Users/humphrey/projects/factorforge-data-api-runtime/catalogs/manus_data_catalog.json"
    return "\n".join(
        [
            '<section id="task-launcher">',
            "<h2>Task Launcher</h2>",
            '<form method="post" action="/tasks/miner">',
            '<label>Campaign ID<input name="campaign_id" value="current_data_api_catalog_20260629" required></label>',
            '<label>Execution workspace<input name="execution_workspace" value="/tmp/factorforge-miner-workspace" required></label>',
            '<label>Catalogs<textarea name="catalogs" rows="3" required>'
            f"{escape(default_catalog)}</textarea></label>",
            '<label>Screen window<input name="screen_window" value="2016-01-01..2025-07-11" required></label>',
            '<label>Universe<input name="universe" value="current_data_api_catalog" required></label>',
            '<button type="submit">Create Miner Campaign Task</button>',
            "</form>",
            '<p class="hint">Creates a task manifest only. Agent execution remains explicit and boundary-guarded.</p>',
            "</section>",
        ]
    )


def _render_tasks(tasks: list[ConsoleTask]) -> str:
    rows = [
        '<section id="task-log">',
        "<h2>Task Log</h2>",
    ]
    if not tasks:
        rows.extend(["<p>No pending Console tasks.</p>", "</section>"])
        return "\n".join(rows)
    rows.extend(
        [
            "<table>",
            "<thead><tr><th>Task</th><th>Type</th><th>Campaign</th><th>Workspace</th><th>Agent handoff</th></tr></thead>",
            "<tbody>",
        ]
    )
    for task in tasks:
        handoff = (
            "Use factor-forge-miner to execute "
            f"{task.task_id} from {Path(task.repo_root) / 'factor_research' / 'console' / 'tasks' / (task.task_id + '.json')}"
        )
        rows.append(
            "<tr>"
            f"<td>{escape(task.task_id)}</td>"
            f"<td>{escape(task.task_type)}</td>"
            f"<td>{escape(task.campaign_id)}</td>"
            f"<td>{escape(task.workspace_root)}</td>"
            f"<td><code>{escape(handoff)}</code></td>"
            "</tr>"
        )
    rows.extend(["</tbody>", "</table>", "</section>"])
    return "\n".join(rows)


def _render_dashboard_table(summaries: list[CampaignSummary]) -> str:
    if not summaries:
        return "<p>No Miner campaigns discovered.</p>"
    rows = [
        "<table>",
        "<thead><tr><th>Campaign</th><th>Verdict</th><th>Candidates</th><th>Research Queue</th><th>Data Gaps</th><th>Requests</th></tr></thead>",
        "<tbody>",
    ]
    for summary in summaries:
        rows.append(
            "<tr>"
            f"<td>{escape(summary.campaign_id)}</td>"
            f"<td><strong>{escape(summary.verdict)}</strong></td>"
            f"<td>{summary.candidate_count}</td>"
            f"<td>{summary.research_queue_count}</td>"
            f"<td>{summary.data_gap_count}</td>"
            f"<td>{summary.data_request_count}</td>"
            "</tr>"
        )
    rows.extend(["</tbody>", "</table>"])
    return "\n".join(rows)


def _render_campaign(summary: CampaignSummary) -> str:
    status_rows = "".join(
        f"<li>{escape(status)}: {count}</li>" for status, count in sorted(summary.template_status_counts.items())
    )
    blockers = _list_items(summary.blockers) or "<li>None</li>"
    next_actions = _list_items(summary.next_actions) or "<li>None</li>"
    return "\n".join(
        [
            '<section id="campaign">',
            f"<h2>Campaign: {escape(summary.campaign_id)}</h2>",
            f"<p><strong>Verdict:</strong> {escape(summary.verdict)}</p>",
            f"<p><strong>Workspace:</strong> {escape(summary.workspace_root)}</p>",
            "<h3>Key Metrics</h3>",
            "<ul>",
            f"<li>Candidates: {summary.candidate_count}</li>",
            f"<li>Cheap-screen passed: {summary.cheap_screen_passed}</li>",
            f"<li>Research queue: {summary.research_queue_count}</li>",
            f"<li>Data gaps: {summary.data_gap_count}</li>",
            f"<li>Data requests: {summary.data_request_count}</li>",
            "</ul>",
            "<h3>Template Status</h3>",
            f"<ul>{status_rows or '<li>None</li>'}</ul>",
            "<h3>Blockers</h3>",
            f"<ul>{blockers}</ul>",
            "<h3>Next Actions</h3>",
            f"<ul>{next_actions}</ul>",
            f"<p class=\"boundary\"><strong>Boundary:</strong> {escape(summary.boundary_statement)}</p>",
            "</section>",
        ]
    )


def _render_data_gap(summary: CampaignSummary) -> str:
    return "\n".join(
        [
            '<section id="data-gap">',
            "<h2>Data Gap</h2>",
            f"<p>Open data/API gaps: <strong>{summary.data_gap_count}</strong></p>",
            f"<p>Formal data requests: <strong>{summary.data_request_count}</strong></p>",
            "</section>",
        ]
    )


def _render_queue(summary: CampaignSummary) -> str:
    text = "Current campaign has candidates queued for handoff." if summary.research_queue_count else "No candidates are currently queued for Ultimate handoff."
    return "\n".join(
        [
            '<section id="research-queue">',
            "<h2>Research Queue</h2>",
            f"<p>Research queue count: <strong>{summary.research_queue_count}</strong></p>",
            f"<p>{escape(text)}</p>",
            "</section>",
        ]
    )


def _render_artifacts(summary: CampaignSummary) -> str:
    workspace = Path(summary.workspace_root)
    links = []
    for label, rel_path in sorted(summary.artifact_paths.items()):
        target = workspace / rel_path
        links.append(f'<li><a href="{escape(target.as_uri())}">{escape(label)}</a>: {escape(rel_path)}</li>')
    return "\n".join(
        [
            '<section id="artifacts">',
            "<h2>Artifact Links</h2>",
            f"<ul>{''.join(links) or '<li>None</li>'}</ul>",
            "</section>",
        ]
    )


def _list_items(values: list[str]) -> str:
    return "".join(f"<li>{escape(value)}</li>" for value in values)


def _css() -> str:
    return """
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f7f7f4; color: #202124; }
main { max-width: 1120px; margin: 0 auto; padding: 32px 20px 56px; }
section { margin-top: 24px; padding-top: 8px; border-top: 1px solid #d9d9d0; }
h1 { font-size: 32px; margin: 0 0 8px; }
h2 { font-size: 22px; margin: 16px 0 12px; }
h3 { font-size: 16px; margin: 16px 0 8px; }
table { width: 100%; border-collapse: collapse; background: #ffffff; }
th, td { padding: 10px 12px; border: 1px solid #d9d9d0; text-align: left; }
th { background: #ecece5; }
a { color: #155e75; }
form { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; background: #ffffff; border: 1px solid #d9d9d0; padding: 16px; }
label { display: grid; gap: 6px; font-weight: 600; }
input, textarea { font: inherit; padding: 8px 10px; border: 1px solid #b8b8ad; background: #fff; }
button { width: fit-content; padding: 9px 14px; border: 1px solid #155e75; background: #155e75; color: #fff; font-weight: 700; cursor: pointer; }
code { overflow-wrap: anywhere; }
.hint { color: #555; }
.boundary { padding: 12px; background: #fff8e1; border: 1px solid #ebd28a; }
"""
