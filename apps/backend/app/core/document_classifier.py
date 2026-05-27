"""자동 문서 유형 분류 (2-A).

vLLM(Qwen2.5-VL) 의 OpenAI 호환 chat API 를 호출해 이미지 한 장으로
문서 유형을 한 단어로 판단한다. 결과를 DocumentType 으로 매핑하면
사용자가 freeform/auto 로 업로드해도 적절한 추출기로 자동 라우팅된다.
"""

from __future__ import annotations

import base64
import io
import time
from typing import Any, Optional

import httpx
from PIL import Image

from app.core.region_ocr import VLLM_BASE, VLLM_MODEL


# DocumentType 값
DOC_TYPES = ("merchant_application", "id_card", "bank_book", "business_reg", "freeform")

# 한글 응답 → DocumentType 매핑 (alias 다수)
_HANGUL_TO_TYPE: dict[str, str] = {
    # 가맹점 가입신청서
    "가맹점": "merchant_application",
    "가맹점가입신청서": "merchant_application",
    "가맹점 가입신청서": "merchant_application",
    "가맹점신청서": "merchant_application",
    "가입신청서": "merchant_application",
    "신청서": "merchant_application",
    # 신분증
    "신분증": "id_card",
    "주민등록증": "id_card",
    "운전면허증": "id_card",
    "운전면허": "id_card",
    "외국인등록증": "id_card",
    "여권": "id_card",
    # 통장 사본
    "통장": "bank_book",
    "통장사본": "bank_book",
    "통장 사본": "bank_book",
    "예금통장": "bank_book",
    # 사업자등록증
    "사업자등록증": "business_reg",
    "사업자": "business_reg",
    # 기타
    "기타": "freeform",
    "기타문서": "freeform",
    "알수없음": "freeform",
    "알 수 없음": "freeform",
    "unknown": "freeform",
    "other": "freeform",
}

CLASSIFICATION_PROMPT = (
    "이 이미지가 어떤 종류의 한국 금융권 문서인지 다음 중에서 하나만 골라 한 단어로 답하세요. "
    "다른 설명, 번역, 부연 설명은 절대 출력하지 마세요.\n"
    "선택지: 가맹점가입신청서, 신분증, 통장사본, 사업자등록증, 기타\n"
    "답:"
)


def _encode_png_to_data_uri(img: Image.Image, max_side: int = 1280) -> str:
    """분류용 — 큰 이미지는 1280px 로 다운샘플링해서 token 절약."""
    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _parse_response(text: str) -> str:
    """모델 응답에서 DocumentType 추출. 매칭 실패 시 'freeform'."""
    if not text:
        return "freeform"
    normalized = text.strip().replace("\n", " ").lower()
    # 공백 제거 매칭 우선
    no_space = normalized.replace(" ", "")
    for key, doc_type in _HANGUL_TO_TYPE.items():
        if key.replace(" ", "").lower() == no_space:
            return doc_type
    # 부분 매칭 (가장 긴 키부터)
    for key in sorted(_HANGUL_TO_TYPE.keys(), key=len, reverse=True):
        if key.lower() in normalized:
            return _HANGUL_TO_TYPE[key]
    return "freeform"


async def classify_document(
    image_path: str,
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """이미지 한 장의 문서 유형 분류.

    Returns:
        {
            "document_type": str,
            "raw_response": str,
            "processing_time_ms": int,
        }
    """
    image = Image.open(image_path).convert("RGB")
    data_uri = _encode_png_to_data_uri(image)

    payload = {
        "model": VLLM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_uri}},
                    {"type": "text", "text": CLASSIFICATION_PROMPT},
                ],
            }
        ],
        "max_tokens": 24,
        "temperature": 0.0,
    }
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(f"{VLLM_BASE}/v1/chat/completions", json=payload)
        r.raise_for_status()
        data = r.json()
    raw_text = ""
    try:
        raw_text = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        pass
    document_type = _parse_response(raw_text)
    return {
        "document_type": document_type,
        "raw_response": raw_text.strip(),
        "processing_time_ms": int((time.perf_counter() - started) * 1000),
    }
