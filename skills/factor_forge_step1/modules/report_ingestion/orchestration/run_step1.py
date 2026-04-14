from __future__ import annotations

from pathlib import Path

from factorforge.skills.factor_forge_step1.modules.report_ingestion.orchestration.wiring import build_step1_pipeline
from factorforge.skills.factor_forge_step1.modules.report_ingestion.adapters.html_report_adapter import HtmlReportAdapter
from factorforge.skills.factor_forge_step1.modules.report_ingestion.adapters.s3_pdf_adapter import S3PdfAdapter


def run_step1_for_html(project_root: str | Path, html_path: str | Path) -> dict:
    root = Path(project_root)
    adapter = HtmlReportAdapter(root / "data" / "report_ingestion" / "raw" / "html")
    source = adapter.from_local_file(html_path)
    pipeline = build_step1_pipeline(root)
    return pipeline.run(source)


def run_step1_for_s3_pdf(project_root: str | Path, s3_client, bucket: str, key: str, prefix: str) -> dict:
    root = Path(project_root)
    adapter = S3PdfAdapter(
        bucket=bucket,
        prefix=prefix,
        cache_root=root / "data" / "report_ingestion" / "raw" / "pdf",
        s3_client=s3_client,
    )
    source = adapter.build_source_from_key(key)
    source = adapter.cache_pdf(source)
    pipeline = build_step1_pipeline(root)
    return pipeline.run(source)
