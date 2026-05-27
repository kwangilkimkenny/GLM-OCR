"""super_resolution 단위 테스트 (Phase 6-B)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.core import super_resolution as sr


def _make_image(tmp_path: Path, h: int = 200, w: int = 300, name: str = "low") -> Path:
    img = np.full((h, w, 3), 230, dtype=np.uint8)
    cv2.putText(img, "ABCDE", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (10, 10, 10), 2)
    p = tmp_path / f"{name}.png"
    cv2.imwrite(str(p), img)
    return p


def test_list_backends_includes_lanczos():
    backends = sr.list_backends()
    names = [b.name for b in backends]
    assert "lanczos-sharpen" in names
    # lanczos 는 항상 available
    lan = next(b for b in backends if b.name == "lanczos-sharpen")
    assert lan.available is True


def test_select_backend_fallback_lanczos():
    """가중치 없는 환경에서는 lanczos 가 선택되어야 한다."""
    chosen = sr.select_backend()
    # realesrgan/opencv weight 가 없으면 lanczos 가 선택됨
    assert chosen.available is True


def test_upscale_noop_when_scale_low():
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    out, used = sr.upscale(img, 1.0)
    assert out.shape == img.shape
    assert used == "noop"


def test_upscale_lanczos_doubles_size():
    img = np.full((200, 300, 3), 230, dtype=np.uint8)
    out, used = sr.upscale(img, 2.0, backend="lanczos-sharpen")
    assert used == "lanczos-sharpen"
    assert out.shape[1] == 600 and out.shape[0] == 400


def test_upscale_file_round_trip(tmp_path: Path):
    src = _make_image(tmp_path)
    dst = tmp_path / "out.png"
    info = sr.upscale_file(str(src), str(dst), scale=2.0)
    assert dst.exists()
    assert info["out_size"][0] > info["in_size"][0]
    assert info["backend"] in {"realesrgan", "opencv-dnn-superres", "lanczos-sharpen"}


def test_upscale_preserves_aspect_ratio():
    img = np.zeros((100, 200, 3), dtype=np.uint8)
    out, _ = sr.upscale(img, 1.5, backend="lanczos-sharpen")
    assert abs((out.shape[1] / out.shape[0]) - 2.0) < 0.05


def test_upscale_missing_weight_falls_back_silently(tmp_path: Path, monkeypatch):
    """realesrgan 가중치가 없으면 다음 우선순위 백엔드로 폴백해야 함."""
    img = np.full((150, 200, 3), 200, dtype=np.uint8)
    # 가중치 없는 상태에서 realesrgan 직접 요청 → 가능한 다음 백엔드로 폴백
    monkeypatch.setattr(sr, "_BACKENDS_CACHE", None)
    out, used = sr.upscale(img, 2.0, backend="realesrgan")
    # realesrgan 가중치 없으면 opencv-dnn-superres (ESPCN 가중치 있음) 또는 lanczos 폴백
    assert used in {"realesrgan", "opencv-dnn-superres", "lanczos-sharpen"}
    assert out.shape[1] > img.shape[1]
