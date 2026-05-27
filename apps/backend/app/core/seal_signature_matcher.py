"""도장/서명 유사도 매처 (Phase 4).

PP-Layout 이 잡은 stamp/signature 영역을 원본 이미지에서 잘라,
사전 등록된 도장·서명 라이브러리와 perceptual hash 로 유사도 비교한다.

External dependency 없이 8x8 평균 해시 (aHash) + 4x4 해상도 phash 변형 두 가지
신호를 모두 사용. 해밍 거리 → 유사도 점수.

사전 라이브러리 구조:
    apps/backend/data/seal_library/
        woori_corp_seal.png
        ceo_signature_kim.png
        ...
파일명에서 _ 앞부분이 "kind" (seal/signature), 뒷부분이 reference name.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image


# 사전 등록 디렉토리 (없으면 빈 라이브러리로 동작)
DEFAULT_LIBRARY_DIR = Path(
    os.environ.get(
        "WOORI_SEAL_LIBRARY",
        os.path.join(os.path.dirname(__file__), "..", "..", "data", "seal_library"),
    )
).resolve()


def _ahash(img: Image.Image, size: int = 8) -> int:
    """평균 해시 — size*size 그레이스케일 → 평균 비교 → 비트마스크.

    크기 size**2 비트의 정수 hash. 해밍 거리로 유사도 측정.
    """
    g = img.convert("L").resize((size, size), Image.LANCZOS)
    arr = np.asarray(g, dtype=np.float32)
    mean = arr.mean()
    bits = (arr >= mean).flatten()
    h = 0
    for b in bits:
        h = (h << 1) | int(b)
    return h


def _hamming(a: int, b: int, bits: int) -> int:
    return bin(a ^ b).count("1")


def _hash_similarity(a: int, b: int, bits: int) -> float:
    """0~1. 비트가 일치할수록 1에 가까움."""
    return 1.0 - _hamming(a, b, bits) / bits


class SealLibrary:
    """디스크의 도장/서명 사전 라이브러리. 첫 호출 시 lazy load."""

    def __init__(self, library_dir: Optional[Path] = None):
        # default 는 호출 시점의 모듈 전역값 (monkeypatch 가능하도록)
        self.library_dir = Path(library_dir) if library_dir is not None else DEFAULT_LIBRARY_DIR
        self._refs: list[dict] = []
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.library_dir.exists():
            return
        for p in sorted(self.library_dir.glob("*")):
            if p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
                continue
            try:
                img = Image.open(p).convert("RGB")
                name = p.stem
                # 파일명 prefix 로 kind 추정
                lower = name.lower()
                if any(k in lower for k in ("seal", "stamp", "도장", "인감")):
                    kind = "stamp"
                elif any(k in lower for k in ("signature", "sign", "서명")):
                    kind = "signature"
                else:
                    kind = "any"
                self._refs.append(
                    {
                        "name": name,
                        "kind": kind,
                        "path": str(p),
                        "ahash_8": _ahash(img, 8),
                        "ahash_16": _ahash(img, 16),
                    }
                )
            except Exception:
                continue

    def references(self) -> list[dict]:
        self._ensure_loaded()
        return list(self._refs)

    def is_empty(self) -> bool:
        self._ensure_loaded()
        return len(self._refs) == 0

    def match(
        self,
        crop: Image.Image,
        *,
        kind: Optional[str] = None,
        threshold: float = 0.65,
        top_k: int = 3,
    ) -> list[dict]:
        """crop 과 라이브러리의 같은 kind(또는 any) 항목들 비교.

        Returns:
            [{reference, kind, similarity, similarity_hi, decision}, ...]  top_k 개
        """
        self._ensure_loaded()
        if not self._refs:
            return []
        ah8 = _ahash(crop, 8)
        ah16 = _ahash(crop, 16)
        scored = []
        for ref in self._refs:
            if kind and ref["kind"] not in {kind, "any"}:
                continue
            s8 = _hash_similarity(ah8, ref["ahash_8"], 64)
            s16 = _hash_similarity(ah16, ref["ahash_16"], 256)
            # 가중 결합 — 해상도 높은 hash 가 더 정확
            combined = 0.4 * s8 + 0.6 * s16
            scored.append(
                {
                    "reference": ref["name"],
                    "kind": ref["kind"],
                    "similarity": round(combined, 4),
                    "similarity_lo": round(s8, 4),
                    "similarity_hi": round(s16, 4),
                    "decision": "match" if combined >= threshold else "no_match",
                }
            )
        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:top_k]


# 모듈 레벨 싱글톤
_library: Optional[SealLibrary] = None


def get_library() -> SealLibrary:
    global _library
    if _library is None:
        _library = SealLibrary()
    return _library


def verify_elements(
    elements: dict[str, list[dict]],
    image_path: str,
) -> dict[str, list[dict]]:
    """`doc_elements` (stamps/signatures/tables) 에 매칭 결과를 in-place 추가.

    각 element 에 `matches` 필드 추가. 라이브러리가 비어 있으면
    matches=[] + library_empty=True 로 알린다.
    """
    lib = get_library()
    if lib.is_empty():
        for kind in ("stamps", "signatures"):
            for el in elements.get(kind, []):
                el["matches"] = []
                el["library_empty"] = True
        return elements
    try:
        full = Image.open(image_path).convert("RGB")
    except Exception:
        return elements
    for kind_key, kind in (("stamps", "stamp"), ("signatures", "signature")):
        for el in elements.get(kind_key, []) or []:
            bbox = el.get("bbox")
            if not bbox or len(bbox) != 4:
                el["matches"] = []
                continue
            x0, y0, x1, y1 = [int(v) for v in bbox]
            x0 = max(0, x0); y0 = max(0, y0)
            x1 = min(full.width, x1); y1 = min(full.height, y1)
            if x1 - x0 < 4 or y1 - y0 < 4:
                el["matches"] = []
                continue
            crop = full.crop((x0, y0, x1, y1))
            el["matches"] = lib.match(crop, kind=kind)
    return elements
