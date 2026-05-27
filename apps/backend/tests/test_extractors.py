"""우리카드 가맹점 가입신청서 추출기 Day 1 테스트."""

import pytest

from app.core.extractors import get_extractor
from app.core.extractors.merchant_application import (
    MerchantApplicationExtractor,
    _validate_business_reg,
    _validate_rrn,
    _is_foreign_rrn,
    _mask_rrn,
)


@pytest.mark.unit
def test_validate_business_reg_known_valid():
    # 공개된 유효 사업자번호 (체크섬 검증용)
    assert _validate_business_reg("2208162517") is True  # 220-81-62517
    assert _validate_business_reg("1078187194") is True  # 107-81-87194


@pytest.mark.unit
def test_validate_business_reg_known_invalid():
    assert _validate_business_reg("1234567890") is False
    assert _validate_business_reg("123") is False  # too short


@pytest.mark.unit
def test_extract_business_registration_number():
    text = "사업자등록번호 220-81-62517 대표자 홍길동"
    res = MerchantApplicationExtractor().extract(text)
    by_name = {f.name: f for f in res.fields}
    assert "business_registration_number" in by_name
    f = by_name["business_registration_number"]
    assert f.value == "220-81-62517"
    assert f.validation_status == "ok"


@pytest.mark.unit
def test_extract_invalid_business_registration_number_marks_invalid():
    text = "사업자등록번호 123-45-67890"
    res = MerchantApplicationExtractor().extract(text)
    f = next(x for x in res.fields if x.name == "business_registration_number")
    assert f.validation_status == "invalid"
    assert f.confidence < 0.9


@pytest.mark.unit
def test_extract_phone_numbers_dedup():
    text = "전화 02-1234-5678, 모바일 010-9876-5432 (재기재: 010-9876-5432)"
    res = MerchantApplicationExtractor().extract(text)
    phones = [f.value for f in res.fields if f.name == "phone_number"]
    assert "02-1234-5678" in phones
    assert phones.count("010-9876-5432") == 1


@pytest.mark.unit
def test_extract_bank_account_masking():
    # 사업자번호(3-2-5)와 형식 다른 계좌만 잡혀야 함
    text = "예금주 홍길동 계좌 1002-348-462782"
    res = MerchantApplicationExtractor().extract(text)
    accounts = [f for f in res.fields if f.name == "bank_account_number"]
    assert len(accounts) == 1
    assert accounts[0].value == "1002-348-462782"
    assert accounts[0].masked_value == "1002-***-462782"


@pytest.mark.unit
def test_extract_does_not_treat_business_reg_as_account():
    text = "사업자등록번호 220-81-62517"
    res = MerchantApplicationExtractor().extract(text)
    accounts = [f for f in res.fields if f.name == "bank_account_number"]
    assert accounts == []


@pytest.mark.unit
def test_registry_lookup():
    assert get_extractor("merchant_application") is not None
    assert get_extractor("freeform") is None
    assert get_extractor(None) is None
    assert get_extractor("unknown_type") is None


# ---- 「붙임3」 추가 항목 테스트 ----

@pytest.mark.unit
def test_rrn_checksum_known_valid():
    # 알고리즘 검증용 합성 RRN (유효 / 무효 페어)
    assert _validate_rrn("8312251820422") is True
    assert _validate_rrn("8312251820423") is False  # 체크 자리만 1 틀림
    assert _validate_rrn("1234") is False  # too short


@pytest.mark.unit
def test_foreign_rrn_detection():
    # 외국인등록번호: 7번째 자리 5/6/7/8
    assert _is_foreign_rrn("9501015234565") is True  # 7번째=5
    assert _is_foreign_rrn("9501011234567") is False


@pytest.mark.unit
def test_mask_rrn():
    assert _mask_rrn("831225-1820422") == "831225-*******"
    assert _mask_rrn("8312251820422") == "831225-*******"


@pytest.mark.unit
def test_extract_resident_registration_number():
    text = "성명 홍길동 주민등록번호 831225-1820422"
    res = MerchantApplicationExtractor().extract(text)
    by_name = {f.name: f for f in res.fields}
    assert "resident_registration_number" in by_name
    f = by_name["resident_registration_number"]
    assert f.value == "831225-1820422"
    assert f.masked_value == "831225-*******"
    assert f.validation_status == "ok"


@pytest.mark.unit
def test_extract_foreign_registration_number():
    # 7번째 자리 5 → 외국인
    text = "외국인등록번호 950101-5234565"
    res = MerchantApplicationExtractor().extract(text)
    names = [f.name for f in res.fields]
    assert "foreign_registration_number" in names
    assert "resident_registration_number" not in names


@pytest.mark.unit
def test_extract_corporate_registration_number_by_label():
    # RRN 형식이지만 라벨이 "법인등록번호"면 법인등록번호로 분류
    text = "법인등록번호 110111-1234567 대표이사 김우리"
    res = MerchantApplicationExtractor().extract(text)
    names = [f.name for f in res.fields]
    assert "corporate_registration_number" in names
    # RRN으로는 잡히지 않음
    assert "resident_registration_number" not in names


