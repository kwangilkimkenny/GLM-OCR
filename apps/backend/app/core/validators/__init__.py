"""사전 매칭 기반 후처리 검증 + 근거 검증 + PII 탐지.

- bank/region: OCR 한글 환각으로 인한 오인식 보정용 사전 매칭
- grounding: 추출값이 raw OCR 에 실제 존재하는지 (Near-Zero Hallucination)
- pii: 개인정보 자동 탐지 + 마스킹 정책 적용
"""

from app.core.validators.bank import lookup_bank_by_account_prefix, normalize_bank_name
from app.core.validators.grounding import apply_grounding, is_grounded
from app.core.validators.pii import (
    apply_masking_policy,
    detect_pii_in_text,
    mask_pii_in_text,
    MaskingLevel,
    SENSITIVE_FIELD_NAMES,
)
from app.core.validators.region import suggest_region

__all__ = [
    "lookup_bank_by_account_prefix",
    "normalize_bank_name",
    "suggest_region",
    "apply_grounding",
    "is_grounded",
    "apply_masking_policy",
    "detect_pii_in_text",
    "mask_pii_in_text",
    "MaskingLevel",
    "SENSITIVE_FIELD_NAMES",
]
