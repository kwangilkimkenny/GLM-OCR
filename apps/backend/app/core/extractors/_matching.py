"""source_match → layout block 역검색 헬퍼."""

from __future__ import annotations

import re
from typing import Optional

from app.core.extractors.base import ExtractedField, LayoutBlock


def _normalize(s: str) -> str:
    """공백·하이픈 차이 제거."""
    return re.sub(r"[\s\-]+", "", s or "")


def attach_bbox(
    fields: list[ExtractedField],
    raw_blocks: Optional[list[LayoutBlock]],
) -> None:
    """각 ExtractedField 의 source_match 문자열을 raw_blocks 의 block_content
    에서 찾아 bbox·page_index 를 채워 넣는다 (in-place).

    매칭 규칙:
    - 1차: 부분 문자열 포함 (대소문자 무관, 원본 그대로)
    - 2차: 공백/하이픈 제거 후 비교 (OCR 자간 노이즈 흡수)
    - 가장 먼저 일치하는 블록을 사용. 같은 블록에 여러 필드가 들어가는 것은 허용.
    """
    if not raw_blocks:
        return
    if not fields:
        return

    blocks_norm: list[tuple[str, str, LayoutBlock]] = []
    for b in raw_blocks:
        content = b.get("block_content") or ""
        blocks_norm.append((content, _normalize(content), b))

    for f in fields:
        needle = f.source_match or f.value
        if not needle:
            continue
        needle_norm = _normalize(needle)

        match: Optional[LayoutBlock] = None
        for content, norm, block in blocks_norm:
            if needle in content:
                match = block
                break
        if match is None:
            for content, norm, block in blocks_norm:
                if needle_norm and needle_norm in norm:
                    match = block
                    break
        if match is None:
            continue

        bbox = match.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            try:
                f.bbox = tuple(int(round(float(v))) for v in bbox)  # type: ignore[assignment]
            except (TypeError, ValueError):
                pass
        page = match.get("page_index")
        if isinstance(page, int):
            f.page_index = page
