"""텍스트 영역 검출 (Phase 6-C).

PP-DocLayoutV3 가 잡지 못하는 작은 글자 영역을 검출하기 위한 보조 모듈.
한글 조합 문자(자모)에 친화적인 CRAFT 를 1순위로, fallback 으로 MSER 기반 검출.

백엔드:
    1. **craft** — CRAFTNet (torch). 가중치 `models/text_det/craft_mlt_25k.pth`
    2. **mser** — OpenCV MSER + morphology (항상 사용 가능, 정밀도 낮음)
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


DEFAULT_DET_DIR = Path(__file__).resolve().parents[2] / "data" / "text_det"
DET_DIR = Path(os.environ.get("WOORI_TEXT_DET_DIR") or DEFAULT_DET_DIR)
CRAFT_WEIGHT = DET_DIR / "craft_mlt_25k.pth"

_LOCK = threading.Lock()
_MODEL_CACHE: dict[str, object] = {}


@dataclass
class TextBox:
    """검출된 단일 텍스트 박스. 픽셀 좌표."""

    x1: int
    y1: int
    x2: int
    y2: int
    confidence: float = 1.0
    source: str = ""  # "craft" | "mser"

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def w(self) -> int:
        return self.x2 - self.x1

    @property
    def h(self) -> int:
        return self.y2 - self.y1


def _craft_available() -> bool:
    try:
        import torch  # noqa: F401
    except ImportError:
        return False
    return CRAFT_WEIGHT.exists()


# ────── CRAFT (torch) ──────


def _build_craft():
    """공식 CRAFT 아키텍처 (VGG16-BN 백본 + U-Net 디코더) 최소 구현."""
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torchvision import models

    class DoubleConv(nn.Module):
        def __init__(self, in_ch, mid_ch, out_ch):
            super().__init__()
            self.conv = nn.Sequential(
                nn.Conv2d(in_ch + mid_ch, mid_ch, 1),
                nn.BatchNorm2d(mid_ch),
                nn.ReLU(inplace=True),
                nn.Conv2d(mid_ch, out_ch, 3, padding=1),
                nn.BatchNorm2d(out_ch),
                nn.ReLU(inplace=True),
            )

        def forward(self, x, y):
            x = torch.cat([x, y], dim=1)
            return self.conv(x)

    class VGG16BN(nn.Module):
        def __init__(self):
            super().__init__()
            base = models.vgg16_bn(weights=None).features
            self.slice1 = nn.Sequential(*list(base)[:12])
            self.slice2 = nn.Sequential(*list(base)[12:19])
            self.slice3 = nn.Sequential(*list(base)[19:29])
            self.slice4 = nn.Sequential(*list(base)[29:39])
            self.slice5 = nn.Sequential(
                nn.MaxPool2d(kernel_size=3, stride=1, padding=1),
                nn.Conv2d(512, 1024, 3, padding=6, dilation=6),
                nn.Conv2d(1024, 1024, 1),
            )

        def forward(self, x):
            h = self.slice1(x); h_relu2_2 = h
            h = self.slice2(h); h_relu3_2 = h
            h = self.slice3(h); h_relu4_3 = h
            h = self.slice4(h); h_relu5_3 = h
            h = self.slice5(h); h_fc7 = h
            return [h_fc7, h_relu5_3, h_relu4_3, h_relu3_2, h_relu2_2]

    class CRAFT(nn.Module):
        def __init__(self):
            super().__init__()
            self.basenet = VGG16BN()
            self.upconv1 = DoubleConv(1024, 512, 256)
            self.upconv2 = DoubleConv(512, 256, 128)
            self.upconv3 = DoubleConv(256, 128, 64)
            self.upconv4 = DoubleConv(128, 64, 32)
            num_class = 2  # region, affinity
            self.conv_cls = nn.Sequential(
                nn.Conv2d(32, 32, 3, padding=1), nn.ReLU(inplace=True),
                nn.Conv2d(32, 32, 3, padding=1), nn.ReLU(inplace=True),
                nn.Conv2d(32, 16, 3, padding=1), nn.ReLU(inplace=True),
                nn.Conv2d(16, 16, 1), nn.ReLU(inplace=True),
                nn.Conv2d(16, num_class, 1),
            )

        def forward(self, x):
            sources = self.basenet(x)
            y = F.interpolate(sources[0], size=sources[1].size()[2:], mode="bilinear", align_corners=False)
            y = self.upconv1(y, sources[1])
            y = F.interpolate(y, size=sources[2].size()[2:], mode="bilinear", align_corners=False)
            y = self.upconv2(y, sources[2])
            y = F.interpolate(y, size=sources[3].size()[2:], mode="bilinear", align_corners=False)
            y = self.upconv3(y, sources[3])
            y = F.interpolate(y, size=sources[4].size()[2:], mode="bilinear", align_corners=False)
            feat = self.upconv4(y, sources[4])
            y = self.conv_cls(feat)
            return y.permute(0, 2, 3, 1), feat

    return CRAFT()


def _load_craft():
    import torch

    key = "craft"
    model = _MODEL_CACHE.get(key)
    if model is not None:
        return model
    with _LOCK:
        model = _MODEL_CACHE.get(key)
        if model is None:
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model = _build_craft()
            state = torch.load(str(CRAFT_WEIGHT), map_location="cpu")
            # CRAFT 공식 가중치는 'module.<key>' prefix 포함
            cleaned: dict = {}
            for k, v in state.items():
                cleaned[k.replace("module.", "", 1) if k.startswith("module.") else k] = v
            model.load_state_dict(cleaned, strict=False)
            model.eval()
            model = model.to(device)
            _MODEL_CACHE[key] = model
        return model


def _detect_craft(img_bgr: np.ndarray, text_threshold: float = 0.7, link_threshold: float = 0.4) -> list[TextBox]:
    """CRAFT region+affinity map → bbox 추출."""
    import torch

    model = _load_craft()
    device = next(model.parameters()).device  # type: ignore[union-attr]

    # 정규화 (CRAFT 표준)
    h, w = img_bgr.shape[:2]
    target = 1280
    ratio = target / max(h, w)
    if ratio < 1.0:
        new_w, new_h = int(w * ratio), int(h * ratio)
    else:
        new_w, new_h = w, h
        ratio = 1.0
    new_w = (new_w // 32) * 32
    new_h = (new_h // 32) * 32
    resized = cv2.resize(img_bgr, (new_w, new_h))
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32)
    rgb = (rgb / 255.0 - np.array([0.485, 0.456, 0.406])) / np.array([0.229, 0.224, 0.225])
    tensor = torch.from_numpy(rgb.transpose(2, 0, 1)).unsqueeze(0).float().to(device)

    with torch.no_grad():
        y, _ = model(tensor)
    score_text = y[0, :, :, 0].cpu().numpy()
    score_link = y[0, :, :, 1].cpu().numpy()

    # 박스 추출 (region threshold 후 connected components → bounding rect)
    text_bin = (score_text >= text_threshold).astype(np.uint8)
    link_bin = (score_link >= link_threshold).astype(np.uint8)
    combined = np.clip(text_bin + link_bin, 0, 1).astype(np.uint8) * 255
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(combined, connectivity=4)
    boxes: list[TextBox] = []
    sx = w / new_w * 2  # heatmap 은 input 의 1/2 해상도
    sy = h / new_h * 2
    for i in range(1, n_labels):
        x, yy, ww, hh, area = stats[i]
        if area < 10:
            continue
        x1 = int(x * sx); y1 = int(yy * sy)
        x2 = int((x + ww) * sx); y2 = int((yy + hh) * sy)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            continue
        boxes.append(TextBox(x1, y1, x2, y2, confidence=float(score_text.max()), source="craft"))
    return boxes


# ────── MSER fallback ──────


def _detect_mser(img_bgr: np.ndarray, *, min_area: int = 40, max_area: int = 8000) -> list[TextBox]:
    """OpenCV MSER 기반. CRAFT 없을 때 폴백.

    한글 자모가 분리되어 검출될 수 있으나, morph close 로 단어 단위로 결합 시도.
    """
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    mser = cv2.MSER_create()
    mser.setMinArea(min_area)
    mser.setMaxArea(max_area)
    regions, _ = mser.detectRegions(gray)

    h, w = gray.shape
    mask = np.zeros((h, w), dtype=np.uint8)
    for pts in regions:
        hull = cv2.convexHull(pts.reshape(-1, 1, 2))
        cv2.fillConvexPoly(mask, hull, 255)

    # 단어 단위 결합: 가로 방향으로 dilation (글자 사이 공백 1-2글자 정도 메우기)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[TextBox] = []
    for c in contours:
        x, y, ww, hh = cv2.boundingRect(c)
        if ww < 8 or hh < 6:
            continue
        # 너무 가로로 긴 영역(line 일 가능성) 또는 너무 정사각형 큰 영역 제외
        ratio = ww / max(hh, 1)
        if ratio > 30:
            continue
        if ww * hh > 0.5 * w * h:
            continue
        boxes.append(TextBox(x, y, x + ww, y + hh, confidence=0.5, source="mser"))
    return boxes


# ────── Public API ──────


def detect_text_regions(image_path: str | np.ndarray, *, backend: Optional[str] = None) -> tuple[list[TextBox], str]:
    """이미지에서 텍스트 박스 검출.

    Args:
        image_path: 파일 경로 또는 BGR ndarray
        backend: "craft" | "mser" | None (자동)

    Returns:
        (boxes, used_backend)
    """
    if isinstance(image_path, np.ndarray):
        img = image_path
    else:
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"failed to read image: {image_path}")

    chosen = backend or ("craft" if _craft_available() else "mser")
    try:
        if chosen == "craft":
            return _detect_craft(img), "craft"
    except Exception:
        chosen = "mser"
    return _detect_mser(img), "mser"


def find_small_text_regions(image_path: str | np.ndarray, *, max_char_height: int = 22) -> list[TextBox]:
    """전체 검출 결과에서 글자 높이가 임계값 미만인 박스만 반환.

    SR/zoom-in 후처리 후보 영역 추리기.
    """
    boxes, _ = detect_text_regions(image_path)
    return [b for b in boxes if b.h <= max_char_height]


def backend_status() -> dict:
    return {
        "craft": {
            "available": _craft_available(),
            "weight": str(CRAFT_WEIGHT),
            "weight_exists": CRAFT_WEIGHT.exists(),
        },
        "mser": {"available": True, "note": "OpenCV 내장, 폴백"},
    }
