from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from ..models.extraction_artifact import (
    ExtractionArtifact,
    SectionCandidate,
    TextBlock,
    VisualCandidate,
)
from ..registry.report_source_contract import ReportSource


class PdfTextExtractor:
    def __init__(self, cache_root: str | Path, pdf_backend: str = "pymupdf"):
        self.cache_root = Path(cache_root)
        self.pdf_backend = pdf_backend

    def extract(self, source: ReportSource) -> ExtractionArtifact:
        pdf_path = Path(source.local_cache_path or "")
        blocks = self._extract_blocks(pdf_path)
        artifact = ExtractionArtifact(
            report_id=source.report_id,
            source_type=source.source_type,
            raw_text_path=self._save_raw_text_markdown(source.report_id, blocks),
            blocks=blocks,
            section_candidates=self._build_section_candidates(blocks),
            visual_candidates=self._build_visual_candidates(blocks),
            extraction_notes=[f"pdf_backend={self.pdf_backend}", f"block_count={len(blocks)}"],
            metadata={
                "title": source.title,
                "broker": source.broker,
                "source_uri": source.source_uri,
                "local_cache_path": source.local_cache_path,
            },
        )
        return artifact

    def _extract_blocks(self, pdf_path: Path) -> List[TextBlock]:
        if not pdf_path.exists():
            raise FileNotFoundError(f"pdf not found: {pdf_path}")

        blocks: List[TextBlock] = []
        backend = (self.pdf_backend or '').lower()

        if backend in {'pypdf', 'auto'}:
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(pdf_path))
                for page_idx, page in enumerate(reader.pages, start=1):
                    text = (page.extract_text() or '').strip()
                    if not text:
                        continue
                    raw_block = {"text": text, "bbox": None}
                    blocks.append(
                        TextBlock(
                            block_id=f"p{page_idx:03d}_b001",
                            page_num=page_idx,
                            block_type=self._classify_block_type(raw_block),
                            text=text,
                            bbox=None,
                            metadata={"char_count": len(text), "backend": "pypdf"},
                        )
                    )
                if blocks:
                    return blocks
            except Exception as e:
                if backend == 'pypdf':
                    raise RuntimeError(f"pypdf unavailable or failed: {e}")

        try:
            import fitz  # PyMuPDF fallback
            doc = fitz.open(pdf_path)
            for page_idx, page in enumerate(doc, start=1):
                raw_blocks = page.get_text("blocks")
                for block_idx, raw in enumerate(raw_blocks, start=1):
                    x0, y0, x1, y1, text, *_rest = raw
                    text = (text or "").strip()
                    if not text:
                        continue
                    raw_block = {
                        "bbox": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
                        "text": text,
                    }
                    blocks.append(
                        TextBlock(
                            block_id=f"p{page_idx:03d}_b{block_idx:03d}",
                            page_num=page_idx,
                            block_type=self._classify_block_type(raw_block),
                            text=text,
                            bbox=raw_block["bbox"],
                            metadata={"char_count": len(text), "backend": "fitz"},
                        )
                    )
            doc.close()
            return blocks
        except Exception as e:
            raise RuntimeError(f"no available PDF backend succeeded (pypdf/fitz): {e}")

    def _classify_block_type(self, raw_block: Dict[str, Any]) -> str:
        text = raw_block.get("text", "").strip()
        if not text:
            return "noise"
        if len(text) <= 40 and (text[:1].isdigit() or "第" in text[:2]):
            return "title"
        if any(k in text.lower() for k in ["table", "表", "tbl"]):
            return "table_hint"
        if any(k in text.lower() for k in ["figure", "fig", "图"]):
            return "figure_hint"
        if any(k in text for k in ["=", "∑", "β", "α", "corr", "rank("]):
            return "formula_hint"
        if len(text) <= 100:
            return "title" if text.count(" ") < 8 else "paragraph"
        return "paragraph"

    def _build_section_candidates(self, blocks: List[TextBlock]) -> List[SectionCandidate]:
        result: List[SectionCandidate] = []
        titles = [b for b in blocks if b.block_type == "title"]
        for idx, block in enumerate(titles, start=1):
            result.append(
                SectionCandidate(
                    candidate_section_id=f"sec_{idx:03d}",
                    title_hint=block.text[:120],
                    start_block_id=block.block_id,
                    end_block_id=block.block_id,
                    confidence=0.75,
                    metadata={"page_num": block.page_num},
                )
            )
        return result

    def _build_visual_candidates(self, blocks: List[TextBlock]) -> List[VisualCandidate]:
        result: List[VisualCandidate] = []
        for idx, block in enumerate(blocks, start=1):
            if block.block_type in {"table_hint", "figure_hint", "formula_hint"}:
                result.append(
                    VisualCandidate(
                        visual_id=f"vis_{idx:03d}",
                        page_num=block.page_num,
                        visual_type=block.block_type.replace("_hint", ""),
                        caption_hint=block.text[:120],
                        related_block_ids=[block.block_id],
                    )
                )
        return result

    def _save_raw_text_markdown(self, report_id: str, blocks: List[TextBlock]) -> str:
        out_dir = self.cache_root / report_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "raw_text.md"
        parts = []
        for block in blocks:
            parts.append(f"<!-- {block.block_id} page={block.page_num} type={block.block_type} -->\n{block.text}")
        out_path.write_text("\n\n".join(parts), encoding="utf-8")
        return str(out_path)
