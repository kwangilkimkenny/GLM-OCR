"""우리카드 가맹점 가입신청서 추출기.

「붙임3. AI_OCR POC관련 문서별 추출 항목.xlsx」의 ② 가맹점가입신청서 항목 기준.

Phase 2 변경:
- extract() 가 raw_blocks 를 받아 source_match → bbox 역매칭 수행 (_matching.attach_bbox)
- bank / region validators 로 사전 매칭 검증 추가 (계좌→은행 추정, 주소→행정구역 보정)
"""

from __future__ import annotations

import re
from typing import NamedTuple, Optional

from app.core.extractors._matching import attach_bbox
from app.core.extractors._table_parser import parse_table_fields
from app.core.extractors.base import (
    ExtractedField,
    ExtractionResult,
    FieldExtractor,
    LayoutBlock,
)
from app.core.validators import (
    lookup_bank_by_account_prefix,
    normalize_bank_name,
    suggest_region,
)


# ---------- 정규식 disjoint 매칭 유틸 ----------

class _Span(NamedTuple):
    start: int
    end: int


def _overlaps(start: int, end: int, used: list[_Span]) -> bool:
    """`[start, end)` 가 이미 사용된 span 중 어느 하나와도 겹치는지."""
    return any(start < u.end and end > u.start for u in used)


def _claim(start: int, end: int, used: list[_Span]) -> None:
    used.append(_Span(start, end))


# ---------- 정규식 ----------

_BUSINESS_REG_RE = re.compile(r"\b(\d{3})\s*[-\s]\s*(\d{2})\s*[-\s]\s*(\d{5})\b")
_RRN_RE = re.compile(r"\b(\d{6})\s*[-\s]\s*(\d{7})\b")
_BANK_ACCOUNT_RE = re.compile(r"\b(\d{3,6})\s*-\s*(\d{2,6})\s*-\s*(\d{2,7})\b")
_PHONE_RE = re.compile(
    r"\b(01[016789]|0\d{1,2})\s*[-\s]\s*(\d{3,4})\s*[-\s]\s*(\d{4})\b"
)
_SHARE_PCT_RE = re.compile(r"(\d{1,3}(?:\.\d{1,2})?)\s*%")


# ---------- 체크섬 ----------

def _validate_business_reg(digits: str) -> bool:
    if len(digits) != 10 or not digits.isdigit():
        return False
    weights = (1, 3, 7, 1, 3, 7, 1, 3, 5)
    total = sum(int(d) * w for d, w in zip(digits[:9], weights))
    total += (int(digits[8]) * 5) // 10
    check = (10 - (total % 10)) % 10
    return check == int(digits[9])


def normalize_business_reg(value: str) -> tuple[str, Optional[str]]:
    """OCR 환각으로 사업자번호 끝자리가 누락된 케이스(3-2-4) 를 체크섬으로 복원.

    Returns:
        (normalized_value, note) — 정상화 실패 시 (value, "끝자리 누락 가능")
    """
    if not value:
        return value, None
    m = re.fullmatch(r"\s*(\d{3})\s*-\s*(\d{2})\s*-\s*(\d{4})\s*", value)
    if not m:
        return value, None
    a, b, c = m.groups()
    candidates = [d for d in range(10) if _validate_business_reg(f"{a}{b}{c}{d}")]
    if len(candidates) == 1:
        return f"{a}-{b}-{c}{candidates[0]}", f"끝자리 누락 복원 → {candidates[0]} (체크섬 일치)"
    if candidates:
        return value, f"끝자리 후보 {len(candidates)}개: {candidates}"
    return value, "끝자리 누락 가능 (체크섬 미확정)"


def _validate_rrn(digits: str) -> bool:
    if len(digits) != 13 or not digits.isdigit():
        return False
    weights = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)
    total = sum(int(d) * w for d, w in zip(digits[:12], weights))
    check = (11 - (total % 11)) % 10
    return check == int(digits[12])


def _is_foreign_rrn(digits: str) -> bool:
    return len(digits) >= 7 and digits[6] in "5678"


# ---------- 마스킹 ----------

def _mask_account(account: str) -> str:
    parts = re.split(r"\s*-\s*", account)
    if len(parts) < 2:
        return account
    masked = parts[:1] + ["*" * len(p) for p in parts[1:-1]] + parts[-1:]
    return "-".join(masked)


