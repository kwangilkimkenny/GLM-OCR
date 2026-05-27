"""문서 유형별 필드 추출기.

OCR raw text를 받아 사업자번호·계좌번호 등 구조화된 필드로 변환한다.
Phase 2 (필드 추출 & 검증)의 진입점.
"""

from app.core.extractors._consensus import consensus_merge
from app.core.extractors.bank_book import BankBookExtractor
from app.core.extractors.base import ExtractedField, ExtractionResult, FieldExtractor
from app.core.extractors.business_reg import BusinessRegExtractor
from app.core.extractors.id_card import IdCardExtractor
from app.core.extractors.merchant_application import MerchantApplicationExtractor
from app.core.extractors.registry import get_extractor

__all__ = [
    "BankBookExtractor",
    "BusinessRegExtractor",
    "ExtractedField",
    "ExtractionResult",
    "FieldExtractor",
    "IdCardExtractor",
    "MerchantApplicationExtractor",
    "consensus_merge",
    "get_extractor",
]
