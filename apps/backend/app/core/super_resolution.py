"""Super-Resolution 멀티 백엔드 (Phase 6-B).

저해상도 글자를 OCR 친화 형태로 복원한다.
백엔드 우선순위 (가능한 것부터 자동 선택):
    1. **realesrgan** — Real-ESRGAN RRDBNet (torch). 가중치 `models/sr/RealESRGAN_x4plus.pth`
    2. **opencv-dnn-superres** — OpenCV contrib (`EDSR_x4.pb`, `ESPCN_x4.pb`)
    3. **lanczos-sharpen** (항상 사용 가능) — PIL LANCZOS + unsharp mask. 가성비 폴백.

가중치 파일 경로:
    `<repo-root>/apps/backend/data/sr_models/`
    또는 환경변수 `WOORI_SR_MODELS_DIR`

가중치가 없으면 자동으로 lanczos-sharpen 으로 폴백 (서비스가 깨지지 않음).
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PIL import Image, ImageFilter


# ────── 백엔드 등록 ──────
DEFAULT_SR_DIR = Path(__file__).resolve().parents[2] / "data" / "sr_models"
SR_DIR = Path(os.environ.get("WOORI_SR_MODELS_DIR") or DEFAULT_SR_DIR)

REALESRGAN_WEIGHT = SR_DIR / "RealESRGAN_x4plus.pth"
EDSR_WEIGHT = SR_DIR / "EDSR_x4.pb"
ESPCN_WEIGHT = SR_DIR / "ESPCN_x4.pb"


@dataclass
class SrBackendInfo:
    name: str
    scale: int
    available: bool
    note: str = ""


_BACKEND_LOCK = threading.Lock()
_BACKENDS_CACHE: Optional[list[SrBackendInfo]] = None
_MODEL_CACHE: dict[str, object] = {}


def list_backends() -> list[SrBackendInfo]:
    """현재 사용 가능한 SR 백엔드 목록 (캐시됨)."""
    global _BACKENDS_CACHE
    if _BACKENDS_CACHE is not None:
        return _BACKENDS_CACHE
    with _BACKEND_LOCK:
        if _BACKENDS_CACHE is not None:
            return _BACKENDS_CACHE
        backends: list[SrBackendInfo] = []

        # 1. Real-ESRGAN
        try:
            import torch  # noqa: F401

            if REALESRGAN_WEIGHT.exists():
                backends.append(
                    SrBackendInfo("realesrgan", scale=4, available=True, note=str(REALESRGAN_WEIGHT))
                )
            else:
                backends.append(
                    SrBackendInfo(
                        "realesrgan",
                        scale=4,
                        available=False,
                        note=f"weight missing: {REALESRGAN_WEIGHT}",
                    )
                )
        except ImportError:
            backends.append(SrBackendInfo("realesrgan", 4, False, "torch not installed"))

        # 2. OpenCV dnn_superres
        if hasattr(cv2, "dnn_superres"):
            available = EDSR_WEIGHT.exists() or ESPCN_WEIGHT.exists()
            backends.append(
                SrBackendInfo(
                    "opencv-dnn-superres",
                    scale=4,
                    available=available,
                    note=f"EDSR={EDSR_WEIGHT.exists()} ESPCN={ESPCN_WEIGHT.exists()}",
                )
            )
        else:
            backends.append(
                SrBackendInfo("opencv-dnn-superres", 4, False, "cv2.dnn_superres 모듈 없음 (contrib 필요)")
            )

        # 3. Lanczos-sharpen — 항상 가능
        backends.append(SrBackendInfo("lanczos-sharpen", 4, True, "PIL LANCZOS + unsharp"))

        _BACKENDS_CACHE = backends
        return backends


def select_backend(preferred: Optional[str] = None) -> SrBackendInfo:
    """우선순위 따라 사용 가능한 백엔드 1개 선택."""
    backends = list_backends()
    available = [b for b in backends if b.available]
    if preferred:
        for b in available:
            if b.name == preferred:
                return b
    if available:
        return available[0]
    # 절대 일어나면 안 되지만 안전망 — lanczos 는 항상 available
    return SrBackendInfo("lanczos-sharpen", 4, True, "fallback")


# ────── 백엔드별 구현 ──────


def _upscale_lanczos_sharpen(img_bgr: np.ndarray, scale: float) -> np.ndarray:
    """PIL LANCZOS + 가벼운 unsharp mask. 항상 동작."""
    h, w = img_bgr.shape[:2]
    new_w = int(round(w * scale))
    new_h = int(round(h * scale))
    pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    pil = pil.resize((new_w, new_h), Image.Resampling.LANCZOS)
    # 약한 unsharp — 큰 글자에는 아티팩트 가능하므로 텍스트 영역 두께에 맞춤
    pil = pil.filter(ImageFilter.UnsharpMask(radius=1.2, percent=110, threshold=2))
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def _upscale_opencv_dnn(img_bgr: np.ndarray, scale: int = 4) -> np.ndarray:
    """OpenCV contrib dnn_superres. ESPCN > EDSR 선호 (속도)."""
    import cv2 as _cv2  # type: ignore

    cache_key = f"opencv-dnn:{scale}"
    sr = _MODEL_CACHE.get(cache_key)
    if sr is None:
        with _BACKEND_LOCK:
            sr = _MODEL_CACHE.get(cache_key)
            if sr is None:
                sr = _cv2.dnn_superres.DnnSuperResImpl_create()  # type: ignore[attr-defined]
                if ESPCN_WEIGHT.exists():
                    sr.readModel(str(ESPCN_WEIGHT))
                    sr.setModel("espcn", scale)
                elif EDSR_WEIGHT.exists():
                    sr.readModel(str(EDSR_WEIGHT))
                    sr.setModel("edsr", scale)
                else:
                    raise FileNotFoundError("no opencv-dnn SR weight available")
                _MODEL_CACHE[cache_key] = sr
    return sr.upsample(img_bgr)


def _upscale_realesrgan(img_bgr: np.ndarray, scale: int = 4) -> np.ndarray:
    """Real-ESRGAN RRDBNet via torch. 가중치 필요.

    공식 구현(`basicsr.archs.rrdbnet_arch.RRDBNet` 또는 `realesrgan.RealESRGANer`)에
    의존하지 않고, 가중치만 있으면 동작하는 최소 구현.
    """
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    cache_key = f"realesrgan:{scale}"
    model = _MODEL_CACHE.get(cache_key)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    if model is None:
        with _BACKEND_LOCK:
            model = _MODEL_CACHE.get(cache_key)
            if model is None:
                # RRDBNet 최소 구현
                model = _build_rrdbnet(scale=scale)
                state = torch.load(str(REALESRGAN_WEIGHT), map_location="cpu")
                # 공식 체크포인트 키 처리
                if "params_ema" in state:
                    state = state["params_ema"]
                elif "params" in state:
                    state = state["params"]
                model.load_state_dict(state, strict=False)
                model.eval()
                model = model.to(device)
                _MODEL_CACHE[cache_key] = model

    # BGR → RGB → tensor
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    inp = torch.from_numpy(rgb.astype(np.float32) / 255.0).permute(2, 0, 1).unsqueeze(0)
    inp = inp.to(device)
    with torch.no_grad():
        out = model(inp)
    out = out.squeeze(0).clamp_(0, 1).permute(1, 2, 0).cpu().numpy()
    out = (out * 255.0).round().astype(np.uint8)
    return cv2.cvtColor(out, cv2.COLOR_RGB2BGR)


def _build_rrdbnet(scale: int = 4):
    """Real-ESRGAN RRDBNet 최소 구현. basicsr 미설치 환경에서도 동작."""
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    class ResidualDenseBlock(nn.Module):
        def __init__(self, num_feat: int = 64, num_grow_ch: int = 32):
            super().__init__()
            self.conv1 = nn.Conv2d(num_feat, num_grow_ch, 3, 1, 1)
            self.conv2 = nn.Conv2d(num_feat + num_grow_ch, num_grow_ch, 3, 1, 1)
            self.conv3 = nn.Conv2d(num_feat + 2 * num_grow_ch, num_grow_ch, 3, 1, 1)
            self.conv4 = nn.Conv2d(num_feat + 3 * num_grow_ch, num_grow_ch, 3, 1, 1)
            self.conv5 = nn.Conv2d(num_feat + 4 * num_grow_ch, num_feat, 3, 1, 1)
            self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

        def forward(self, x):
            x1 = self.lrelu(self.conv1(x))
            x2 = self.lrelu(self.conv2(torch.cat([x, x1], 1)))
            x3 = self.lrelu(self.conv3(torch.cat([x, x1, x2], 1)))
            x4 = self.lrelu(self.conv4(torch.cat([x, x1, x2, x3], 1)))
            x5 = self.conv5(torch.cat([x, x1, x2, x3, x4], 1))
            return x5 * 0.2 + x

    class RRDB(nn.Module):
        def __init__(self, num_feat=64, num_grow_ch=32):
            super().__init__()
            self.rdb1 = ResidualDenseBlock(num_feat, num_grow_ch)
            self.rdb2 = ResidualDenseBlock(num_feat, num_grow_ch)
            self.rdb3 = ResidualDenseBlock(num_feat, num_grow_ch)

        def forward(self, x):
            out = self.rdb1(x)
            out = self.rdb2(out)
            out = self.rdb3(out)
            return out * 0.2 + x

    class RRDBNet(nn.Module):
        def __init__(self, num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4):
            super().__init__()
            self.scale = scale
            self.conv_first = nn.Conv2d(num_in_ch, num_feat, 3, 1, 1)
            self.body = nn.Sequential(*[RRDB(num_feat, num_grow_ch) for _ in range(num_block)])
            self.conv_body = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_up1 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_up2 = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_hr = nn.Conv2d(num_feat, num_feat, 3, 1, 1)
            self.conv_last = nn.Conv2d(num_feat, num_out_ch, 3, 1, 1)
            self.lrelu = nn.LeakyReLU(negative_slope=0.2, inplace=True)

        def forward(self, x):
            feat = self.conv_first(x)
            body_feat = self.conv_body(self.body(feat))
            feat = feat + body_feat
            feat = self.lrelu(self.conv_up1(F.interpolate(feat, scale_factor=2, mode="nearest")))
            feat = self.lrelu(self.conv_up2(F.interpolate(feat, scale_factor=2, mode="nearest")))
            out = self.conv_last(self.lrelu(self.conv_hr(feat)))
            return out

    return RRDBNet(scale=scale)


# ────── Public API ──────


def upscale(img_bgr: np.ndarray, scale: float, *, backend: Optional[str] = None) -> tuple[np.ndarray, str]:
    """이미지 업스케일. scale 이 1.0 이하면 그대로 반환.

    Returns:
        (출력 BGR, 사용된 백엔드 이름)
    """
    if scale <= 1.05:
        return img_bgr, "noop"

    chosen = select_backend(backend)
    try:
        if chosen.name == "realesrgan":
            # 모델은 4x 고정 → 후 LANCZOS 로 목표 비율에 맞춤
            out = _upscale_realesrgan(img_bgr, scale=4)
            target_w = int(img_bgr.shape[1] * scale)
            target_h = int(img_bgr.shape[0] * scale)
            if out.shape[1] != target_w or out.shape[0] != target_h:
                out = cv2.resize(out, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
            return out, "realesrgan"
        if chosen.name == "opencv-dnn-superres":
            out = _upscale_opencv_dnn(img_bgr, scale=4)
            target_w = int(img_bgr.shape[1] * scale)
            target_h = int(img_bgr.shape[0] * scale)
            if out.shape[1] != target_w or out.shape[0] != target_h:
                out = cv2.resize(out, (target_w, target_h), interpolation=cv2.INTER_LANCZOS4)
            return out, "opencv-dnn-superres"
    except Exception:
        # 모델 로드 / 추론 실패 → 안전 폴백
        pass

    return _upscale_lanczos_sharpen(img_bgr, scale), "lanczos-sharpen"


def upscale_file(input_path: str, output_path: str, scale: float, *, backend: Optional[str] = None) -> dict:
    """파일 in/out. info dict 반환."""
    img = cv2.imread(input_path)
    if img is None:
        raise ValueError(f"failed to read: {input_path}")
    out, used = upscale(img, scale, backend=backend)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(output_path, out)
    return {
        "input": input_path,
        "output": output_path,
        "scale": scale,
        "backend": used,
        "in_size": (img.shape[1], img.shape[0]),
        "out_size": (out.shape[1], out.shape[0]),
    }
