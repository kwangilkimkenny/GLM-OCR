"""HwpxConverter 단위 테스트.

Node.js / hwpx-cli 가 없이도 동작하도록 subprocess 와 PDFConverter 를 mock.
실제 통합 테스트는 별도 (`tests/fixtures/sample.hwpx` 와 npm ci 가 끝난 환경).

NOTE: pytest-asyncio 가 깔려 있지 않아 `asyncio.run()` 으로 직접 구동한다.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.utils.converters.exceptions import (
    ConversionFailedError,
    ConversionTimeoutError,
)
from app.utils.converters.hwpx import HwpxConverter


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if asyncio._get_running_loop() else asyncio.run(coro)


@pytest.fixture
def fake_hwpx_file(tmp_path):
    p = tmp_path / "fake.hwpx"
    # 진짜 HWPX 가 아니어도 됨 — CLI 호출을 mock 하므로
    p.write_bytes(b"PK\x03\x04fake hwpx content")
    return p


@pytest.fixture
def fake_runner_dir(tmp_path):
    """가짜 hwpx-cli 가 존재하는 runner 디렉토리 (validate 통과용)."""
    runner = tmp_path / "runner"
    cli = runner / "node_modules" / "open-hangul-ai" / "bin"
    cli.mkdir(parents=True)
    (cli / "hwpx-cli.mjs").write_text("// stub")
    return runner


# ---------- validate ----------


def test_validate_fails_when_cli_missing(tmp_path, fake_hwpx_file):
    runner = tmp_path / "no_runner"
    runner.mkdir()
    conv = HwpxConverter(runner_dir=str(runner))
    assert asyncio.run(conv.validate(str(fake_hwpx_file))) is False


def test_validate_fails_for_wrong_extension(tmp_path, fake_runner_dir):
    not_hwpx = tmp_path / "x.pdf"
    not_hwpx.write_bytes(b"%PDF")
    conv = HwpxConverter(runner_dir=str(fake_runner_dir))
    assert asyncio.run(conv.validate(str(not_hwpx))) is False


def test_validate_fails_for_empty_file(tmp_path, fake_runner_dir):
    empty = tmp_path / "empty.hwpx"
    empty.write_bytes(b"")
    conv = HwpxConverter(runner_dir=str(fake_runner_dir))
    assert asyncio.run(conv.validate(str(empty))) is False


def test_validate_passes(fake_hwpx_file, fake_runner_dir):
    conv = HwpxConverter(runner_dir=str(fake_runner_dir))
    assert asyncio.run(conv.validate(str(fake_hwpx_file))) is True


# ---------- _run_cli ----------


class _FakeProc:
    def __init__(self, rc=0, stdout=b"", stderr=b""):
        self.returncode = rc
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self):
        return self._stdout, self._stderr

    def kill(self):
        pass


def test_run_cli_translates_encryption_error(fake_runner_dir, fake_hwpx_file):
    conv = HwpxConverter(runner_dir=str(fake_runner_dir))
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(
        return_value=_FakeProc(rc=2, stderr=b"Error: file is encrypted (PBKDF2)"),
    )):
        with pytest.raises(ConversionFailedError, match="암호화"):
            asyncio.run(conv._run_cli(["info", str(fake_hwpx_file)], timeout=5))


def test_run_cli_generic_failure(fake_runner_dir, fake_hwpx_file):
    conv = HwpxConverter(runner_dir=str(fake_runner_dir))
    with patch("asyncio.create_subprocess_exec", new=AsyncMock(
        return_value=_FakeProc(rc=1, stderr=b"unexpected error here"),
    )):
        with pytest.raises(ConversionFailedError, match="hwpx-cli failed"):
            asyncio.run(conv._run_cli(["info", str(fake_hwpx_file)], timeout=5))


def test_run_cli_timeout(fake_runner_dir, fake_hwpx_file):
    conv = HwpxConverter(runner_dir=str(fake_runner_dir))

    class _HangingProc(_FakeProc):
        async def communicate(self):
            await asyncio.sleep(3600)
            return b"", b""

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=_HangingProc())):
        with pytest.raises(ConversionTimeoutError):
            asyncio.run(conv._run_cli(["info", str(fake_hwpx_file)], timeout=0.1))


# ---------- convert (high-level) ----------


def test_convert_happy_path(fake_runner_dir, fake_hwpx_file, tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    structured_json = {
        "sections": [
            {"elements": [{"type": "paragraph", "runs": [{"text": "안녕"}]}]}
        ],
        "images": {},
    }

    async def fake_run_cli(self, args, *, timeout, capture_stdout=False):
        if args[0] == "info":
            return '{"pages": 1}'
        if "--to" in args and "json" in args:
            out_idx = args.index("-o") + 1
            with open(args[out_idx], "w", encoding="utf-8") as f:
                json.dump(structured_json, f)
            return ""
        if "--to" in args and "pdf" in args:
            out_idx = args.index("-o") + 1
            Path(args[out_idx]).write_bytes(b"%PDF-1.4\nfake")
            return ""
        return ""

    async def fake_pdf_convert(self, file_path, output_dir, **kw):
        png_path = Path(output_dir) / "page_1.png"
        png_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")
        return {
            "output_files": [str(png_path)],
            "page_count": 1,
            "metadata": {"page_size": {"width": 595, "height": 842}},
        }

    monkeypatch.setattr(HwpxConverter, "_run_cli", fake_run_cli)
    monkeypatch.setattr("app.utils.converters.pdf.PDFConverter.convert", fake_pdf_convert)

    conv = HwpxConverter(runner_dir=str(fake_runner_dir))
    result = asyncio.run(conv.convert(str(fake_hwpx_file), str(out_dir)))

    assert result["page_count"] == 1
    assert len(result["output_files"]) == 1
    assert result["metadata"]["source_format"] == "hwpx"
    assert "hwpx_structured" in result["metadata"]
    assert result["metadata"]["hwpx_structured"] == structured_json
    assert "hwpx_parse_ms" in result["metadata"]
    assert "hwpx_pdf_ms" in result["metadata"]


def test_convert_respects_feature_flag(fake_runner_dir, fake_hwpx_file, tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    monkeypatch.setattr("app.utils.config.settings.HWPX_NATIVE_PATH", False)
    conv = HwpxConverter(runner_dir=str(fake_runner_dir))
    with pytest.raises(ConversionFailedError, match="HWPX native path is disabled"):
        asyncio.run(conv.convert(str(fake_hwpx_file), str(out_dir)))
