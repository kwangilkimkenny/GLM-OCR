"""신분증/통장/사업자등록증 추출기 + 사업자번호 정상화 테스트."""

import pytest

from app.core.extractors import (
    BankBookExtractor,
    BusinessRegExtractor,
    IdCardExtractor,
    get_extractor,
)
from app.core.extractors.merchant_application import (
    MerchantApplicationExtractor,
    normalize_business_reg,
)


# ---- 사업자등록번호 끝자리 정상화 ----

@pytest.mark.unit
def test_normalize_business_reg_recovers_unique_check_digit():
    # 220-81-6251X 에서 7 만 체크섬 통과 (220-81-62517)
    normalized, note = normalize_business_reg("220-81-6251")
    assert normalized == "220-81-62517"
    assert note and "끝자리 누락 복원" in note


@pytest.mark.unit
def test_normalize_business_reg_no_op_for_complete_value():
    normalized, note = normalize_business_reg("220-81-62517")
    assert normalized == "220-81-62517"
    assert note is None


@pytest.mark.unit
def test_normalize_business_reg_marks_when_no_candidate():
    # 0-0-0 패턴은 0이 valid 검증 통과 → 단일 후보로 복원될 수 있음. 의도된 동작
    normalized, note = normalize_business_reg("000-00-0000")
    assert "끝자리" in (note or "") or normalized != "000-00-0000"


@pytest.mark.unit
def test_merchant_extractor_normalizes_business_reg_in_table():
    md = """
| 사업자등록번호 | 220-81-6251 |
| 상호 | (주)테스트 |
"""
    res = MerchantApplicationExtractor().extract(md)
    biz = next(f for f in res.fields if f.name == "business_registration_number")
    assert biz.value == "220-81-62517"
    assert "끝자리 누락 복원" in (biz.notes or "")
    # 정상화된 케이스는 confidence ≥ 0.85
    assert biz.confidence >= 0.85


# ---- registry ----

@pytest.mark.unit
def test_registry_returns_all_extractors():
    assert get_extractor("merchant_application") is not None
    assert get_extractor("id_card") is not None
    assert get_extractor("bank_book") is not None
    assert get_extractor("business_reg") is not None
    assert get_extractor("freeform") is None


# ---- 신분증 ----

@pytest.mark.unit
def test_id_card_extracts_rrn_and_name():
    text = """
주민등록증
홍길동
성명 홍길동
주민등록번호 831225-1820422
서울특별시 강남구 테헤란로 100
발급일자 2020.05.15
서울특별시장
"""
    res = IdCardExtractor().extract(text)
    by_name = {f.name: f for f in res.fields}
    assert by_name["resident_registration_number"].value == "831225-1820422"
    assert by_name["resident_registration_number"].masked_value == "831225-*******"
    assert by_name["resident_registration_number"].validation_status == "ok"
    assert by_name["issue_date"].value == "2020-05-15"


@pytest.mark.unit
def test_id_card_extracts_driver_license_number():
    text = "운전면허번호 11-22-345678-90 / 종별 1종 보통"
    res = IdCardExtractor().extract(text)
    by_name = {f.name: f for f in res.fields}
    assert by_name["license_number"].value == "11-22-345678-90"


@pytest.mark.unit
def test_id_card_foreign_registration_branch():
    text = "외국인등록번호 950101-5234565"
    res = IdCardExtractor().extract(text)
    names = {f.name for f in res.fields}
    assert "foreign_registration_number" in names
    assert "resident_registration_number" not in names


# ---- 통장 사본 ----

@pytest.mark.unit
def test_bank_book_extracts_account_and_bank_from_prefix():
    text = "예금주 김우리 / 계좌 1002-348-462782"
    res = BankBookExtractor().extract(text)
    by_name = {f.name: f for f in res.fields}
    acc = by_name["account_number"]
    assert acc.value == "1002-348-462782"
    assert "우리은행" in (acc.notes or "")
    assert acc.validation_status == "ok"


@pytest.mark.unit
def test_bank_book_alias_and_prefix_match_boosts_confidence():
    text = "우리은행 통장 1002-348-462782 예금주 홍길동"
    res = BankBookExtractor().extract(text)
    bank = next(f for f in res.fields if f.name == "bank_name")
    assert bank.value == "우리은행"
    # alias + prefix 일치 → confidence ≥ 0.9
    assert bank.confidence >= 0.9
    assert bank.validation_status == "ok"


@pytest.mark.unit
def test_bank_book_account_holder_via_label():
    text = "은행: 신한은행 예금주 박지분 계좌 110-123-456789"
    res = BankBookExtractor().extract(text)
    by_name = {f.name: f for f in res.fields}
    assert by_name["account_holder"].value == "박지분"


# ---- 사업자등록증 ----

@pytest.mark.unit
def test_business_reg_extracts_core_fields():
    text = """
사업자등록증
등록번호 220-81-62517
상호 (주)우리상사
대표자 김우리
사업장 소재지 서울특별시 강남구 테헤란로 100
업태 도소매
종목 카드결제 솔루션
개업연월일 2020년 3월 15일
"""
    res = BusinessRegExtractor().extract(text)
    by_name = {f.name: f for f in res.fields}
    assert by_name["business_registration_number"].value == "220-81-62517"
    assert by_name["business_registration_number"].validation_status == "ok"
    assert by_name["establishment_date"].value == "2020-03-15"


@pytest.mark.unit
def test_business_reg_normalizes_truncated_number_in_table():
    text = """
| 등록번호 | 220-81-6251 |
| 상호 | (주)테스트 |
"""
    res = BusinessRegExtractor().extract(text)
    biz = next(f for f in res.fields if f.name == "business_registration_number")
    # 정규식이 5자리 잡지 못해 표 셀에서만 잡힘 → normalize 작동
    assert biz.value == "220-81-62517"