def _mask_rrn(rrn: str) -> str:
    digits = re.sub(r"[^0-9]", "", rrn)
    if len(digits) != 13:
        return rrn
    return f"{digits[:6]}-{'*' * 7}"


def _mask_phone(phone: str) -> str:
    parts = re.split(r"\s*-\s*", phone)
    if len(parts) != 3:
        return phone
    return f"{parts[0]}-{'*' * len(parts[1])}-{parts[2]}"


# ---------- 라벨 인접 토큰 ----------

# (field_name, 한글 라벨 후보, 최대 길이, 신뢰도)
_LABEL_FIELDS: list[tuple[str, tuple[str, ...], int, float]] = [
    ("merchant_name", ("상호", "사업자명", "법인명", "가맹점명"), 40, 0.65),
    ("representative_name", ("대표자", "대표이사", "대표자명"), 20, 0.65),
    ("business_category", ("업태", "종목", "업종"), 30, 0.6),
    ("beneficial_owner", ("실소유자", "실 소유자"), 20, 0.6),
    ("corporate_registration_number", ("법인등록번호", "법인 등록번호"), 25, 0.7),
    ("merchant_address", ("사업장 주소", "사업장주소", "사업장 소재지", "주소"), 80, 0.55),
]


_PLACEHOLDER_VALUES = {"", "-", "—", "N/A", "(주)", "□", "☐"}


# 라벨 인접 값에서 자르기용 다음-라벨 키워드 (공백 후 등장하면 stop)
_NEXT_LABEL_KEYWORDS = (
    "계좌", "은행", "지점", "전화", "연락처", "휴대폰", "주소",
    "이메일", "E-Mail", "업태", "종목", "업종", "성명", "대표자",
    "발급", "면허", "종별", "유효", "국적", "체류", "상호", "법인",
    "사업자", "사업장", "예금주", "지분",
)
_NEXT_LABEL_RE = re.compile(
    r"\s+(?:" + "|".join(re.escape(k) for k in _NEXT_LABEL_KEYWORDS) + r")(?:\s|[::])"
)


def _label_value(text: str, labels: tuple[str, ...], max_chars: int) -> Optional[str]:
    for label in labels:
        idx = text.find(label)
        if idx == -1:
            continue
        after = text[idx + len(label) : idx + len(label) + max_chars]
        after = after.lstrip(" :：\t-")
        # 1) 줄바꿈 또는 "다음 한글 라벨 + 콜론" 패턴
        cut = re.split(r"[\n\r]|(?:[가-힣]{2,4}\s*[::])", after, maxsplit=1)
        candidate = cut[0]
        # 2) 콜론 없는 다음 라벨 키워드(공백+계좌/은행 등)에서 자르기
        nl = _NEXT_LABEL_RE.search(candidate)
        if nl:
            candidate = candidate[: nl.start()]
        candidate = candidate.strip(" \t,.|/")
        if candidate and candidate not in _PLACEHOLDER_VALUES and len(candidate) >= 2:
            return candidate
    return None


# ---------- 사전 매칭 검증 ----------

def _apply_validators(fields: list[ExtractedField]) -> None:
    """각 ExtractedField 에 사전 매칭 결과를 in-place 반영."""
    for f in fields:
        if f.name == "bank_account_number":
            bank = lookup_bank_by_account_prefix(f.value)
            if bank:
                f.notes = f"매칭 은행: {bank}"
                if f.validation_status == "unverified":
                    f.validation_status = "ok"
                    f.confidence = max(f.confidence, 0.85)
        elif f.name == "merchant_address":
            province, district, note = suggest_region(f.value)
            parts = []
            if province:
                parts.append(f"시·도={province}")
            if district:
                parts.append(f"구={district}")
            if parts:
                f.notes = ", ".join(parts) + (f" ({note})" if note else "")
                # 보정이 있었다면 confidence 살짝 증가, 그래도 unverified 유지
                if note and f.confidence < 0.7:
                    f.confidence = 0.7


# ---------- 메인 추출기 ----------

