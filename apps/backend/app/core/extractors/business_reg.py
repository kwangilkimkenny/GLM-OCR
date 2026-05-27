"""사업자등록증 추출기."""

from __future__ import annotations

import re
from typing import Optional

from app.core.extractors._matching import attach_bbox
from app.core.extractors._table_parser import parse_table_fields
from app.core.extractors.base import (
    ExtractedField,
    ExtractionResult,
    FieldExtractor,
    LayoutBlock,
)
from app.core.extractors.merchant_application import (
    _BUSINESS_REG_RE,
    _RRN_RE,
    _Span,
    _claim,
    _label_value,
    _overlaps,
    _validate_business_reg,
    normalize_business_reg,
)
from app.core.validators import suggest_region


_ESTABLISHMENT_RE = re.compile(
    r"(\d{4})\s*[년./\-]\s*(\d{1,2})\s*[월./\-]\s*(\d{1,2})\s*일?"
)

_LABEL_FIELDS = [
    ("company_name", ("상호", "상호(법인명)", "법인명"), 40, 0.7),
    ("representative_name", ("대표자", "대표이사", "성명"), 20, 0.7),
    ("business_address", ("사업장 소재지", "사업장주소", "사업장 주소"), 80, 0.65),
    ("business_category", ("업태", "종목", "업종"), 30, 0.65),
]


class BusinessRegExtractor(FieldExtractor):
    document_type = "business_reg"

    def extract(
        self,
        raw_text: str,
        raw_blocks: Optional[list[LayoutBlock]] = None,
    ) -> ExtractionResult:
        fields: list[ExtractedField] = []
        used_spans: list[_Span] = []

        # 1) 사업자등록번호 (3-2-5, 체크섬)
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

        # 2) 법인등록번호 (6-7) — "법인" 라벨 인근만
        for m in _RRN_RE.finditer(raw_text):
            if _overlaps(m.start(), m.end(), used_spans):
                continue
            window = raw_text[max(0, m.start() - 30) : m.end() + 5]
            if "법인" not in window:
                continue
            _claim(m.start(), m.end(), used_spans)
            fields.append(
                ExtractedField(
                    name="corporate_registration_number",
                    value=f"{m.group(1)}-{m.group(2)}",
                    confidence=0.8,
                    validation_status="unverified",
                    source_match=m.group(0),
                )
            )

        # 3) 개업연월일 — "개업" 라벨 인근만
        for m in _ESTABLISHMENT_RE.finditer(raw_text):
            if _overlaps(m.start(), m.end(), used_spans):
                continue
            window = raw_text[max(0, m.start() - 20) : m.end() + 5]
            if not any(kw in window for kw in ("개업", "설립")):
                continue
            _claim(m.start(), m.end(), used_spans)
            normalized = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            fields.append(
                ExtractedField(
                    name="establishment_date",
                    value=normalized,
                    confidence=0.8,
                    validation_status="unverified",
                    source_match=m.group(0),
                )
            )
            break

        # 4) 표 셀 매칭 + 사업자번호 정상화
        existing_names = {f.name for f in fields}
        existing_pairs = {(f.name, f.value) for f in fields}
        table_pairs = parse_table_fields(raw_text)
        if "business_registration_number" in table_pairs:
            original = table_pairs["business_registration_number"]
            normalized, note = normalize_business_reg(original)
            if normalized != original:
                table_pairs["business_registration_number"] = normalized
                table_pairs.setdefault("__notes__", {})["business_registration_number"] = note
        normalize_notes = table_pairs.pop("__notes__", {})

        # 사업자등록증 라벨 매핑: 사업자등록증의 상호는 company_name 로 통일
        TABLE_REMAP = {"merchant_name": "company_name", "merchant_address": "business_address"}
        for field_name, value in table_pairs.items():
            field_name = TABLE_REMAP.get(field_name, field_name)
            if (field_name, value) in existing_pairs:
                continue
            if field_name in existing_names:
                continue
            base_note = "표 셀 라벨 매칭"
            if field_name in normalize_notes or "business_registration_number" in normalize_notes:
                if field_name == "business_registration_number":
                    base_note += "; " + normalize_notes["business_registration_number"]
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

        # 5) 라벨 인접 매칭 보완
        for field_name, labels, max_chars, conf in _LABEL_FIELDS:
            if field_name in existing_names:
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

        # 6) 사업장 주소 사전 매칭
        for f in fields:
            if f.name == "business_address":
                province, district, note = suggest_region(f.value)
                parts = [p for p in [province and f"시·도={province}", district and f"구={district}"] if p]
                if parts:
                    f.notes = ", ".join(parts) + (f" ({note})" if note else "")

        attach_bbox(fields, raw_blocks)
        return ExtractionResult(document_type=self.document_type, fields=fields)
