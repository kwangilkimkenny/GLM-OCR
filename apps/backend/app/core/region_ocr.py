"""사용자가 지정한 영역(ROI)만 OCR — 양식 문서의 손글씨 칸 인식용.

전체 페이지를 거치지 않고 vLLM 의 OpenAI 호환 API 를 직접 호출해
영역별로 짧은 텍스트 응답을 받는다. 손글씨 hint 가 있으면 프롬프트를
"인쇄된 라벨을 무시하고 손글씨만 추출"로 변경한다.
"""

from __future__ import annotations

import asyncio
import base64
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

import httpx
from PIL import Image


# vLLM OpenAI-compatible endpoint
VLLM_BASE = os.environ.get("WOORI_VLLM_BASE", "http://localhost:8080")
VLLM_MODEL = os.environ.get("WOORI_VLLM_MODEL", "qwen2.5-vl-7b")

# 손글씨 / 인쇄 텍스트별 prompt
PROMPT_HANDWRITING = (
    "다음 이미지는 인쇄된 양식의 일부에 손글씨로 채워진 영역입니다. "
    "손글씨로 작성된 텍스트만 정확히 추출하세요. 인쇄된 라벨이나 안내 문구는 무시하세요. "
    "여러 줄이면 줄바꿈을 유지하고, 텍스트 외 설명·번역은 포함하지 마세요."
)
PROMPT_PRINTED = (
    "이 이미지 영역의 모든 텍스트를 정확히 추출하세요. "
    "표 셀이면 셀 내용만 한 줄로, 본문이면 줄바꿈을 유지하세요. "
    "추측·설명·번역 없이 인식한 텍스트만 출력하세요."
)


def _encode_png_to_data_uri(img: Image.Image) -> str:
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _clamp_bbox(bbox: list[int], width: int, height: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = bbox
    x0 = max(0, min(int(x0), width - 1))
    y0 = max(0, min(int(y0), height - 1))
    x1 = max(x0 + 1, min(int(x1), width))
    y1 = max(y0 + 1, min(int(y1), height))
    return x0, y0, x1, y1


async def _call_vllm_chat(
    image_data_uri: str,
    prompt: str,
    *,
    max_tokens: int = 256,
    timeout: float = 60.0,
) -> tuple[str, dict[str, Any]]:
    payload = {
        "model": VLLM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_data_uri}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(f"{VLLM_BASE}/v1/chat/completions", json=payload)
        r.raise_for_status()
        data = r.json()
    text = ""
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        pass
    return text.strip(), data


async def process_region(
    image: Image.Image,
    bbox: list[int],
    *,
    handwriting: bool,
    snapshot_dir: Optional[str] = None,
) -> dict[str, Any]:
    """한 영역을 잘라 vLLM 으로 보내고 결과 dict 반환.

    Returns:
        {bbox, text, raw_response_id, processing_time_ms, snapshot_path?}
    """
    width, height = image.size
    x0, y0, x1, y1 = _clamp_bbox(bbox, width, height)
    crop = image.crop((x0, y0, x1, y1))

    snapshot_path: Optional[str] = None
    if snapshot_dir:
        Path(snapshot_dir).mkdir(parents=True, exist_ok=True)
        snapshot_path = str(
            Path(snapshot_dir) / f"roi_{x0}_{y0}_{x1}_{y1}_{int(time.time()*1000)}.png"
        )
        crop.save(snapshot_path, format="PNG")

    data_uri = _encode_png_to_data_uri(crop)
    prompt = PROMPT_HANDWRITING if handwriting else PROMPT_PRINTED
    started = time.perf_counter()
    text, raw = await _call_vllm_chat(data_uri, prompt)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return {
        "bbox": [x0, y0, x1, y1],
        "text": text,
        "processing_time_ms": elapsed_ms,
        "snapshot_path": snapshot_path,
        "raw_id": raw.get("id"),
    }


async def process_regions(
    image_path: str,
    regions: list[dict[str, Any]],
    *,
    handwriting: bool,
    snapshot_dir: Optional[str] = None,
) -> list[dict[str, Any]]:
    """여러 영역을 순차 처리. vLLM single-GPU 환경에서 동시성은 backpressure 위험."""
    image = Image.open(image_path).convert("RGB")
    results: list[dict[str, Any]] = []
    for region in regions:
        name = region.get("name") or f"region_{len(results)+1}"
        bbox = region.get("bbox")
        if not bbox or len(bbox) != 4:
            results.append({"name": name, "error": "invalid bbox"})
            continue
        try:
            out = await process_region(
                image,
                bbox,
                handwriting=region.get("handwriting", handwriting),
                snapshot_dir=snapshot_dir,
            )
            out["name"] = name
            results.append(out)
        except Exception as e:
            results.append({"name": name, "bbox": bbox, "error": str(e)})
    return results
