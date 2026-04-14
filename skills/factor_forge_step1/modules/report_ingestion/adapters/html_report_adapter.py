from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from ..registry.report_source_contract import ReportSource, normalize_report_source


class HtmlReportAdapter:
    def __init__(self, cache_root: str | Path):
        self.cache_root = Path(cache_root)
        self.cache_root.mkdir(parents=True, exist_ok=True)

    def from_local_file(
        self,
        file_path: str | Path,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> ReportSource:
        path = Path(file_path)
        return normalize_report_source(
            source_type="html",
            source_uri=str(path.resolve()),
            title=title or path.stem,
            metadata=metadata or {},
        )

    def from_url(
        self,
        url: str,
        html_content: str,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> ReportSource:
        source = normalize_report_source(
            source_type="html",
            source_uri=url,
            title=title,
            metadata=metadata or {},
        )
        return self.cache_html(source, html_content)

    def cache_html(self, source: ReportSource, html_content: str) -> ReportSource:
        local_dir = self.cache_root / source.report_id
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / "source.html"
        local_path.write_text(html_content, encoding="utf-8")
        source.local_cache_path = str(local_path)
        source.status = "cached"
        return source
