"""근거 기반 검증 (Grounding) — Near-Zero Hallucination 의 핵심.

추출기가 만든 ExtractedField 의 source_match 가 실제 raw OCR 텍스트에
존재하는지 검사한다. 존재하지 않으면 (즉 모델/정규식/표 파서가
환각으로 만들어낸 값) `validation_status` 를 'ungrounded' 로 강등하고
confidence 를 ÷2 로 낮춘다.

운영 규칙:
- raw_text 에 정확히 부분 일치 → grounded
- 공백/특수문자 제거 후 부분 일치 → grounded (fuzzy_normalized)
- 위 둘 다 실패 → ungrounded (사람 검수 필요)
"""

from __future__ import annotations

import re
from typing import Iterable

from app.core.extractors.base import ExtractedField


_STRIP_RE = re.compile(r"[\s\-\.\,\(\)\[\]/:|··]+")


def _normalize(s: str) -> str:
    return _STRIP_RE.sub("", s or "").casefold()


def is_grounded(value: str, source_match: str | None, raw_text: str) -> tuple[bool, str]:
    """value 또는 source_match 가 raw_text 에 실제 존재하는지.

    Returns:
        (grounded, mode) — mode: "exact" | "normalized" | "absent"
    """
    if not raw_text:
        return False, "absent"
    needle = source_match or value
    if not needle:
        return False, "absent"
    # 1) exact substring
    if needle in raw_text:
        return True, "exact"
    # 2) normalized (공백/하이픈/괄호 제거 후)
    n_needle = _normalize(needle)
    n_haystack = _normalize(raw_text)
    if n_needle and n_needle in n_haystack:
        return True, "normalized"
    # 3) 짧은 값(≤4글자) 은 일부분만 일치해도 ungrounded 로 간주 (false positive 방지)
    return False, "absent"


def apply_grounding(
    fields: Iterable[ExtractedField],
    raw_text: str,
) -> dict[str, int]:
    """ExtractedField 들에 grounding 결과를 in-place 반영.

    - grounded(exact): 변동 없음. notes 끝에 '근거 일치' 추가
    - grounded(normalized): notes 끝에 '근거 일치(정규화)' 추가
    - ungrounded: validation_status='ungrounded', confidence ÷ 2,
      notes 끝에 '⚠ 원본에서 근거 미발견' 추가

    Returns:
        {"grounded": N, "normalized": N, "ungrounded": N} 통계
    """
    stats = {"grounded": 0, "normalized": 0, "ungrounded": 0}
    for f in fields:
        ok, mode = is_grounded(f.value, f.source_match, raw_text)
        if mode == "exact":
            stats["grounded"] += 1
            _append_note(f, "근거 일치")
        elif mode == "normalized":
            stats["normalized"] += 1
            _append_note(f, "근거 일치(정규화)")
            # 정규화로만 매칭은 confidence 살짝 하향
            f.confidence = max(0.1, f.confidence * 0.9)
        else:
            stats["ungrounded"] += 1
            # 사전 validation_status 가 'ok' 였어도 ungrounded 로 강등
            f.validation_status = "ungrounded"
            f.confidence = max(0.05, f.confidence * 0.5)
            _append_note(f, "⚠ 원본에서 근거 미발견")
    return stats


def _append_note(f: ExtractedField, note: str) -> None:
    if not f.notes:
        f.notes = note
        return
    if note in f.notes:
        return
    f.notes = f.notes + "; " + note
