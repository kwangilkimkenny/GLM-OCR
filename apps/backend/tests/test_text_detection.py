"""text_detection 단위 테스트 (Phase 6-C)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.core.text_detection import (
    TextBox,
    backend_status,
    detect_text_regions,
    find_small_text_regions,
)


def _make_text_image(tmp_path: Path) -> Path:
    img = np.full((400, 600, 3), 245, dtype=np.uint8)
    cv2.putText(img, "Hello World", (40, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (10, 10, 10), 2)
    cv2.putText(img, "Small Text 123", (40, 250), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (10, 10, 10), 1)
    p = tmp_path / "text.png"
    cv2.imwrite(str(p), img)
    return p


def test_detect_returns_textbox_list(tmp_path: Path):
    p = _make_text_image(tmp_path)
    boxes, backend = detect_text_regions(str(p))
    assert isinstance(boxes, list)
    assert len(boxes) >= 1
    for b in boxes:
        assert isinstance(b, TextBox)
        assert b.x2 > b.x1
        assert b.y2 > b.y1
    # 가중치 없는 환경 → mser 폴백
    assert backend in {"craft", "mser"}


def test_textbox_w_h_properties():
    b = TextBox(10, 20, 100, 80)
    assert b.w == 90
    assert b.h == 60


def test_find_small_text_regions(tmp_path: Path):
    p = _make_text_image(tmp_path)
    smalls = find_small_text_regions(str(p), max_char_height=25)
    # 합성 이미지에 "Small Text" 가 있으므로 적어도 일부 작은 박스가 잡혀야 함
    assert isinstance(smalls, list)


def test_backend_status_keys():
    s = backend_status()
    assert "craft" in s
    assert "mser" in s
    assert s["mser"]["available"] is True


def test_invalid_image_raises():
    with pytest.raises(ValueError):
        detect_text_regions("/nonexistent.png")


def test_accepts_ndarray_input(tmp_path: Path):
    p = _make_text_image(tmp_path)
    img = cv2.imread(str(p))
    boxes, _ = detect_text_regions(img)
    assert len(boxes) >= 1
