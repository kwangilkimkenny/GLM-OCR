"""문서 유형 → 추출기 인스턴스 매핑."""

from __future__ import annotations

from app.core.extractors.bank_book import BankBookExtractor
from app.core.extractors.base import FieldExtractor
from app.core.extractors.business_reg import BusinessRegExtractor
from app.core.extractors.id_card import IdCardExtractor
from app.core.extractors.merchant_application import MerchantApplicationExtractor


_REGISTRY: dict[str, FieldExtractor] = {
    MerchantApplicationExtractor.document_type: MerchantApplicationExtractor(),
    IdCardExtractor.document_type: IdCardExtractor(),
    BankBookExtractor.document_type: BankBookExtractor(),
    BusinessRegExtractor.document_type: BusinessRegExtractor(),
}


def get_extractor(document_type: str | None) -> FieldExtractor | None:
    """document_type 에 매칭되는 추출기를 반환. 없으면 None.

    None / "freeform" 은 추출 생략 (raw OCR 만 노출).
    """
    if not document_type or document_type == "freeform":
        return None
    return _REGISTRY.get(document_type)
