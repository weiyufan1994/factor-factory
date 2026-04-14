from __future__ import annotations

from typing import List

from ..models.extraction_artifact import ExtractionArtifact, SectionCandidate, TextBlock


class SectionParser:
    def parse_candidates(self, artifact: ExtractionArtifact) -> List[SectionCandidate]:
        title_blocks = [b for b in artifact.blocks if self._is_title_like(b)]
        return self._merge_nearby_title_blocks(title_blocks)

    def _is_title_like(self, block: TextBlock) -> bool:
        if block.block_type == "title":
            return True
        text = block.text.strip()
        return bool(text and len(text) <= 80)

    def _estimate_section_confidence(self, block: TextBlock) -> float:
        return 0.8 if block.block_type == "title" else 0.4

    def _merge_nearby_title_blocks(self, title_blocks: List[TextBlock]) -> List[SectionCandidate]:
        result: List[SectionCandidate] = []
        for idx, block in enumerate(title_blocks, 1):
            result.append(
                SectionCandidate(
                    candidate_section_id=f"sec_{idx:03d}",
                    title_hint=block.text.strip() or None,
                    start_block_id=block.block_id,
                    end_block_id=block.block_id,
                    confidence=self._estimate_section_confidence(block),
                )
            )
        return result
