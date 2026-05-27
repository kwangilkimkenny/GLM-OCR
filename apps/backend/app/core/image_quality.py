"""이미지 품질 자동 진단 (Phase 6).

업로드된 문서가 OCR에 적합한지 판단하고, 어떤 전처리가 필요한지 추천한다.

핵심 메트릭:
- DPI / 짧은 변 길이 → 저해상도 여부
- Laplacian variance → 블러 여부
- 히스토그램 std → 조명 불균형 / 그림자 여부
- 평균 밝기 → 과노출 / 과소노출 여부
- 텍스트 영역 추정 글자 높이 → 자모 patch 크기 미만 여부
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image


@dataclass
class QualityReport:
    """이미지 품질 진단 결과 + 권장 액션."""

    width: int
    height: int
    short_side: int
    dpi: Optional[int]
    laplacian_var: float
    brightness: float
    contrast: float
    shadow_score: float
    estimated_char_height: Optional[float]

    needs_upscale: bool = False
    upscale_factor: float = 1.0
    needs_deblur: bool = False
    needs_deshadow: bool = False
    needs_binarize: bool = False
    needs_illumination_correction: bool = False

    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# 권장 임계값 — 한국 금융 양식 문서 대상으로 튜닝.
TARGET_SHORT_SIDE = 1600        # 짧은 변 기준 OCR 최소 해상도
TARGET_DPI = 200                # 권장 DPI
MIN_CHAR_HEIGHT_PX = 20         # 14x14 patch 보장 위해 글자 높이 최소 20px
LAPLACIAN_BLUR_THRESHOLD = 80   # 미만이면 블러로 판단
SHADOW_STD_THRESHOLD = 40       # 조명 std 가 크면 그림자/조명 불균형
BRIGHTNESS_DARK = 90            # 평균 밝기 < 90 이면 어두움
BRIGHTNESS_BRIGHT = 200         # > 200 이면 과노출
CONTRAST_LOW_THRESHOLD = 35     # 표준편차 낮으면 contrast 부족


def _estimate_char_height(gray: np.ndarray) -> Optional[float]:
    """Otsu 이진화 후 contour 의 중앙값 높이로 글자 높이 추정.

    완벽하지 않지만 "글자가 너무 작은가" 판단에 충분.
    None 반환 시 추정 실패 (텍스트가 거의 없는 이미지).
    """
    inv = cv2.bitwise_not(gray)
    _, bw = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    heights: list[float] = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        # 글자 모양에 가까운 비율만 카운트 (가로:세로 0.2~3.0, 면적 4~5000)
        if h == 0 or w == 0:
            continue
        ratio = w / h
        area = w * h
        if 0.2 <= ratio <= 3.0 and 4 <= area <= 5000:
            heights.append(float(h))
    if not heights:
        return None
    return float(np.median(heights))


def _read_dpi(image_path: str | Path) -> Optional[int]:
    """PIL DPI 메타 추출. 모바일 카메라 사진은 보통 72 dpi 거나 None."""
    try:
        with Image.open(str(image_path)) as im:
            dpi = im.info.get("dpi")
            if dpi:
                # tuple 또는 float
                v = dpi[0] if isinstance(dpi, (tuple, list)) else dpi
                return int(round(float(v)))
    except Exception:
        pass
    return None


def _shadow_score(gray: np.ndarray) -> float:
    """이미지를 8x8 그리드로 나눠 셀 평균 밝기의 std.

    페이지 전체가 균일하면 작은 값, 한쪽이 어두우면 큰 값.
    """
    h, w = gray.shape[:2]
    rows, cols = 8, 8
    cell_h, cell_w = max(1, h // rows), max(1, w // cols)
    means = []
    for r in range(rows):
        for c in range(cols):
            cell = gray[r * cell_h : (r + 1) * cell_h, c * cell_w : (c + 1) * cell_w]
            if cell.size > 0:
                means.append(float(cell.mean()))
    if len(means) < 4:
        return 0.0
    return float(np.std(means))


def analyze_image(image_path: str | Path) -> QualityReport:
    """이미지 파일을 분석하고 권장 액션을 채워 QualityReport 반환.

    OCR 실패 가능성이 높으면 needs_* 플래그가 True 로 채워진다.
    """
    image_path = str(image_path)
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"failed to read image: {image_path}")
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean())
    contrast = float(gray.std())
    shadow = _shadow_score(gray)
    dpi = _read_dpi(image_path)
    char_h = _estimate_char_height(gray)
    short_side = min(h, w)

    report = QualityReport(
        width=w,
        height=h,
        short_side=short_side,
        dpi=dpi,
        laplacian_var=lap_var,
        brightness=brightness,
        contrast=contrast,
        shadow_score=shadow,
        estimated_char_height=char_h,
    )

    # ─── 권장 액션 산출 ───
    # 1. 업스케일: 짧은 변이 TARGET 미만이거나, 글자 높이가 patch 미만
    upscale_factor = 1.0
    if short_side < TARGET_SHORT_SIDE:
        upscale_factor = max(upscale_factor, TARGET_SHORT_SIDE / short_side)
    if char_h is not None and char_h < MIN_CHAR_HEIGHT_PX:
        upscale_factor = max(upscale_factor, MIN_CHAR_HEIGHT_PX / char_h)
    if dpi is not None and dpi > 0 and dpi < TARGET_DPI:
        upscale_factor = max(upscale_factor, TARGET_DPI / dpi)
    # 4배 이상은 SR 효과보다 노이즈 증폭이 큼 — clamp
    upscale_factor = min(upscale_factor, 4.0)
    if upscale_factor >= 1.2:
        report.needs_upscale = True
        report.upscale_factor = round(upscale_factor, 2)
        report.notes.append(
            f"short_side={short_side} dpi={dpi} char_h={char_h} → upscale x{upscale_factor:.2f}"
        )

    # 2. deblur
    if lap_var < LAPLACIAN_BLUR_THRESHOLD:
        report.needs_deblur = True
        report.notes.append(f"laplacian_var={lap_var:.1f} < {LAPLACIAN_BLUR_THRESHOLD} → deblur")

    # 3. deshadow / illumination correction
    if shadow > SHADOW_STD_THRESHOLD:
        report.needs_deshadow = True
        report.notes.append(f"shadow_score={shadow:.1f} > {SHADOW_STD_THRESHOLD} → deshadow")
    if brightness < BRIGHTNESS_DARK or brightness > BRIGHTNESS_BRIGHT:
        report.needs_illumination_correction = True
        report.notes.append(
            f"brightness={brightness:.1f} 비정상 (range {BRIGHTNESS_DARK}-{BRIGHTNESS_BRIGHT})"
        )

    # 4. binarize
    if contrast < CONTRAST_LOW_THRESHOLD:
        report.needs_binarize = True
        report.notes.append(f"contrast={contrast:.1f} < {CONTRAST_LOW_THRESHOLD} → binarize")

    return report


def is_low_quality(report: QualityReport) -> bool:
    """전처리가 필요한지 한 줄 판단."""
    return any(
        [
            report.needs_upscale,
            report.needs_deblur,
            report.needs_deshadow,
            report.needs_illumination_correction,
            report.needs_binarize,
        ]
    )
