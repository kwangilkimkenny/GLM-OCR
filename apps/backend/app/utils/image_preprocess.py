"""저품질 문서 복원 — 자동 전처리 (Phase 2-B + 6-A).

파이프라인:
    [SR upscale] → deskew → [deshadow] → [illumination correction]
    → denoise → CLAHE → unsharp → [adaptive threshold]

각 단계는 옵션. `auto_quality=True` 면 `image_quality.QualityReport` 진단에 따라
필요한 단계만 자동 선택.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np

# 순환 import 회피: app.core.__init__ → task_manager → flows → layout_ocr → image_preprocess
# 따라서 super_resolution / image_quality 는 함수 내부에서 지연 import.


def deskew(gray: np.ndarray) -> tuple[np.ndarray, float]:
    """텍스트 마스크의 minAreaRect 로 기울기 각도 추정 후 회전.

    |angle| < 0.3° 면 그대로 둠 (resample artifact 방지).
    """
    inv = cv2.bitwise_not(gray)
    _, thresh = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(thresh > 0))
    if coords.size == 0:
        return gray, 0.0
    raw = cv2.minAreaRect(coords)[-1]
    # minAreaRect 각도 규약은 OpenCV 버전마다 다르다(≥4.5: (0,90], ≤4.4: [-90,0)).
    # [-45, 45] 로 정규화해 90°/−90° 과회전을 막는다.
    if raw > 45:
        raw -= 90
    elif raw < -45:
        raw += 90
    # 정규화 값은 감지된 기울기(°). 텍스트를 수평으로 만들려면 반대 방향으로 회전.
    # (cv2 4.13 에서 합성 기울기 이미지로 검증: 보정각 = -정규화각.)
    angle = -raw
    if abs(angle) < 0.3:
        return gray, angle
    h, w = gray.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rotated = cv2.warpAffine(
        gray, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )
    return rotated, angle


def unsharp_mask(img: np.ndarray, ksize: int = 5, amount: float = 1.0) -> np.ndarray:
    blurred = cv2.GaussianBlur(img, (ksize, ksize), 0)
    return cv2.addWeighted(img, 1 + amount, blurred, -amount, 0)


def remove_shadow(gray: np.ndarray) -> np.ndarray:
    """배경 추정 후 정규화로 그림자 제거 (BEDSR 아이디어의 경량 구현).

    1. dilate 로 글자 제거 → 배경 추정
    2. median blur 로 부드럽게
    3. 원본을 배경으로 나눠 정규화
    """
    bg = cv2.dilate(gray, np.ones((7, 7), np.uint8))
    bg = cv2.medianBlur(bg, 21)
    # divide 시 zero-division 방지 위해 max(1) 처리
    safe_bg = np.maximum(bg, 1)
    norm = cv2.divide(gray, safe_bg, scale=255)
    # 8-bit 범위 보장
    return np.clip(norm, 0, 255).astype(np.uint8)


def correct_illumination(gray: np.ndarray, target_mean: float = 160.0) -> np.ndarray:
    """평균 밝기를 target_mean 근처로 맞추는 감마 보정.

    어두운 사진 ↑, 너무 밝은 사진 ↓.
    """
    mean = float(gray.mean()) if gray.size > 0 else target_mean
    if mean <= 1:
        return gray
    # gamma > 1 → 어두워짐, gamma < 1 → 밝아짐
    gamma = float(np.log(target_mean / 255.0) / np.log(max(mean, 1) / 255.0))
    gamma = float(np.clip(gamma, 0.5, 2.0))
    if abs(gamma - 1.0) < 0.05:
        return gray
    lut = np.clip(255.0 * (np.arange(256) / 255.0) ** (1.0 / gamma), 0, 255).astype(np.uint8)
    return cv2.LUT(gray, lut)


def preprocess_image(
    img: np.ndarray,
    *,
    do_deskew: bool = True,
    binarize: bool = False,
    target_width: Optional[int] = None,
    upscale_factor: float = 1.0,
    do_deshadow: bool = False,
    do_illumination: bool = False,
    sr_backend: Optional[str] = None,
) -> tuple[np.ndarray, dict]:
    """BGR 이미지를 OCR 친화 형태로 정제.

    Returns:
        (출력 BGR, info 메타)
    """
    info: dict = {}
    h0, w0 = img.shape[:2]
    info["orig_size"] = (w0, h0)

    # ─── 1. SR 업스케일 (Phase 6-B) — target_width 보다 우선 ───
    if upscale_factor and upscale_factor > 1.05:
        from app.core import super_resolution as sr_mod  # lazy import
        img, backend_used = sr_mod.upscale(img, upscale_factor, backend=sr_backend)
        info["sr_backend"] = backend_used
        info["sr_factor"] = round(float(upscale_factor), 2)
        info["sr_size"] = (img.shape[1], img.shape[0])
    elif target_width and w0 != target_width:
        scale = target_width / w0
        img = cv2.resize(img, (target_width, int(h0 * scale)), interpolation=cv2.INTER_CUBIC)
        info["resized_to"] = (target_width, int(h0 * scale))

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # ─── 2. deskew ───
    if do_deskew:
        gray, angle = deskew(gray)
        info["deskew_angle"] = round(float(angle), 3)

    # ─── 3. 그림자 제거 (Phase 6-A) ───
    if do_deshadow:
        gray = remove_shadow(gray)
        info["deshadow"] = True

    # ─── 4. 조명 보정 ───
    if do_illumination:
        gray = correct_illumination(gray)
        info["illumination"] = True

    # ─── 5. denoise + CLAHE + unsharp ───
    gray = cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    gray = unsharp_mask(gray, ksize=5, amount=1.0)

    # ─── 6. 적응적 이진화 ───
    if binarize:
        gray = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 12
        )
        info["binarized"] = True

    out = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return out, info


def preprocess_image_file(
    input_path: str,
    output_path: str,
    *,
    do_deskew: bool = True,
    binarize: bool = False,
    target_width: Optional[int] = None,
    upscale_factor: float = 1.0,
    do_deshadow: bool = False,
    do_illumination: bool = False,
    sr_backend: Optional[str] = None,
) -> dict:
    """파일 in/out. cv2.imread/imwrite. Returns info dict."""
    img = cv2.imread(input_path)
    if img is None:
        raise ValueError(f"failed to load image: {input_path}")
    out, info = preprocess_image(
        img,
        do_deskew=do_deskew,
        binarize=binarize,
        target_width=target_width,
        upscale_factor=upscale_factor,
        do_deshadow=do_deshadow,
        do_illumination=do_illumination,
        sr_backend=sr_backend,
    )
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(output_path, out)
    info["input"] = input_path
    info["output"] = output_path
    return info


def auto_preprocess_file(input_path: str, output_path: str) -> dict:
    """`image_quality` 진단 → 권장된 단계만 자동 수행.

    어떤 단계든 필요 없다고 진단되면 원본을 그대로 복사 (info 에 표시).
    """
    from app.core import image_quality  # lazy import (순환 import 회피)

    report = image_quality.analyze_image(input_path)
    info: dict = {"quality_report": report.to_dict()}

    if not image_quality.is_low_quality(report):
        # 원본 그대로 — 다만 일관된 인터페이스 유지 위해 복사
        img = cv2.imread(input_path)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(output_path, img)
        info.update({"input": input_path, "output": output_path, "skipped": True})
        return info

    out_info = preprocess_image_file(
        input_path,
        output_path,
        do_deskew=True,
        binarize=report.needs_binarize,
        upscale_factor=report.upscale_factor if report.needs_upscale else 1.0,
        do_deshadow=report.needs_deshadow,
        do_illumination=report.needs_illumination_correction,
    )
    info.update(out_info)
    return info
