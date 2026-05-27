"""Grounding (근거 기반 검증) + PII (개인정보 탐지/마스킹) 테스트."""

import pytest

from app.core.extractors.base import ExtractedField
from app.core.validators import (
    apply_grounding,
    apply_masking_policy,
    detect_pii_in_text,
    is_grounded,
)


def _f(name: str, value: str, source_match: str | None = None, conf: float = 0.9) -> ExtractedField:
    return ExtractedField(
        name=name,
        value=value,
        confidence=conf,
        validation_status="ok",
        source_match=source_match if source_match is not None else value,
    )


# ---------- Grounding ----------

@pytest.mark.unit
def test_grounding_exact_match():
    raw = "사업자등록번호 220-81-62517 / 상호 (주)테스트"
    ok, mode = is_grounded("220-81-62517", "220-81-62517", raw)
    assert ok and mode == "exact"


@pytest.mark.unit
def test_grounding_normalized_match():
    # 추출값에는 공백 없지만 raw 에는 공백
    raw = "220 - 81 - 62517"
    ok, mode = is_grounded("220-81-62517", "220-81-62517", raw)
    assert ok and mode == "normalized"


@pytest.mark.unit
def test_grounding_absent():
    raw = "다른 텍스트만 있음"
    ok, mode = is_grounded("220-81-62517", "220-81-62517", raw)
    assert not ok and mode == "absent"


@pytest.mark.unit
def test_apply_grounding_demotes_hallucinated_field():
    raw = "상호 (주)테스트, 대표자 김우리"
    fields = [
        _f("merchant_name", "(주)테스트"),
        _f("ghost_field", "환각값123", source_match="환각값123"),  # raw 에 없음
    ]
    stats = apply_grounding(fields, raw)
    assert stats["grounded"] == 1
    assert stats["ungrounded"] == 1
    # 환각 필드는 validation_status='ungrounded', confidence 절반
    ghost = next(f for f in fields if f.name == "ghost_field")
    assert ghost.validation_status == "ungrounded"
    assert ghost.confidence <= 0.5
    assert "근거 미발견" in (ghost.notes or "")


@pytest.mark.unit
def test_apply_grounding_preserves_grounded_field_status():
    raw = "사업자등록번호 220-81-62517"
    f = _f("business_registration_number", "220-81-62517", conf=0.95)
    f.validation_status = "ok"
    apply_grounding([f], raw)
    # validation_status 유지, confidence 약간만 변동(또는 그대로)
    assert f.validation_status == "ok"
    assert f.confidence >= 0.9


# ---------- PII ----------

@pytest.mark.unit
def test_masking_partial_for_phone():
    fields = [_f("phone_number", "02-1234-5678")]
    stats = apply_masking_policy(fields, "partial")
    assert stats["sensitive"] == 1
    assert fields[0].masked_value == "02-****-5678"


@pytest.mark.unit
def test_masking_partial_for_rrn():
    fields = [_f("resident_registration_number", "831225-1820422")]
    apply_masking_policy(fields, "partial")
    assert fields[0].masked_value == "831225-*******"


@pytest.mark.unit
def test_masking_partial_for_email():
    fields = [_f("email", "abcdef@example.com")]
    apply_masking_policy(fields, "partial")
    # 앞 2자 노출 + 나머지 *
    assert fields[0].masked_value is not None
    assert fields[0].masked_value.startswith("ab")
    assert "@example.com" in fields[0].masked_value


@pytest.mark.unit
def test_masking_full():
    fields = [_f("name", "홍길동")]
    apply_masking_policy(fields, "full")
    assert fields[0].masked_value == "***"


@pytest.mark.unit
def test_masking_none_exposes_value():
    fields = [_f("phone_number", "02-1234-5678")]
    stats = apply_masking_policy(fields, "none")
    assert stats["exposed"] == 1
    assert fields[0].masked_value == "02-1234-5678"


@pytest.mark.unit
def test_masking_skips_non_sensitive_fields():
    fields = [_f("business_category", "도소매")]
    stats = apply_masking_policy(fields, "full")
    assert stats["sensitive"] == 0
    # masked_value 변경 없음
    assert fields[0].masked_value is None


@pytest.mark.unit
def test_detect_pii_email_in_raw_text():
    raw = "문의: support@woori.com 또는 sales@example.co.kr 까지"
    found = detect_pii_in_text(raw)
    emails = [f for f in found if f["kind"] == "email"]
    values = sorted(f["value"] for f in emails)
    assert "sales@example.co.kr" in values
    assert "support@woori.com" in values


@pytest.mark.unit
def test_detect_pii_address_in_raw_text():
    raw = "사업장 주소: 서울특별시 강남구 테헤란로 100, 8층"
    found = detect_pii_in_text(raw)
    addrs = [f for f in found if f["kind"] == "address"]
    assert addrs
    assert "강남구" in addrs[0]["value"]
