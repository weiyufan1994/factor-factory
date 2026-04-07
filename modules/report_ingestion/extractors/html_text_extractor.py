from __future__ import annotations

from pathlib import Path
from typing import List

from ..models.extraction_artifact import (
    ExtractionArtifact,
    SectionCandidate,
    TextBlock,
    VisualCandidate,
)
from ..registry.report_source_contract import ReportSource


class HtmlTextExtractor:
    def __init__(self, cache_root: str | Path):
        self.cache_root = Path(cache_root)

    def extract(self, source: ReportSource) -> ExtractionArtifact:
        html_path = Path(source.local_cache_path or "")
        html_text = self._extract_main_content(html_path)
        blocks = self._html_to_blocks(html_text)
        artifact = ExtractionArtifact(
            report_id=source.report_id,
            source_type=source.source_type,
            raw_text_path=self._save_raw_text_markdown(source.report_id, blocks),
            blocks=blocks,
            section_candidates=self._build_section_candidates(blocks),
            visual_candidates=self._build_visual_candidates(blocks),
            extraction_notes=["html skeleton extractor output"],
        )
        return artifact

    def _extract_main_content(self, html_path: Path) -> str:
        return html_path.read_text(encoding="utf-8")

    def _html_to_blocks(self, html_text: str) -> List[TextBlock]:
        return []

    def _build_section_candidates(self, blocks: List[TextBlock]) -> List[SectionCandidate]:
        return []

    def _build_visual_candidates(self, blocks: List[TextBlock]) -> List[VisualCandidate]:
        return []

    def _save_raw_text_markdown(self, report_id: str, blocks: List[TextBlock]) -> str:
        out_dir = self.cache_root / report_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "raw_text.md"
        content = "\n\n".join(block.text for block in blocks)
        out_path.write_text(content, encoding="utf-8")
        return str(out_path)
