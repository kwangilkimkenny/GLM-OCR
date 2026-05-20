"""Image preprocessing for GLM-OCR.

Pipeline (in order):
  1. Load (BGR)
  2. Convert to grayscale for analysis (keep color copy for output)
  3. Deskew (estimate angle via minAreaRect on text mask)
  4. Denoise (fastNlMeansDenoising on grayscale, mild)
  5. CLAHE contrast enhancement
  6. Unsharp mask
  7. Optional adaptive threshold (--binarize)
  8. Save

CLI:
  python preprocess.py INPUT OUTPUT [--binarize] [--no-deskew] [--target-width N]
  python preprocess.py INPUT_DIR OUTPUT_DIR [...]   # batch mode

Examples:
  python preprocess.py test/form.png out/form.png
  python preprocess.py test/ out_preproc/ --target-width 2400
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import cv2
import numpy as np


IMG_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def deskew(gray: np.ndarray) -> tuple[np.ndarray, float]:
    """Estimate skew angle from dark pixels and rotate to correct it.

    Returns (rotated_image_or_input_unchanged, angle_in_degrees).
    If |angle| < 0.3°, returns the original to avoid resampling artefacts.
    """
    inv = cv2.bitwise_not(gray)
    _, thresh = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(thresh > 0))
    if coords.size == 0:
        return gray, 0.0
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    if abs(angle) < 0.3:
        return gray, angle
    h, w = gray.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rotated = cv2.warpAffine(
        gray, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )
    return rotated, angle


def unsharp_mask(img: np.ndarray, ksize: int = 5, amount: float = 1.2) -> np.ndarray:
    blurred = cv2.GaussianBlur(img, (ksize, ksize), 0)
    sharp = cv2.addWeighted(img, 1 + amount, blurred, -amount, 0)
    return sharp


def preprocess(
    img: np.ndarray,
    do_deskew: bool = True,
    binarize: bool = False,
    target_width: int | None = None,
) -> tuple[np.ndarray, dict]:
    info: dict = {}
    h0, w0 = img.shape[:2]
    info["orig_size"] = (w0, h0)

    if target_width and w0 != target_width:
        scale = target_width / w0
        img = cv2.resize(
            img, (target_width, int(h0 * scale)), interpolation=cv2.INTER_CUBIC
        )
        info["resized_to"] = (target_width, int(h0 * scale))

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    if do_deskew:
        gray, angle = deskew(gray)
        info["deskew_angle"] = round(float(angle), 3)

    gray = cv2.fastNlMeansDenoising(gray, h=10, templateWindowSize=7, searchWindowSize=21)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    gray = clahe.apply(gray)
    gray = unsharp_mask(gray, ksize=5, amount=1.0)

    if binarize:
        gray = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 12
        )
        info["binarized"] = True

    out = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return out, info


def iter_images(path: Path):
    if path.is_file():
        yield path
        return
    for p in sorted(path.iterdir()):
        if p.suffix.lower() in IMG_EXTS:
            yield p


def main():
    ap = argparse.ArgumentParser(description="GLM-OCR image preprocessor")
    ap.add_argument("input", type=Path, help="input file or directory")
    ap.add_argument("output", type=Path, help="output file (single) or directory (batch)")
    ap.add_argument("--no-deskew", action="store_true")
    ap.add_argument("--binarize", action="store_true", help="adaptive threshold (B/W output)")
    ap.add_argument(
        "--target-width", type=int, default=None,
        help="resize so width equals this many pixels (preserve aspect ratio)"
    )
    args = ap.parse_args()

    in_path: Path = args.input
    out_path: Path = args.output

    if not in_path.exists():
        print(f"input not found: {in_path}", file=sys.stderr)
        sys.exit(2)

    batch = in_path.is_dir()
    if batch:
        out_path.mkdir(parents=True, exist_ok=True)
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)

    for src in iter_images(in_path):
        img = cv2.imread(str(src))
        if img is None:
            print(f"skip (not an image): {src}", file=sys.stderr)
            continue
        processed, info = preprocess(
            img,
            do_deskew=not args.no_deskew,
            binarize=args.binarize,
            target_width=args.target_width,
        )
        dst = out_path / src.name if batch else out_path
        cv2.imwrite(str(dst), processed)
        print(f"{src.name} -> {dst}  {info}")


if __name__ == "__main__":
    main()
