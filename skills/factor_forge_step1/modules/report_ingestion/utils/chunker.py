from __future__ import annotations

from typing import Any, Dict, List

from ..models.extraction_artifact import ExtractionArtifact


class ExtractionChunker:
    def __init__(self, max_chars: int = 6000, overlap_chars: int = 300):
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def chunk_for_report_map(self, artifact: ExtractionArtifact) -> List[Dict[str, Any]]:
        chunks: List[Dict[str, Any]] = []
        current: List[Dict[str, Any]] = []
        current_chars = 0

        for block in artifact.blocks:
            block_payload = {
                "block_id": block.block_id,
                "page_num": block.page_num,
                "block_type": block.block_type,
                "text": block.text,
                "metadata": block.metadata,
            }
            block_chars = len(block.text)
            if current and current_chars + block_chars > self.max_chars:
                chunks.append({"blocks": current})
                current = current[-1:] if self.overlap_chars > 0 and current else []
                current_chars = sum(len(x.get("text", "")) for x in current)
            current.append(block_payload)
            current_chars += block_chars

        if current:
            chunks.append({"blocks": current})
        return chunks
