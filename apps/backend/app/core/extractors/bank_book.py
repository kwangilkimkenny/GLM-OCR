"""통장 사본 추출기 — 은행명/계좌번호/예금주."""

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
    _BANK_ACCOUNT_RE,
    _Span,
    _claim,
    _label_value,
    _mask_account,
    _overlaps,
)
from app.core.validators import (
    lookup_bank_by_account_prefix,
    normalize_bank_name,
)


_LABEL_FIELDS = [
    ("account_holder", ("예금주",), 16, 0.75),
    ("bank_name", ("은행명", "은행"), 16, 0.65),
    ("branch", ("지점", "개설지점"), 20, 0.6),
]


class BankBookExtractor(FieldExtractor):
    document_type = "bank_book"

    def extract(
        self,
        raw_text: str,
        raw_blocks: Optional[list[LayoutBlock]] = None,
    ) -> ExtractionResult:
        fields: list[ExtractedField] = []
        used_spans: list[_Span] = []

        # 1) 계좌번호 (3-3-7 등 가변)
        seen_accounts: set[str] = set()
        for m in _BANK_ACCOUNT_RE.finditer(raw_text):
            if _overlaps(m.start(), m.end(), used_spans):
                continue
            normalized = re.sub(r"\s+", "", m.group(0))
            if normalized in seen_accounts:
                continue
            seen_accounts.add(normalized)
            _claim(m.start(), m.end(), used_spans)
            fields.append(
                ExtractedField(
                    name="account_number",
                    value=normalized,
                    confidence=0.85,
                    validation_status="unverified",
                    masked_value=_mask_account(normalized),
                    source_match=m.group(0),
                )
            )

        # 2) 은행명 — 텍스트 alias 매칭 + 계좌 prefix 추정 (둘이 일치하면 confidence↑)
        bank_from_alias = normalize_bank_name(raw_text[:300])
        bank_from_account = None
        for f in fields:
            if f.name == "account_number":
                bank_from_account = lookup_bank_by_account_prefix(f.value)
                if bank_from_account:
                    f.notes = f"매칭 은행: {bank_from_account}"
                    f.validation_status = "ok"
                    f.confidence = max(f.confidence, 0.9)
                break

        bank_value = bank_from_alias or bank_from_account
        if bank_value:
            confidence = 0.95 if (bank_from_alias and bank_from_account and bank_from_alias == bank_from_account) else 0.65
            note = "alias+prefix 일치" if confidence >= 0.9 else "사전 alias 매칭"
            fields.append(
                ExtractedField(
                    name="bank_name",
                    value=bank_value,
                    confidence=confidence,
                    validation_status="ok" if confidence >= 0.9 else "unverified",
                    source_match=bank_value,
                    notes=note,
                )
            )

        # 3) 표 셀 라벨 매칭
        existing_names = {f.name for f in fields}
        existing_pairs = {(f.name, f.value) for f in fields}
        for field_name, value in parse_table_fields(raw_text).items():
            # _table_parser 는 통장 라벨을 "bank_account_number" 로 매핑하나 통장 도메인에선 "account_number"
            if field_name == "bank_account_number":
                field_name = "account_number"
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

        # 4) 라벨 인접 항목
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

        attach_bbox(fields, raw_blocks)
        return ExtractionResult(document_type=self.document_type, fields=fields)
