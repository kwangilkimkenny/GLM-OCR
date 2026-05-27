"""필드 추출기 공통 인터페이스.

추출 결과는 `ExtractedField` 단위. 신뢰도·검증 상태·마스킹 값·bbox·페이지 인덱스를 함께 갖는다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


ValidationStatus = str  # "ok" | "invalid" | "unverified"
ConsensusStatus = str   # "agreed" | "conflict" | "single"

# merge_results 가 만드는 layout 블록과 호환되는 dict 구조:
#   {"block_content": str, "bbox": [x0, y0, x1, y1] | None, "block_id": int, "page_index": int}
LayoutBlock = dict[str, Any]


@dataclass
class ExtractedField:
    name: str
    value: str
    confidence: float = 0.0
    bbox: Optional[tuple[int, int, int, int]] = None
    page_index: Optional[int] = None
    validation_status: ValidationStatus = "unverified"
    masked_value: Optional[str] = None
    source_match: Optional[str] = None
    notes: Optional[str] = None
    # 비교 모드(engine=both) 출처 — 어느 엔진(들)에서 잡혔는지
    engines: Optional[list[str]] = None
    consensus: Optional[ConsensusStatus] = None  # agreed | conflict | single

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExtractionResult:
    document_type: str
    fields: list[ExtractedField] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "document_type": self.document_type,
            "fields": [f.to_dict() for f in self.fields],
        }


class FieldExtractor(ABC):
    """문서 유형별 추출기 베이스."""

    document_type: str = ""

    @abstractmethod
    def extract(
        self,
        raw_text: str,
        raw_blocks: Optional[list[LayoutBlock]] = None,
    ) -> ExtractionResult:
        """OCR raw text 와 (선택) layout blocks 를 받아 필드 리스트를 돌려준다.

        raw_blocks 가 제공되면 각 필드의 source_match 를 블록 내용에서 역검색해
        bbox·page_index 를 채운다.
        """
        raise NotImplementedError
