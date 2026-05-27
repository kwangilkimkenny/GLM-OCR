"""image_quality 단위 테스트 (Phase 6)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.core.image_quality import (
    QualityReport,
    analyze_image,
    is_low_quality,
    TARGET_SHORT_SIDE,
)


def _save_synthetic(tmp_path: Path, **kwargs) -> Path:
    """합성 문서 이미지 저장 (테스트용)."""
    h = kwargs.get("h", 1200)
    w = kwargs.get("w", 800)
    text_size = kwargs.get("text_size", 0.8)
    brightness = kwargs.get("brightness", 240)
    img = np.full((h, w, 3), brightness, dtype=np.uint8)
    # 임의 검은 텍스트
    for y in range(80, h - 80, 60):
        cv2.putText(
            img, "사업자등록증 123-45-67890", (40, y),
            cv2.FONT_HERSHEY_SIMPLEX, text_size, (20, 20, 20), 1, cv2.LINE_AA,
        )
    if kwargs.get("blur"):
        img = cv2.GaussianBlur(img, (9, 9), 0)
    if kwargs.get("dark"):
        img = (img.astype(np.int32) - 80).clip(0, 255).astype(np.uint8)
    if kwargs.get("shadow"):
        # 왼쪽 절반 어둡게
        img[:, : w // 2] = (img[:, : w // 2].astype(np.int32) - 60).clip(0, 255).astype(np.uint8)
    path = tmp_path / f"{kwargs.get('name', 'synthetic')}.png"
    cv2.imwrite(str(path), img)
    return path


def test_normal_image_no_action(tmp_path: Path):
    # 충분히 큰 글자(text_size=2.0 → 약 30px 높이) + 적정 밝기 + 적정 contrast
    h, w = 2200, 1700
    img = np.full((h, w, 3), 200, dtype=np.uint8)  # 회색 배경 → contrast 확보
    for y in range(150, h - 150, 100):
        cv2.putText(
            img, "사업자등록증 123-45-67890", (60, y),
            cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 4, cv2.LINE_AA,
        )
    p = tmp_path / "normal.png"
    cv2.imwrite(str(p), img)
    report = analyze_image(str(p))
    assert isinstance(report, QualityReport)
    assert report.short_side >= TARGET_SHORT_SIDE
    # 정상 이미지는 needs_upscale=False
    assert not report.needs_upscale, f"불필요한 upscale 트리거됨: {report.notes}"
    assert not report.needs_deblur


def test_low_resolution_triggers_upscale(tmp_path: Path):
    p = _save_synthetic(tmp_path, h=400, w=600, text_size=0.4)
    report = analyze_image(str(p))
    assert report.needs_upscale, f"보고: {report.notes}"
    assert report.upscale_factor > 1.0
    assert is_low_quality(report)


def test_blur_triggers_deblur(tmp_path: Path):
    p = _save_synthetic(tmp_path, h=2000, w=1600, blur=True)
    report = analyze_image(str(p))
    # 블러된 이미지는 laplacian variance 가 낮아야 함
    assert report.laplacian_var < 200


def test_shadow_triggers_deshadow(tmp_path: Path):
    p = _save_synthetic(tmp_path, h=1800, w=1400, shadow=True)
    report = analyze_image(str(p))
    # 한 쪽이 어두우면 shadow_score 가 커야 함
    assert report.shadow_score > 15  # 합성이므로 임계값 보다 약함


def test_dark_image_triggers_illumination(tmp_path: Path):
    p = _save_synthetic(tmp_path, h=1800, w=1400, dark=True)
    report = analyze_image(str(p))
    assert report.brightness < 200  # 어두워졌어야 함


def test_invalid_path_raises(tmp_path: Path):
    with pytest.raises(ValueError):
        analyze_image(str(tmp_path / "does_not_exist.png"))


def test_to_dict_serializable(tmp_path: Path):
    p = _save_synthetic(tmp_path)
    report = analyze_image(str(p))
    d = report.to_dict()
    assert "needs_upscale" in d
    assert "upscale_factor" in d
    assert isinstance(d["notes"], list)
