"""개인정보(PII) 자동 탐지 + 마스킹 정책.

기존 추출기는 주민번호·계좌·휴대폰만 마스킹 했다. 이 모듈은:
1. 이메일·주소·이름 등 추가 PII 자동 탐지
2. masking_level 정책 (none / partial / full)
3. 응답에 PII 통계를 포함해 감사로그·시각화에 활용

기존 extractor 결과(fields) 에 마스킹 정책을 적용하고, raw_text 에서
추가로 발견된 PII 도 별도로 반환한다 (필드명 없이도 raw 단계에서 차단).
"""

from __future__ import annotations

import re
from typing import Iterable, Literal

from app.core.extractors.base import ExtractedField


MaskingLevel = Literal["none", "partial", "full"]


# ---------- 정규식 ----------

EMAIL_RE = re.compile(r"\b[\w.+\-]+@[\w-]+(?:\.[\w-]+)+\b")
# 한국 주소 패턴: 시·도 + 시·군·구 + ... (느슨)
ADDRESS_RE = re.compile(
    r"(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)"
    r"(?:특별시|광역시|특별자치시|특별자치도|도)?"
    r"\s*[가-힣]+(?:시|군|구)"
    r"[가-힣\d\s\-,.()]+"
)


# ---------- 마스킹 함수 ----------

def _mask_full(value: str) -> str:
    """완전 마스킹: 모든 영숫자·한글을 *로."""
    return re.sub(r"[\w가-힣]", "*", value)


def _mask_partial_text(value: str) -> str:
    """부분 마스킹: 앞 1자 + ... + 마지막 1자만 노출."""
    if len(value) <= 2:
        return _mask_full(value)
    return value[0] + "*" * (len(value) - 2) + value[-1]


def _mask_email(email: str) -> str:
    """이메일: local 첫 2자만 노출 + @ + 도메인."""
    if "@" not in email:
        return _mask_full(email)
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = _mask_full(local)
    else:
        masked_local = local[:2] + "*" * (len(local) - 2)
    return f"{masked_local}@{domain}"


def _mask_address(addr: str) -> str:
    """주소: 시·도 + 구·시·군 까지만 노출, 그 이후는 마스킹."""
    m = re.match(
        r"((?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)"
        r"(?:특별시|광역시|특별자치시|특별자치도|도)?\s*[가-힣]+(?:시|군|구))",
        addr,
    )
    if not m:
        return _mask_partial_text(addr)
    return m.group(1) + " " + "*" * max(3, len(addr) - len(m.group(1)) - 1)


# ---------- 마스킹 정책 ----------

# 어떤 필드명이 PII 인지
SENSITIVE_FIELD_NAMES: set[str] = {
    "resident_registration_number",
    "foreign_registration_number",
    "bank_account_number",
    "account_number",
    "phone_number",
    "email",
    "name",
    "representative_name",
    "beneficial_owner",
    "account_holder",
    "merchant_address",
    "business_address",
    "address",
}


def _mask_field_value(field_name: str, value: str) -> str:
    """필드명에 따라 적절한 부분 마스킹 적용."""
    if field_name in {"resident_registration_number", "foreign_registration_number"}:
        digits = re.sub(r"\D", "", value)
        if len(digits) == 13:
            return f"{digits[:6]}-{'*' * 7}"
    if field_name in {"bank_account_number", "account_number"}:
        parts = re.split(r"\s*-\s*", value)
        if len(parts) >= 2:
            masked = parts[:1] + ["*" * len(p) for p in parts[1:-1]] + parts[-1:]
            return "-".join(masked)
    if field_name == "phone_number":
        parts = re.split(r"\s*-\s*", value)
        if len(parts) == 3:
            return f"{parts[0]}-{'*' * len(parts[1])}-{parts[2]}"
    if field_name == "email":
        return _mask_email(value)
    if field_name in {"merchant_address", "business_address", "address"}:
        return _mask_address(value)
    if field_name in {"name", "representative_name", "beneficial_owner", "account_holder"}:
        return _mask_partial_text(value)
    return _mask_partial_text(value)


def apply_masking_policy(
    fields: Iterable[ExtractedField], level: MaskingLevel
) -> dict[str, int]:
    """추출 필드의 masked_value 를 마스킹 정책에 맞춰 갱신 (in-place).

    Returns:
        {"sensitive": N, "masked_partial": N, "masked_full": N, "exposed": N}
    """
    stats = {"sensitive": 0, "masked_partial": 0, "masked_full": 0, "exposed": 0}
    for f in fields:
        if f.name not in SENSITIVE_FIELD_NAMES:
            continue
        stats["sensitive"] += 1
        if level == "none":
            f.masked_value = f.value  # 마스킹 없음 (감사 로그 필요)
            stats["exposed"] += 1
        elif level == "partial":
            f.masked_value = _mask_field_value(f.name, f.value)
            stats["masked_partial"] += 1
        elif level == "full":
            f.masked_value = _mask_full(f.value)
            stats["masked_full"] += 1
    return stats


def detect_pii_in_text(raw_text: str) -> list[dict]:
    """추출 필드와 무관하게 raw_text 에서 추가 PII 탐지.

    Returns:
        [{"kind": "email"|"address", "value": str, "span": (start, end)}]
    """
    found: list[dict] = []
    if not raw_text:
        return found
    seen: set[tuple[str, str]] = set()
    for m in EMAIL_RE.finditer(raw_text):
        key = ("email", m.group(0))
        if key in seen:
            continue
        seen.add(key)
        found.append({"kind": "email", "value": m.group(0), "span": (m.start(), m.end())})
    for m in ADDRESS_RE.finditer(raw_text):
        key = ("address", m.group(0)[:30])
        if key in seen:
            continue
        seen.add(key)
        found.append({"kind": "address", "value": m.group(0).strip(), "span": (m.start(), m.end())})
    return found
