"""신분증(주민등록증/운전면허/외국인등록증) 추출기."""

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
    _RRN_RE,
    _Span,
    _claim,
    _is_foreign_rrn,
    _label_value,
    _mask_rrn,
    _overlaps,
    _validate_rrn,
)
from app.core.validators import suggest_region


# 운전면허번호: 12-34-567890-12 (지역-연도-일련번호-검사)
_LICENSE_RE = re.compile(r"\b(\d{2})\s*-\s*(\d{2})\s*-\s*(\d{6})\s*-\s*(\d{2})\b")

# 발급일자: 2024-08-15 / 2024.08.15 / 2024년 8월 15일
_DATE_RE = re.compile(
    r"(\d{4})\s*[년./\-]\s*(\d{1,2})\s*[월./\-]\s*(\d{1,2})\s*일?"
)

_LABEL_FIELDS = [
    ("name", ("성명",), 12, 0.7),
    ("issue_date", ("발급일자", "발급일"), 16, 0.7),
    ("issuer", ("발급기관", "발급청"), 30, 0.65),
    ("license_class", ("종별", "면허종류"), 12, 0.65),
    ("nationality", ("국적",), 12, 0.65),
]


class IdCardExtractor(FieldExtractor):
    document_type = "id_card"

    def extract(
        self,
        raw_text: str,
        raw_blocks: Optional[list[LayoutBlock]] = None,
    ) -> ExtractionResult:
        fields: list[ExtractedField] = []
        used_spans: list[_Span] = []

        # 1) 운전면허번호 (가장 specific 4-grp)
        for m in _LICENSE_RE.finditer(raw_text):
            if _overlaps(m.start(), m.end(), used_spans):
                continue
            _claim(m.start(), m.end(), used_spans)
            license_no = f"{m.group(1)}-{m.group(2)}-{m.group(3)}-{m.group(4)}"
            fields.append(
                ExtractedField(
                    name="license_number",
                    value=license_no,
                    confidence=0.85,
                    validation_status="ok",
                    source_match=m.group(0),
                )
            )

        # 2) 주민/외국인등록번호 (6-7)
        for m in _RRN_RE.finditer(raw_text):
            if _overlaps(m.start(), m.end(), used_spans):
                continue
            _claim(m.start(), m.end(), used_spans)
            front, back = m.group(1), m.group(2)
            digits = front + back
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

        # 3) 발급일 (라벨 인근만 — 임의 날짜 노이즈 제외)
        for m in _DATE_RE.finditer(raw_text):
            if _overlaps(m.start(), m.end(), used_spans):
                continue
            window = raw_text[max(0, m.start() - 20) : m.end() + 5]
            if not any(kw in window for kw in ("발급", "발행")):
                continue
            _claim(m.start(), m.end(), used_spans)
            normalized = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
            fields.append(
                ExtractedField(
                    name="issue_date",
                    value=normalized,
                    confidence=0.8,
                    validation_status="unverified",
                    source_match=m.group(0),
                )
            )
            break  # 신분증 발급일은 보통 1건

        # 4) 표 셀 라벨 매칭
        existing_names = {f.name for f in fields}
        existing_pairs = {(f.name, f.value) for f in fields}
        for field_name, value in parse_table_fields(raw_text).items():
            if (field_name, value) in existing_pairs:
                continue
            if field_name in existing_names:
                continue
            fields.append(
                ExtractedField(
                    name=field_name,
                    value=value,
                    confidence=0.75,
                    validation_status="unverified",
                    source_match=value,
                    notes="표 셀 라벨 매칭",
                )
            )
            existing_names.add(field_name)
            existing_pairs.add((field_name, value))

        # 5) 라벨 인접 항목 (표에 없는 경우)
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

        # 6) 주소 사전 매칭 (신분증의 주소/본적 검증)
        for f in fields:
            if f.name == "address":
                province, district, note = suggest_region(f.value)
                parts = [p for p in [province and f"시·도={province}", district and f"구={district}"] if p]
                if parts:
                    f.notes = ", ".join(parts) + (f" ({note})" if note else "")

        attach_bbox(fields, raw_blocks)
        return ExtractionResult(document_type=self.document_type, fields=fields)
