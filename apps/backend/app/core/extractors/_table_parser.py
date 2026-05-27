"""마크다운 표 셀 단위 라벨↔값 매칭.

Qwen2.5-VL 같은 instruction-following VLM 은 한국어 양식을 마크다운 표로
구조화해서 내놓는 경우가 많다. 라벨 인접 매칭만으로는 표 헤더 + 본문 행의
2-D 구조를 놓치므로, 표 단위 파서를 별도로 둔다.

지원하는 패턴:
1. 2-열 표: `| 사업자등록번호 | 412-81-…` (라벨 | 값)
2. 헤더 기반 표: 첫 행이 컬럼명, 이후 행이 값 (예: 주민번호 표)
"""

from __future__ import annotations

import re
from typing import Iterable


_LABEL_TO_FIELD: dict[str, str] = {
    # 본질적으로 한 라벨이 여러 필드명 후보를 가질 수 있으니 left-wins
    # ---- 사업자등록증 / 가맹점 신청서 공통 ----
    "사업자등록번호": "business_registration_number",
    "등록번호": "business_registration_number",
    "법인등록번호": "corporate_registration_number",
    "주민등록번호": "resident_registration_number",
    "외국인등록번호": "foreign_registration_number",
    "주민번호": "resident_registration_number",
    "상호": "merchant_name",
    "상호(법인명)": "merchant_name",
    "법인명": "merchant_name",
    "사업자명": "merchant_name",
    "가맹점명": "merchant_name",
    "대표자": "representative_name",
    "대표이사": "representative_name",
    "대표자명": "representative_name",
    "성명": "name",
    "업태": "business_category",
    "종목": "business_category",
    "업종": "business_category",
    "사업장 주소": "merchant_address",
    "사업장주소": "merchant_address",
    "사업장 소재지": "merchant_address",
    "(기타)주소": "merchant_address",
    "주소": "merchant_address",
    "본적": "address",
    "연락처": "phone_number",
    "연락처(휴대폰)": "phone_number",
    "휴대폰": "phone_number",
    "전화": "phone_number",
    "E-Mail": "email",
    "이메일": "email",
    # ---- 계좌 ----
    "감제처좌": "bank_account_number",
    "결제계좌": "bank_account_number",
    "계좌번호": "bank_account_number",
    "계좌": "bank_account_number",
    "은행": "bank_name",
    "은행명": "bank_name",
    "예금주": "account_holder",
    "지점": "branch",
    "개설지점": "branch",
    # ---- 신분증 ----
    "발급일": "issue_date",
    "발급일자": "issue_date",
    "발급기관": "issuer",
    "면허번호": "license_number",
    "운전면허번호": "license_number",
    "면허종류": "license_class",
    "종별": "license_class",
    "유효기간": "expiry_date",
    "국적": "nationality",
    "체류자격": "residence_status",
    "체류기간": "residence_period",
    # ---- 가맹점/주주 ----
    "실소유자": "beneficial_owner",
    "지분율": "ownership_percentage",
    "지분": "ownership_percentage",
    # ---- 사업자등록증 추가 ----
    "개업연월일": "establishment_date",
    "개업일자": "establishment_date",
    "개업일": "establishment_date",
    "설립연월일": "establishment_date",
}


_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$")


def _clean_cell(cell: str) -> str:
    return cell.strip().strip("□☐☑■").strip()


def _split_row(line: str) -> list[str]:
    m = _TABLE_ROW_RE.match(line)
    if not m:
        return []
    return [_clean_cell(c) for c in m.group(1).split("|")]


def _is_separator_row(cells: Iterable[str]) -> bool:
    """`| --- | --- |` 형태 구분선."""
    for c in cells:
        if not c:
            continue
        if not re.fullmatch(r":?-+:?", c):
            return False
    return True


def parse_table_fields(markdown: str) -> dict[str, str]:
    """마크다운 텍스트에서 라벨↔값 페어를 추출. 이미 잡힌 값이 있으면 첫 값 우선.

    Returns:
        {field_name: value}
    """
    found: dict[str, str] = {}
    if not markdown:
        return found

    for raw_line in markdown.splitlines():
        cells = _split_row(raw_line)
        if not cells or _is_separator_row(cells):
            continue
        # 패턴: | 라벨 | 값 | (옵션 추가 셀)
        if len(cells) < 2:
            continue
        label, value = cells[0], cells[1]
        if not label or not value:
            continue
        field_name = _LABEL_TO_FIELD.get(label)
        if not field_name:
            # 라벨에 공백/괄호 노이즈가 섞인 경우 정규화 후 재시도
            normalized = re.sub(r"\s+", "", label)
            field_name = _LABEL_TO_FIELD.get(normalized)
        if not field_name:
            continue
        if field_name in found:
            continue
        # 너무 짧거나 placeholder 값은 폐기
        if value in {"", "-", "N/A", "(주)"} or len(value) < 2:
            continue
        found[field_name] = value

    return found
