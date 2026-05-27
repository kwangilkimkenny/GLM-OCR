"""두 엔진의 ExtractionResult를 합의 병합.

전략:
- 필드명이 같고 값이 같으면 → consensus="agreed", validation_status="ok", confidence↑
- 필드명이 같지만 값이 다르면 → consensus="conflict", 신뢰도 높은 쪽 채택, notes에 대립 값
- 한 쪽 엔진에서만 추출되면 → consensus="single"

다중 값을 가질 수 있는 필드(예: 계좌번호 2건)는 value 기반 매칭.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from app.core.extractors.base import ExtractedField, ExtractionResult


def _normalize(s: str) -> str:
    return (s or "").replace(" ", "").replace(" ", "").strip().casefold()


def _group_by_name(fields: Iterable[ExtractedField]) -> dict[str, list[ExtractedField]]:
    out: dict[str, list[ExtractedField]] = {}
    for f in fields:
        out.setdefault(f.name, []).append(f)
    return out


def consensus_merge(
    primary: ExtractionResult,
    secondary: ExtractionResult,
    primary_engine: str = "qwen",
    secondary_engine: str = "glm-ocr",
) -> tuple[ExtractionResult, dict[str, int]]:
    """primary(메인 엔진) + secondary(보조 엔진) 결과를 합쳐 합의 결과 + 통계 반환."""
    p_by_name = _group_by_name(primary.fields)
    s_by_name = _group_by_name(secondary.fields)

    merged: list[ExtractedField] = []
    seen_names: set[str] = set()

    for name, p_list in p_by_name.items():
        seen_names.add(name)
        s_list = s_by_name.get(name, [])

        # value 정규화 인덱스
        p_norm = {_normalize(f.value): f for f in p_list}
        s_norm = {_normalize(f.value): f for f in s_list}

        common_keys = set(p_norm) & set(s_norm)
        p_only = set(p_norm) - common_keys
        s_only = set(s_norm) - common_keys

        # 1) 두 엔진 동일 값 → agreed
        for k in common_keys:
            base = p_norm[k]
            note_parts = [base.notes] if base.notes else []
            note_parts.append("교차검증 일치")
            merged.append(
                replace(
                    base,
                    confidence=max(base.confidence, 0.95),
                    validation_status="ok" if base.validation_status != "invalid" else "invalid",
                    engines=[primary_engine, secondary_engine],
                    consensus="agreed",
                    notes="; ".join(note_parts),
                )
            )

        # 2) Primary 만 추출
        if p_only and s_only:
            # 같은 필드명에 양쪽 모두 자기만의 값 → conflict
            # Primary 값을 채택, secondary 값을 notes 에 대안으로 표시
            alts = ", ".join(s_norm[k].value for k in sorted(s_only))
            for k in p_only:
                base = p_norm[k]
                note_parts = [base.notes] if base.notes else []
                note_parts.append(f"불일치 후보({secondary_engine}): {alts}")
                merged.append(
                    replace(
                        base,
                        engines=[primary_engine],
                        consensus="conflict",
                        notes="; ".join(note_parts),
                    )
                )
        elif p_only:
            for k in p_only:
                base = p_norm[k]
                merged.append(
                    replace(base, engines=[primary_engine], consensus="single")
                )
        elif s_only and not common_keys:
            # primary 가 같은 필드명을 잡지 않았는데 우연히 위 branch 진입 — 이론상 도달 안 함
            for k in s_only:
                base = s_norm[k]
                merged.append(
                    replace(base, engines=[secondary_engine], consensus="single")
                )

    # 3) Secondary 만 잡은 필드명 (Primary 가 아예 보지 못한 항목)
    for name, s_list in s_by_name.items():
        if name in seen_names:
            continue
        for f in s_list:
            merged.append(
                replace(f, engines=[secondary_engine], consensus="single")
            )

    # 통계
    summary = {"agreed": 0, "conflict": 0, "single": 0, "total": len(merged)}
    for f in merged:
        if f.consensus in summary:
            summary[f.consensus] += 1

    return (
        ExtractionResult(
            document_type=primary.document_type or secondary.document_type,
            fields=merged,
        ),
        summary,
    )
