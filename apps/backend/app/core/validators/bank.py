"""국내 은행 사전 — 계좌번호 첫 그룹 prefix 매칭 + 한글 명칭 정규화.

전체 라우팅 테이블은 아니고, 시연용 시드. POC 평가 단계에서 확장한다.
"""

from __future__ import annotations

import re
from typing import Optional


# 계좌번호 첫 그룹 prefix → 은행명. 우리·국민·신한·하나·농협 등 주요 시중은행 중심.
# 같은 prefix 가 다른 은행과 겹치는 경우가 있어 데모용으로만 사용 (POC 명세에서 확정 가능).
_PREFIX_TO_BANK: dict[str, str] = {
    "1002": "우리은행",
    "1005": "우리은행",
    "1006": "우리은행",
    "110": "신한은행",
    "140": "신한은행",
    "356": "농협은행",
    "301": "농협은행",
    "302": "농협은행",
    "333": "농협은행",
    "100": "국민은행",
    "123": "국민은행",
    "200": "기업은행",
    "388": "하나은행",
    "199": "하나은행",
    "081": "하나은행",
    "081-": "하나은행",
    "267": "케이뱅크",
    "3333": "카카오뱅크",
    "9999": "토스뱅크",
}

# 한글 명칭 노이즈 정규화 (OCR 결과 한글 환각 완화)
_BANK_ALIASES: dict[str, str] = {
    "우리": "우리은행",
    "kb국민": "국민은행",
    "국민": "국민은행",
    "신한": "신한은행",
    "농협": "농협은행",
    "기업": "기업은행",
    "하나": "하나은행",
    "케이뱅크": "케이뱅크",
    "카뱅": "카카오뱅크",
    "카카오": "카카오뱅크",
    "토스": "토스뱅크",
}


def lookup_bank_by_account_prefix(account_number: str) -> Optional[str]:
    """계좌번호 첫 그룹/앞자리를 보고 은행명을 추정. 매칭 실패 시 None.

    가장 긴 prefix 매칭을 우선 (4 → 3자리).
    """
    if not account_number:
        return None
    head = re.split(r"[\s-]+", account_number, maxsplit=1)[0]
    if not head.isdigit():
        return None
    for length in (4, 3):
        if len(head) >= length and head[:length] in _PREFIX_TO_BANK:
            return _PREFIX_TO_BANK[head[:length]]
    return None


def normalize_bank_name(text: str) -> Optional[str]:
    """OCR 한글 환각으로 망가진 은행명 추정 (느슨한 부분 일치)."""
    if not text:
        return None
    t = text.replace(" ", "").lower()
    for key, name in _BANK_ALIASES.items():
        if key in t:
            return name
    return None
