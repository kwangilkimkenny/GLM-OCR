"""두 엔진 결과 합의 병합 테스트."""

import pytest

from app.core.extractors import consensus_merge
from app.core.extractors.base import ExtractedField, ExtractionResult


def _f(name: str, value: str, conf: float = 0.7, status: str = "unverified", **kw) -> ExtractedField:
    return ExtractedField(name=name, value=value, confidence=conf, validation_status=status, **kw)


def _result(*fields: ExtractedField) -> ExtractionResult:
    return ExtractionResult(document_type="merchant_application", fields=list(fields))


@pytest.mark.unit
def test_consensus_agreed_when_same_value():
    primary = _result(_f("business_registration_number", "220-81-62517", conf=0.95, status="ok"))
    secondary = _result(_f("business_registration_number", "220-81-62517", conf=0.95, status="ok"))
    merged, summary = consensus_merge(primary, secondary)

    assert summary["agreed"] == 1
    assert summary["conflict"] == 0
    assert summary["single"] == 0

    f = merged.fields[0]
    assert f.consensus == "agreed"
    assert f.engines == ["qwen", "glm-ocr"]
    assert f.confidence >= 0.95
    assert f.validation_status == "ok"
    assert "교차검증 일치" in (f.notes or "")


@pytest.mark.unit
def test_consensus_conflict_when_same_field_different_values():
    primary = _result(_f("representative_name", "차정수"))
    secondary = _result(_f("representative_name", "치정수"))
    merged, summary = consensus_merge(primary, secondary)

    assert summary["conflict"] == 1
    assert summary["agreed"] == 0
    assert summary["single"] == 0

    f = merged.fields[0]
    assert f.consensus == "conflict"
    assert f.engines == ["qwen"]
    assert f.value == "차정수"  # primary 채택
    assert "불일치 후보" in (f.notes or "")
    assert "치정수" in (f.notes or "")


@pytest.mark.unit
def test_consensus_single_primary_only():
    primary = _result(_f("merchant_name", "(주)하사테크"))
    secondary = _result()  # 빈 결과
    merged, summary = consensus_merge(primary, secondary)

    assert summary["single"] == 1
    f = merged.fields[0]
    assert f.consensus == "single"
    assert f.engines == ["qwen"]


@pytest.mark.unit
def test_consensus_single_secondary_only():
    primary = _result()
    secondary = _result(_f("bank_name", "우리은행"))
    merged, summary = consensus_merge(primary, secondary)

    assert summary["single"] == 1
    f = merged.fields[0]
    assert f.consensus == "single"
    assert f.engines == ["glm-ocr"]


@pytest.mark.unit
def test_consensus_multi_value_partial_agreement():
    # 계좌번호 두 건 — 하나는 둘 다 잡고, 하나는 primary 만
    primary = _result(
        _f("bank_account_number", "1002-348-462782"),
        _f("bank_account_number", "462-891-2906"),
    )
    secondary = _result(_f("bank_account_number", "1002-348-462782"))
    merged, summary = consensus_merge(primary, secondary)

    assert summary["agreed"] == 1
    assert summary["single"] == 1
    assert summary["conflict"] == 0

    by_value = {f.value: f for f in merged.fields}
    assert by_value["1002-348-462782"].consensus == "agreed"
    assert by_value["462-891-2906"].consensus == "single"


@pytest.mark.unit
def test_consensus_value_normalization_ignores_whitespace():
    primary = _result(_f("business_registration_number", "220-81-62517"))
    secondary = _result(_f("business_registration_number", "220 - 81 - 62517"))
    merged, summary = consensus_merge(primary, secondary)
    # 정규화 후 같은 값 — agreed
    assert summary["agreed"] == 1


@pytest.mark.unit
def test_consensus_preserves_primary_metadata():
    primary = _result(
        _f("bank_account_number", "1002-348-462782", bbox=(10, 20, 100, 40),
           page_index=1, masked_value="1002-***-462782", notes="매칭 은행: 우리은행")
    )
    secondary = _result(_f("bank_account_number", "1002-348-462782"))
    merged, _ = consensus_merge(primary, secondary)
    f = merged.fields[0]
    assert f.bbox == (10, 20, 100, 40)
    assert f.page_index == 1
    assert f.masked_value == "1002-***-462782"
    assert "매칭 은행: 우리은행" in (f.notes or "")
    assert "교차검증 일치" in (f.notes or "")


@pytest.mark.unit
def test_consensus_summary_total():
    primary = _result(
        _f("a", "1"), _f("b", "2"), _f("c", "3"),
    )
    secondary = _result(
        _f("a", "1"),  # agreed
        _f("b", "X"),  # conflict
        _f("d", "4"),  # secondary only
    )
    merged, summary = consensus_merge(primary, secondary)
    assert summary["agreed"] == 1
    assert summary["conflict"] == 1
    # c (primary only), d (secondary only)
    assert summary["single"] == 2
    assert summary["total"] == 4