class MerchantApplicationExtractor(FieldExtractor):
    """가맹점 가입신청서 — 「붙임3」 명세 항목 + 주소."""

    document_type = "merchant_application"

    def extract(
        self,
        raw_text: str,
        raw_blocks: Optional[list[LayoutBlock]] = None,
    ) -> ExtractionResult:
        fields: list[ExtractedField] = []

        # 정규식 disjoint: 한 번 매치된 character span 은 후속 정규식이 못 본다.
        # 우선순위: 가장 specific → generic
        #   1) 사업자등록번호 (3-2-5)
        #   2) 전화번호 (0xx-xxx-xxxx, 모바일 prefix specific)
        #   3) 주민/외국인/법인등록번호 (6-7)
        #   4) 계좌번호 (3~6-2~6-2~7, 가장 generic — 마지막)
        used_spans: list[_Span] = []

        # 1) 사업자등록번호
        for m in _BUSINESS_REG_RE.finditer(raw_text):
            if _overlaps(m.start(), m.end(), used_spans):
                continue
            _claim(m.start(), m.end(), used_spans)
            joined = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            digits = m.group(1) + m.group(2) + m.group(3)
            ok = _validate_business_reg(digits)
            fields.append(
                ExtractedField(
                    name="business_registration_number",
                    value=joined,
                    confidence=0.95 if ok else 0.55,
                    validation_status="ok" if ok else "invalid",
                    source_match=m.group(0),
                )
            )

        # 2) 전화번호 (휴대폰/지역번호 — account 정규식보다 우선)
        seen_phones: set[str] = set()
        for m in _PHONE_RE.finditer(raw_text):
            if _overlaps(m.start(), m.end(), used_spans):
                continue
            _claim(m.start(), m.end(), used_spans)
            normalized = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            if normalized in seen_phones:
                continue
            seen_phones.add(normalized)
            fields.append(
                ExtractedField(
                    name="phone_number",
                    value=normalized,
                    confidence=0.85,
                    validation_status="ok",
                    masked_value=_mask_phone(normalized),
                    source_match=m.group(0),
                )
            )

        # 3) 주민/외국인/법인등록번호 (6-7)
        seen_rrns: set[str] = set()
        for m in _RRN_RE.finditer(raw_text):
            if _overlaps(m.start(), m.end(), used_spans):
                continue
            front, back = m.group(1), m.group(2)
            digits = front + back
            if digits in seen_rrns:
                continue
            seen_rrns.add(digits)
            _claim(m.start(), m.end(), used_spans)
            window = raw_text[max(0, m.start() - 30) : m.end() + 5]
            is_corp = "법인등록번호" in window or "법인 등록번호" in window
            if is_corp:
                fields.append(
                    ExtractedField(
                        name="corporate_registration_number",
                        value=f"{front}-{back}",
                        confidence=0.8,
                        validation_status="unverified",
                        source_match=m.group(0),
                    )
                )
                continue
            ok = _validate_rrn(digits)
            foreign = _is_foreign_rrn(digits)
            name = "foreign_registration_number" if foreign else "resident_registration_number"
            fields.append(
                ExtractedField(
                    name=name,
                    value=f"{front}-{back}",
                    confidence=0.95 if ok else 0.5,
                    validation_status="ok" if ok else "invalid",
                    masked_value=_mask_rrn(f"{front}-{back}"),
                    source_match=m.group(0),
                )
            )

        # 4) 계좌번호 (가장 generic — 마지막)
        seen_accounts: set[str] = set()
        for m in _BANK_ACCOUNT_RE.finditer(raw_text):
            if _overlaps(m.start(), m.end(), used_spans):
                continue
            raw = m.group(0)
            normalized = re.sub(r"\s+", "", raw)
            if normalized in seen_accounts:
                continue
            seen_accounts.add(normalized)
            _claim(m.start(), m.end(), used_spans)
            fields.append(
                ExtractedField(
                    name="bank_account_number",
                    value=normalized,
                    confidence=0.7,
                    validation_status="unverified",
                    masked_value=_mask_account(normalized),
                    source_match=raw,
                )
            )

        # 5a. 마크다운 표 셀 라벨↔값 (Qwen2.5-VL 등 VLM 출력 강함)
        existing_names = {f.name for f in fields}
        existing_pairs = {(f.name, f.value) for f in fields}
        table_pairs = parse_table_fields(raw_text)

        # 사업자번호 끝자리 누락 정상화 (예: 412-81-2936 → 412-81-29360)
        if "business_registration_number" in table_pairs:
            original = table_pairs["business_registration_number"]
            normalized, note = normalize_business_reg(original)
            if normalized != original:
                table_pairs["business_registration_number"] = normalized
                table_pairs.setdefault("__notes__", {})["business_registration_number"] = note

        normalize_notes = table_pairs.pop("__notes__", {})

        for field_name, value in table_pairs.items():
            # (name, value) 가 정규식으로 이미 잡혔으면 → 합산: 신뢰도 ↑, notes 추가
            if (field_name, value) in existing_pairs:
                for f in fields:
                    if f.name == field_name and f.value == value:
                        f.confidence = max(f.confidence, 0.9)
                        existing = f.notes or ""
                        if "표 셀" not in existing:
                            f.notes = (existing + "; " if existing else "") + "정규식+표 셀 일치"
                continue
            # 이미 같은 이름의 다른 값이 있는 경우 — 표 셀이 더 신뢰
            if field_name in existing_names:
                continue
            # 정규식이 같은 value 를 다른 name (예: 사업자번호 형식이 아닌 계좌 패턴)으로 잡았다면,
            # 표 셀의 라벨 정보가 더 권위 있으므로 그 정규식 결과를 폐기.
            ghosts = [f for f in fields if f.value == value and f.name != field_name]
            for ghost in ghosts:
                fields.remove(ghost)
                existing_pairs.discard((ghost.name, ghost.value))
                # ghost name 이 다른 fields 에도 있으면 existing_names 는 유지
                if not any(g.name == ghost.name for g in fields):
                    existing_names.discard(ghost.name)
            base_note = "표 셀 라벨 매칭"
            if field_name in normalize_notes:
                base_note += "; " + normalize_notes[field_name]
            fields.append(
                ExtractedField(
                    name=field_name,
                    value=value,
                    confidence=0.85 if field_name in normalize_notes else 0.75,
                    validation_status="unverified",
                    source_match=value,
                    notes=base_note,
                )
            )
            existing_names.add(field_name)
            existing_pairs.add((field_name, value))

        # 5b. 라벨 인접 항목 (표에 없는 케이스 보완)
        seen_corp_reg = "corporate_registration_number" in existing_names
        for field_name, labels, max_chars, conf in _LABEL_FIELDS:
            if field_name in existing_names:
                continue
            if field_name == "corporate_registration_number" and seen_corp_reg:
                continue
            value = _label_value(raw_text, labels, max_chars)
            if value:
                fields.append(
                    ExtractedField(
                        name=field_name,
                        value=value,
                        confidence=conf,
                        validation_status="unverified",
                        source_match=value,
                    )
                )
                existing_names.add(field_name)

        # 6. 은행명 (텍스트에서 직접 매칭)
        bank_from_text = normalize_bank_name(raw_text[:500])
        if bank_from_text and not any(f.name == "bank_name" for f in fields):
            fields.append(
                ExtractedField(
                    name="bank_name",
                    value=bank_from_text,
                    confidence=0.6,
                    validation_status="unverified",
                    source_match=bank_from_text,
                    notes="사전 alias 매칭",
                )
            )

        # 7. 지분율 ("지분" 라벨 인근만)
        seen_shares: set[str] = set()
        for m in _SHARE_PCT_RE.finditer(raw_text):
            window = raw_text[max(0, m.start() - 15) : m.end()]
            if "지분" not in window:
                continue
            value = f"{m.group(1)}%"
            if value in seen_shares:
                continue
            seen_shares.add(value)
            fields.append(
                ExtractedField(
                    name="ownership_percentage",
                    value=value,
                    confidence=0.7,
                    validation_status="unverified",
                    source_match=m.group(0),
                )
            )

        # 8. 같은 (name, value) 중복 제거 — 동일 사업자번호가 본문 + 표 셀에 모두 나타나면
        #    한 entry 로 합쳐 신뢰도 max, notes 병합.
        seen_pairs: dict[tuple[str, str], ExtractedField] = {}
        deduped: list[ExtractedField] = []
        for f in fields:
            key = (f.name, f.value)
            existing = seen_pairs.get(key)
            if existing is None:
                seen_pairs[key] = f
                deduped.append(f)
                continue
            existing.confidence = max(existing.confidence, f.confidence)
            if f.notes and f.notes not in (existing.notes or ""):
                existing.notes = (
                    (existing.notes + "; ") if existing.notes else ""
                ) + f.notes
        fields = deduped

        # 9. 사전 매칭 검증 (계좌 → 은행 추정, 주소 → 행정구역 보정)
        _apply_validators(fields)

        # 10. bbox 역매칭
        attach_bbox(fields, raw_blocks)

        return ExtractionResult(document_type=self.document_type, fields=fields)
