from __future__ import annotations

from pathlib import Path

from factorforge.skills.factor_forge_step1.modules.report_ingestion.orchestration.wiring import build_step1_pipeline
from factorforge.skills.factor_forge_step1.modules.report_ingestion.adapters.html_report_adapter import HtmlReportAdapter


def run_html_smoke_test(project_root: str | Path) -> dict:
    root = Path(project_root)
    sample_html = """
    <html>
      <body>
        <h1>Sample Factor Report</h1>
        <h2>1. Investment Thesis</h2>
        <p>Turnover crowding predicts short-term reversal.</p>
        <h2>2. Key Variables</h2>
        <p>turnover, realized volatility, residual return</p>
      </body>
    </html>
    """.strip()

    adapter = HtmlReportAdapter(root / "data" / "report_ingestion" / "raw" / "html")
    source = adapter.from_url(
        url="https://example.com/sample-factor-report",
        html_content=sample_html,
        title="Sample Factor Report",
        metadata={"smoke_test": True},
    )

    pipeline = build_step1_pipeline(root)
    return pipeline.run(source)
