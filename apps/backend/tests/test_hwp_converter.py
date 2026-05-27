"""HwpConverter 단위 테스트.

실제 LibreOffice 없이 subprocess 와 HwpxConverter/PDFConverter 를 mock.
NOTE: pytest-asyncio 가 깔려 있지 않아 `asyncio.run()` 으로 직접 구동한다.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.utils.converters.exceptions import ConversionFailedError
from app.utils.converters.hwp import HwpConverter


@pytest.fixture
def fake_hwp_file(tmp_path):
    p = tmp_path / "fake.hwp"
    # CFB OLE magic — HwpConverter 는 확장자만 보지만 진짜처럼 보이게
    p.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 1024)
    return p


def test_validate_rejects_wrong_extension(tmp_path):
    not_hwp = tmp_path / "x.pdf"
    not_hwp.write_bytes(b"%PDF")
    assert asyncio.run(HwpConverter().validate(str(not_hwp))) is False


def test_validate_rejects_empty(tmp_path):
    empty = tmp_path / "empty.hwp"
    empty.write_bytes(b"")
    assert asyncio.run(HwpConverter().validate(str(empty))) is False


def test_validate_passes(fake_hwp_file):
    assert asyncio.run(HwpConverter().validate(str(fake_hwp_file))) is True


def test_convert_prefers_hwpx_path(fake_hwp_file, tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    conv = HwpConverter()

    async def fake_libreoffice(self, target_format, file_path, outdir, timeout):
        if target_format == "hwpx":
            (Path(outdir) / "converted.hwpx").write_bytes(b"PK\x03\x04fake")
            return True, ""
        return False, ""

    async def fake_hwpx_convert(self, file_path, output_dir, **kw):
        return {
            "output_files": [str(Path(output_dir) / "page_1.png")],
            "page_count": 1,
            "metadata": {"source_format": "hwpx", "hwpx_structured": {"sections": []}},
        }

    monkeypatch.setattr(HwpConverter, "_libreoffice", fake_libreoffice)
    monkeypatch.setattr("app.utils.converters.hwpx.HwpxConverter.convert", fake_hwpx_convert)

    result = asyncio.run(conv.convert(str(fake_hwp_file), str(out_dir)))
    assert result["metadata"]["source_format"] == "hwp_via_libreoffice_to_hwpx"
    assert "libreoffice_to_hwpx_ms" in result["metadata"]


def test_convert_falls_back_to_pdf(fake_hwp_file, tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    conv = HwpConverter()

    async def fake_libreoffice(self, target_format, file_path, outdir, timeout):
        if target_format == "hwpx":
            return False, "Filter not found for type hwpx"
        if target_format == "pdf":
            (Path(outdir) / "converted.pdf").write_bytes(b"%PDF-1.4\nfake")
            return True, ""
        return False, ""

    async def fake_pdf_convert(self, file_path, output_dir, **kw):
        png_path = Path(output_dir) / "page_1.png"
        png_path.write_bytes(b"\x89PNG")
        return {
            "output_files": [str(png_path)],
            "page_count": 1,
            "metadata": {},
        }

    monkeypatch.setattr(HwpConverter, "_libreoffice", fake_libreoffice)
    monkeypatch.setattr("app.utils.converters.pdf.PDFConverter.convert", fake_pdf_convert)

    result = asyncio.run(conv.convert(str(fake_hwp_file), str(out_dir)))
    assert result["metadata"]["source_format"] == "hwp_via_libreoffice_to_pdf"


def test_convert_both_fail_raises_korean_error(fake_hwp_file, tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    conv = HwpConverter()

    async def fake_libreoffice(self, target_format, file_path, outdir, timeout):
        return False, "encrypted document"

    monkeypatch.setattr(HwpConverter, "_libreoffice", fake_libreoffice)

    with pytest.raises(ConversionFailedError, match="HWP 변환에 실패"):
        asyncio.run(conv.convert(str(fake_hwp_file), str(out_dir)))


def test_convert_falls_back_when_hwpx_path_explodes_after_export(
    fake_hwp_file, tmp_path, monkeypatch
):
    """HWPX export 는 성공했는데 HwpxConverter 가 그 결과를 못 파싱하는 케이스 — PDF 로 폴백."""
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    conv = HwpConverter()

    async def fake_libreoffice(self, target_format, file_path, outdir, timeout):
        if target_format == "hwpx":
            (Path(outdir) / "converted.hwpx").write_bytes(b"corrupt")
            return True, ""
        if target_format == "pdf":
            (Path(outdir) / "converted.pdf").write_bytes(b"%PDF-1.4\nok")
            return True, ""
        return False, ""

    async def fake_hwpx_convert(self, file_path, output_dir, **kw):
        raise ConversionFailedError("hwpx-cli failed")

    async def fake_pdf_convert(self, file_path, output_dir, **kw):
        return {
            "output_files": [str(Path(output_dir) / "page_1.png")],
            "page_count": 1,
            "metadata": {},
        }

    monkeypatch.setattr(HwpConverter, "_libreoffice", fake_libreoffice)
    monkeypatch.setattr("app.utils.converters.hwpx.HwpxConverter.convert", fake_hwpx_convert)
    monkeypatch.setattr("app.utils.converters.pdf.PDFConverter.convert", fake_pdf_convert)

    result = asyncio.run(conv.convert(str(fake_hwp_file), str(out_dir)))
    assert result["metadata"]["source_format"] == "hwp_via_libreoffice_to_pdf"