@pytest.mark.unit
def test_extract_labeled_fields():
    text = (
        "상호 우리상사주식회사\n"
        "대표자 김우리\n"
        "업태 도소매\n"
        "종목 카드결제 솔루션\n"
        "실소유자 박지분\n"
    )
    res = MerchantApplicationExtractor().extract(text)
    by_name = {f.name: f.value for f in res.fields}
    assert by_name.get("merchant_name") == "우리상사주식회사"
    assert by_name.get("representative_name") == "김우리"
    assert by_name.get("business_category") in {"도소매", "카드결제 솔루션"}
    assert by_name.get("beneficial_owner") == "박지분"


@pytest.mark.unit
def test_extract_ownership_percentage():
    text = "주주: 박지분 지분율 51% / 김우리 지분율 49%"
    res = MerchantApplicationExtractor().extract(text)
    shares = [f.value for f in res.fields if f.name == "ownership_percentage"]
    assert "51%" in shares
    assert "49%" in shares


@pytest.mark.unit
def test_ownership_percentage_requires_label():
    # "지분" 없는 % 는 잡히면 안 됨 (예: 부가세 10%)
    text = "부가세 10% 별도"
    res = MerchantApplicationExtractor().extract(text)
    shares = [f for f in res.fields if f.name == "ownership_percentage"]
    assert shares == []


@pytest.mark.unit
def test_phone_masking():
    text = "연락처 02-1234-5678"
    res = MerchantApplicationExtractor().extract(text)
    phone = next(f for f in res.fields if f.name == "phone_number")
    assert phone.masked_value == "02-****-5678"


# ---- 트랙 B: source_match → bbox 역매칭 ----

@pytest.mark.unit
def test_bbox_attached_when_blocks_provided():
    raw_text = "사업자등록번호 220-81-62517 연락처 02-1234-5678"
    raw_blocks = [
        {"block_content": "사업자등록번호 220-81-62517", "bbox": [10, 20, 300, 50], "block_id": 0, "page_index": 0},
        {"block_content": "연락처 02-1234-5678", "bbox": [10, 60, 300, 90], "block_id": 1, "page_index": 0},
    ]
    res = MerchantApplicationExtractor().extract(raw_text, raw_blocks=raw_blocks)
    by_name = {f.name: f for f in res.fields}
    assert by_name["business_registration_number"].bbox == (10, 20, 300, 50)
    assert by_name["business_registration_number"].page_index == 0
    assert by_name["phone_number"].bbox == (10, 60, 300, 90)


@pytest.mark.unit
def test_bbox_matches_normalized_when_block_has_extra_spaces():
    raw_text = "사업자등록번호 220-81-62517"
    raw_blocks = [
        # OCR 결과가 자간이 들어간 경우
        {"block_content": "사업자등록번호 220 - 81 - 62517", "bbox": [0, 0, 100, 20], "block_id": 0, "page_index": 1},
    ]
    res = MerchantApplicationExtractor().extract(raw_text, raw_blocks=raw_blocks)
    by_name = {f.name: f for f in res.fields}
    assert by_name["business_registration_number"].bbox == (0, 0, 100, 20)
    assert by_name["business_registration_number"].page_index == 1


@pytest.mark.unit
def test_bbox_none_when_no_blocks():
    res = MerchantApplicationExtractor().extract("사업자등록번호 220-81-62517")
    f = next(x for x in res.fields if x.name == "business_registration_number")
    assert f.bbox is None
    assert f.page_index is None


# ---- 트랙 C: 은행/주소 사전 매칭 ----

@pytest.mark.unit
def test_bank_account_prefix_marks_known_bank():
    text = "계좌 1002-348-462782"
    res = MerchantApplicationExtractor().extract(text)
    f = next(x for x in res.fields if x.name == "bank_account_number")
    assert f.validation_status == "ok"
    assert f.notes and "우리은행" in f.notes


@pytest.mark.unit
def test_bank_account_unknown_prefix_stays_unverified():
    text = "계좌 7777-12-345678"
    res = MerchantApplicationExtractor().extract(text)
    f = next(x for x in res.fields if x.name == "bank_account_number")
    assert f.validation_status == "unverified"
    assert f.notes is None


@pytest.mark.unit
def test_address_exact_match_marks_region():
    text = "사업장 주소 서울특별시 광진구 광진서로 239"
    res = MerchantApplicationExtractor().extract(text)
    addr = next(x for x in res.fields if x.name == "merchant_address")
    assert addr.notes is not None
    assert "서울특별시" in addr.notes
    assert "광진구" in addr.notes


@pytest.mark.unit
def test_address_fuzzy_correction_for_one_char_typo():
    # 1글자 OCR 오인식: 광진구 → 광진귀 (자모 1 차이)
    text = "사업장 주소 서울 광진귀 광진서로 239"
    res = MerchantApplicationExtractor().extract(text)
    addr = next(x for x in res.fields if x.name == "merchant_address")
    assert addr.notes is not None
    assert "광진귀 → 광진구" in addr.notes


