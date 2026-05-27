"""혼합 문서 분리 (Phase 2-C).

여러 종류의 문서가 한 PDF 에 섞인 경우를 가정하고, 각 페이지를
`document_classifier.classify_document` 로 분류한 뒤 연속 같은 유형의
페이지를 하나의 segment 로 묶는다.

규칙:
- 같은 type 의 연속 페이지 = 하나의 segment
- type 바뀌면 새 segment 시작
- type='freeform' 이 연속될 때, 직전 segment 와 가까운 페이지면 직전에 흡수
  (페이지 1장 미분류로 인한 과도한 분할 방지)
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.document_classifier import classify_document
from app.utils.logger import logger


async def segment_documents(
    image_files: list[str],
    *,
    max_concurrency: int = 1,
) -> list[dict[str, Any]]:
    """페이지별 분류 + 연속 그룹화.

    Args:
        image_files: 페이지 순서대로 정렬된 이미지 경로
        max_concurrency: vLLM 동시 호출 수 (단일 GPU 환경에선 1 권장)

    Returns:
        [
          {
            "document_type": "merchant_application",
            "pages": [1, 2, 3],
            "page_count": 3,
            "classifications": [
              {"page": 1, "document_type": "merchant_application", "raw_response": "...", "processing_time_ms": 250},
              ...
            ],
          },
          ...
        ]
    """
    if not image_files:
        return []

    # 페이지별 분류 — 단일 GPU 환경에서 동시 호출은 backpressure 위험 → 기본 순차
    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def _one(idx: int, path: str) -> dict:
        async with semaphore:
            try:
                cls = await classify_document(path)
                return {
                    "page": idx + 1,
                    "document_type": cls["document_type"],
                    "raw_response": cls["raw_response"],
                    "processing_time_ms": cls["processing_time_ms"],
                }
            except Exception as e:
                logger.warning(f"segmenter: page {idx+1} classify failed: {e}")
                return {
                    "page": idx + 1,
                    "document_type": "freeform",
                    "raw_response": f"error: {e}",
                    "processing_time_ms": 0,
                }

    classifications = await asyncio.gather(*[_one(i, p) for i, p in enumerate(image_files)])

    # 연속 같은 유형 그룹화
    segments: list[dict] = []
    for c in classifications:
        if segments and segments[-1]["document_type"] == c["document_type"]:
            segments[-1]["pages"].append(c["page"])
            segments[-1]["classifications"].append(c)
        else:
            # 직전 segment 가 다른 type 인데 현재가 freeform 이고 한 장이면 직전에 흡수 시도
            segments.append(
                {
                    "document_type": c["document_type"],
                    "pages": [c["page"]],
                    "classifications": [c],
                }
            )

    # freeform 단일 페이지 흡수 규칙 — segments 가 [A, freeform(1), A] 같은 형태일 때
    # 가운데 freeform 을 양쪽에 흡수 (단순 동일 type 일 때만)
    cleaned: list[dict] = []
    i = 0
    while i < len(segments):
        s = segments[i]
        if (
            s["document_type"] == "freeform"
            and len(s["pages"]) == 1
            and cleaned
            and i + 1 < len(segments)
            and cleaned[-1]["document_type"] == segments[i + 1]["document_type"]
        ):
            # 양쪽 합치고 가운데 freeform 도 합침
            cleaned[-1]["pages"].extend(s["pages"] + segments[i + 1]["pages"])
            cleaned[-1]["classifications"].extend(s["classifications"] + segments[i + 1]["classifications"])
            i += 2
            continue
        cleaned.append(s)
        i += 1

    for s in cleaned:
        s["page_count"] = len(s["pages"])
    return cleaned
