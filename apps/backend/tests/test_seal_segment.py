"""Phase 4 도장/서명 매처 + Phase 2-C 혼합 문서 분리 테스트."""

import io
import asyncio
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from app.core.seal_signature_matcher import SealLibrary, _ahash, _hash_similarity, verify_elements


def _make_image(color=(255, 0, 0), size=(64, 64)) -> Image.Image:
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, size[0] - 4, size[1] - 4), outline=color, width=6)
    return img


@pytest.mark.unit
def test_ahash_identical_images_perfect_match():
    a = _make_image()
    h = _ahash(a, 8)
    assert _hash_similarity(h, h, 64) == 1.0


@pytest.mark.unit
def test_ahash_similar_images_high_score():
    a = _make_image(color=(255, 0, 0))
    b = _make_image(color=(255, 0, 0), size=(70, 70))  # 살짝 다른 크기
    sim = _hash_similarity(_ahash(a), _ahash(b), 64)
    assert sim > 0.85


@pytest.mark.unit
def test_ahash_different_images_low_score():
    a = _make_image(color=(255, 0, 0))
    b = Image.new("RGB", (64, 64), "black")
    sim = _hash_similarity(_ahash(a), _ahash(b), 64)
    assert sim < 0.6


@pytest.mark.unit
def test_library_empty_returns_no_matches(tmp_path):
    lib = SealLibrary(library_dir=tmp_path)
    assert lib.is_empty()
    matches = lib.match(_make_image())
    assert matches == []


@pytest.mark.unit
def test_library_loads_and_matches(tmp_path):
    # 라이브러리에 도장 이미지 한 장 등록
    ref = _make_image(color=(255, 0, 0))
    ref.save(tmp_path / "woori_corp_seal.png")
    lib = SealLibrary(library_dir=tmp_path)
    assert not lib.is_empty()
    # 같은 이미지는 가장 높은 유사도
    matches = lib.match(_make_image(color=(255, 0, 0)), kind="stamp")
    assert matches
    assert matches[0]["reference"] == "woori_corp_seal"
    assert matches[0]["similarity"] >= 0.85
    assert matches[0]["decision"] == "match"


@pytest.mark.unit
def test_verify_elements_with_empty_library(tmp_path, monkeypatch):
    import app.core.seal_signature_matcher as m

    # 라이브러리(빈) 와 페이지 디렉토리 분리
    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    monkeypatch.setattr(m, "_library", None)
    monkeypatch.setattr(m, "DEFAULT_LIBRARY_DIR", lib_dir)

    page_path = tmp_path / "page.png"
    Image.new("RGB", (200, 200), "white").save(page_path)

    elements = {
        "stamps": [{"bbox": [10, 10, 80, 80]}],
        "signatures": [],
        "tables": [],
    }
    result = verify_elements(elements, str(page_path))
    assert result["stamps"][0]["matches"] == []
    assert result["stamps"][0]["library_empty"] is True


@pytest.mark.unit
def test_verify_elements_finds_match(tmp_path, monkeypatch):
    import app.core.seal_signature_matcher as m

    lib_dir = tmp_path / "lib"
    lib_dir.mkdir()
    seal_img = _make_image(color=(255, 0, 0))
    seal_img.save(lib_dir / "woori_corp_seal.png")
    monkeypatch.setattr(m, "_library", None)
    monkeypatch.setattr(m, "DEFAULT_LIBRARY_DIR", lib_dir)

    page = Image.new("RGB", (300, 300), "white")
    page.paste(seal_img.resize((80, 80)), (50, 50))
    page_path = tmp_path / "page.png"
    page.save(page_path)

    elements = {
        "stamps": [{"bbox": [50, 50, 130, 130]}],
        "signatures": [],
        "tables": [],
    }
    result = verify_elements(elements, str(page_path))
    matches = result["stamps"][0]["matches"]
    assert matches
    assert matches[0]["reference"] == "woori_corp_seal"
    assert matches[0]["similarity"] > 0.7


# ---------- 혼합 문서 분리 ----------

from app.core.document_segmenter import segment_documents


class _FakeClassifyResults:
    """document_classifier.classify_document 를 monkey-patch 하기 위한 헬퍼."""
    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.calls = 0

    async def __call__(self, image_path, **kwargs):
        idx = self.calls
        self.calls += 1
        return {
            "document_type": self.sequence[idx],
            "raw_response": self.sequence[idx],
            "processing_time_ms": 100,
        }


@pytest.mark.unit
def test_segmenter_groups_consecutive_same_types(monkeypatch):
    import app.core.document_segmenter as seg
    fake = _FakeClassifyResults(["merchant_application", "merchant_application", "id_card", "bank_book"])
    monkeypatch.setattr(seg, "classify_document", fake)
    result = asyncio.run(segment_documents([f"p{i}.png" for i in range(4)]))
    assert len(result) == 3
    assert result[0]["document_type"] == "merchant_application"
    assert result[0]["pages"] == [1, 2]
    assert result[1]["document_type"] == "id_card"
    assert result[1]["pages"] == [3]
    assert result[2]["document_type"] == "bank_book"


@pytest.mark.unit
def test_segmenter_absorbs_single_freeform_between_same_types(monkeypatch):
    # [A, freeform, A] → [A, A, A] 한 segment 로 합쳐짐
    import app.core.document_segmenter as seg
    fake = _FakeClassifyResults(["merchant_application", "freeform", "merchant_application"])
    monkeypatch.setattr(seg, "classify_document", fake)
    result = asyncio.run(segment_documents([f"p{i}.png" for i in range(3)]))
    assert len(result) == 1
    assert result[0]["page_count"] == 3
    assert result[0]["pages"] == [1, 2, 3]


@pytest.mark.unit
def test_segmenter_empty_input():
    assert asyncio.run(segment_documents([])) == []


@pytest.mark.unit
def test_segmenter_handles_classify_failure(monkeypatch):
    import app.core.document_segmenter as seg

    async def fail(_path, **_kw):
        raise RuntimeError("vLLM down")

    monkeypatch.setattr(seg, "classify_document", fail)
    result = asyncio.run(segment_documents(["p1.png"]))
    # 실패해도 freeform 으로 폴백
    assert len(result) == 1
    assert result[0]["document_type"] == "freeform"
