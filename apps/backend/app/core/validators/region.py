"""행정구역 사전 — 시·도 + 서울 25개 구 시드.

OCR 한글 환각으로 "광진구" → "책전구" 같은 오인식이 발생할 때 Levenshtein
근사 매칭으로 가장 가까운 정식 행정구역명을 제안한다.
"""

from __future__ import annotations

import re
from typing import Optional


KR_PROVINCES: tuple[str, ...] = (
    "서울특별시",
    "부산광역시",
    "대구광역시",
    "인천광역시",
    "광주광역시",
    "대전광역시",
    "울산광역시",
    "세종특별자치시",
    "경기도",
    "강원특별자치도",
    "충청북도",
    "충청남도",
    "전북특별자치도",
    "전라남도",
    "경상북도",
    "경상남도",
    "제주특별자치도",
)

SEOUL_DISTRICTS: tuple[str, ...] = (
    "종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구",
    "성북구", "강북구", "도봉구", "노원구", "은평구", "서대문구", "마포구",
    "양천구", "강서구", "구로구", "금천구", "영등포구", "동작구", "관악구",
    "서초구", "강남구", "송파구", "강동구",
)


def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            curr[j] = min(
                prev[j] + 1,           # deletion
                curr[j - 1] + 1,       # insertion
                prev[j - 1] + (ca != cb),  # substitution
            )
        prev = curr
    return prev[-1]


def _best_match(token: str, candidates: tuple[str, ...], max_distance: int) -> Optional[str]:
    best: Optional[str] = None
    best_dist = max_distance + 1
    for c in candidates:
        d = _levenshtein(token, c)
        if d < best_dist:
            best, best_dist = c, d
    return best if best_dist <= max_distance else None


def _sliding_fuzzy(text: str, target: str, max_distance: int) -> Optional[str]:
    """text 안에서 target 과 길이가 같은 substring 중 거리 ≤ max_distance 인 가장 이른 토큰."""
    L = len(target)
    if L == 0 or len(text) < L:
        return None
    for i in range(len(text) - L + 1):
        token = text[i : i + L]
        if _levenshtein(token, target) <= max_distance:
            return token
    return None


def suggest_region(address: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """주소 문자열에서 (시·도, 서울 구, 보정 메모) 추정.

    - exact 일치하면 그대로 반환
    - 1~2 글자 거리 오차는 가장 가까운 정식명으로 보정 (메모에 원본 노출)
    - 매칭 실패는 (None, None, None)
    """
    if not address:
        return (None, None, None)

    notes: list[str] = []
    province: Optional[str] = None
    district: Optional[str] = None

    # 시·도
    for p in KR_PROVINCES:
        if p in address:
            province = p
            break
    if province is None:
        # 토큰 단위 fuzzy
        for token in re.findall(r"[가-힣]+", address)[:3]:
            cand = _best_match(token, KR_PROVINCES, max_distance=1)
            if cand:
                province = cand
                notes.append(f"province: {token} → {cand}")
                break

    # 서울 구
    if province == "서울특별시" or "서울" in address:
        for d in SEOUL_DISTRICTS:
            if d in address:
                district = d
                break
        if district is None:
            # 슬라이딩 윈도우 fuzzy — 거리 1 이내만 신뢰 (거리 2 는 false positive 다수)
            for d in SEOUL_DISTRICTS:
                token = _sliding_fuzzy(address, d, max_distance=1)
                if token and token != d:
                    district = d
                    notes.append(f"district: {token} → {d}")
                    break
                if token == d:
                    district = d
                    break

    note = "; ".join(notes) if notes else None
    return (province, district, note)