@pytest.mark.unit
def test_bank_name_aliased_from_text():
    text = "우리은행 1002-348-462782"
    res = MerchantApplicationExtractor().extract(text)
    bank = next((x for x in res.fields if x.name == "bank_name"), None)
    assert bank is not None
    assert bank.value == "우리은행"


# ---- 마크다운 표 셀 추출기 ----

@pytest.mark.unit
def test_table_parser_extracts_label_value_pairs():
    md = """
이 문서는 다음과 같습니다.

| 사항 | 내용 |
| --- | --- |
| 사업자등록번호 | 412-81-29360 |
| 상호 | (주)하사테크 |
| 대표자 | 차정수 |
| 업태 | 전기, 전선 |
| 연락처(휴대폰) | 010-1167-7577 |
| (기타)주소 | 경기도 안양시 만안구 한양대학길 101-60호 |
| 감제처좌 | 우리은행 1002-348-462782 |
"""
    res = MerchantApplicationExtractor().extract(md)
    by_name = {f.name: f for f in res.fields}
    assert by_name["business_registration_number"].value == "412-81-29360"
    assert by_name["merchant_name"].value == "(주)하사테크"
    assert by_name["representative_name"].value == "차정수"
    assert by_name["business_category"].value == "전기, 전선"
    # 표 셀 매칭이 라벨 인접보다 우선 (notes 로 식별)
    note_keys = {f.name for f in res.fields if f.notes == "표 셀 라벨 매칭"}
    assert "merchant_name" in note_keys
    assert "representative_name" in note_keys


@pytest.mark.unit
def test_table_parser_ignores_separator_rows():
    md = """
| 라벨 | 값 |
| --- | --- |
| 대표자 | 김우리 |
"""
    res = MerchantApplicationExtractor().extract(md)
    rep = next((f for f in res.fields if f.name == "representative_name"), None)
    assert rep is not None
    assert rep.value == "김우리"


@pytest.mark.unit
def test_table_parser_skips_placeholder_values():
    md = """
| 대표자 | - |
| 상호 | (주) |
"""
    res = MerchantApplicationExtractor().extract(md)
    names = {f.name for f in res.fields}
    assert "representative_name" not in names
    assert "merchant_name" not in names


# ---- 정규식 disjoint 매칭 ----

@pytest.mark.unit
def test_phone_not_double_matched_as_account():
    # 휴대폰 010-1167-7577 이 계좌번호로 잡히지 않아야 함
    text = "연락처(휴대폰) 010-1167-7577 결제계좌 1002-348-462782"
    res = MerchantApplicationExtractor().extract(text)
    phones = [f.value for f in res.fields if f.name == "phone_number"]
    accounts = [f.value for f in res.fields if f.name == "bank_account_number"]
    assert phones == ["010-1167-7577"]
    assert "010-1167-7577" not in accounts
    assert "1002-348-462782" in accounts


@pytest.mark.unit
def test_business_reg_not_double_matched_as_account():
    text = "사업자등록번호 220-81-62517 / 계좌 1002-348-462782"
    res = MerchantApplicationExtractor().extract(text)
    biz = [f.value for f in res.fields if f.name == "business_registration_number"]
    accounts = [f.value for f in res.fields if f.name == "bank_account_number"]
    assert biz == ["220-81-62517"]
    # 사업자번호가 계좌로 중복 매치되면 안 됨
    assert "220-81-62517" not in accounts


@pytest.mark.unit
def test_rrn_not_double_matched_as_account():
    text = "주민등록번호 831225-1820422"
    res = MerchantApplicationExtractor().extract(text)
    rrns = [f.value for f in res.fields if f.name == "resident_registration_number"]
    accounts = [f.value for f in res.fields if f.name == "bank_account_number"]
    assert rrns == ["831225-1820422"]
    assert accounts == []


@pytest.mark.unit
def test_table_and_regex_same_value_merges_with_higher_confidence():
    text = """
사업자등록번호 220-81-62517

| 사항 | 내용 |
| --- | --- |
| 사업자등록번호 | 220-81-62517 |
"""
    res = MerchantApplicationExtractor().extract(text)
    biz = [f for f in res.fields if f.name == "business_registration_number"]
    assert len(biz) == 1
    f = biz[0]
    # 정규식 valid → 0.95, 그리고 표 셀 일치로 confidence ≥ 0.9 유지
    assert f.confidence >= 0.9
    assert "정규식+표 셀 일치" in (f.notes or "")


@pytest.mark.unit
def test_multiple_phones_and_accounts_disjoint():
    text = """
전화 02-1234-5678
모바일 010-9876-5432
결제계좌 1002-348-462782
"""
    res = MerchantApplicationExtractor().extract(text)
    phones = sorted(f.value for f in res.fields if f.name == "phone_number")
    accounts = sorted(f.value for f in res.fields if f.name == "bank_account_number")
    assert phones == ["010-9876-5432", "02-1234-5678"]
    assert accounts == ["1002-348-462782"]
    # 전화번호가 계좌로 중복 매치되면 안 됨
    assert "010-9876-5432" not in accounts
    assert "02-1234-5678" not in accounts
