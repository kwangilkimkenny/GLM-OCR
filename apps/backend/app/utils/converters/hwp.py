"""HWP (한컴 바이너리 5.x) 변환기.

전략 (순서):
    1. LibreOffice headless 로 .hwp → .hwpx 변환 → HwpxConverter 위임 (구조 보존)
    2. 실패 시 .hwp → .pdf 폴백 → PDFConverter 위임 (구조 손실, OCR 경로)
    3. 둘 다 실패 → 명시적 한국어 에러

LibreOffice 동시성 충돌 회피를 위해 호출마다 `UserInstallation` 디렉토리를 격리.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.utils.config import settings
from app.utils.converters.base import BaseConverter
from app.utils.converters.exceptions import (
    ConversionFailedError,
    ConversionTimeoutError,
)
from app.utils.logger import logger


class HwpConverter(BaseConverter):
    """레거시 HWP → HWPX (선호) 또는 PDF (폴백) 변환기."""

    name = "hwp_converter"
    supported_extensions = {".hwp"}

    LIBREOFFICE_TIMEOUT_S = 180

    def __init__(self, libreoffice_cmd: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        # WordConverter 와 동일한 규칙: dev → soffice, prod → libreoffice
        self.libreoffice_cmd = libreoffice_cmd or (
            "soffice" if settings.environment == "development" else "libreoffice"
        )

    # ---------------------------------------------------------------- helpers

    async def _libreoffice(
        self,
        target_format: str,
        file_path: str,
        outdir: str,
        timeout: int,
    ) -> Tuple[bool, str]:
        """LibreOffice headless 변환 한 번 실행.

        Returns (success, stderr_text).
        """
        user_dir = Path(tempfile.gettempdir()) / f"lo-profile-{uuid.uuid4().hex}"
        user_dir.mkdir(parents=True, exist_ok=True)
        try:
            cmd = [
                self.libreoffice_cmd,
                f"-env:UserInstallation=file://{user_dir}",
                "--headless",
                "--convert-to",
                target_format,
                "--outdir",
                outdir,
                file_path,
            ]
            logger.info(f"libreoffice exec: {' '.join(cmd)}")
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except FileNotFoundError:
                return False, f"{self.libreoffice_cmd} not found on PATH"

            try:
                _, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                raise ConversionTimeoutError(
                    f"libreoffice --convert-to {target_format} timed out after {timeout}s"
                )

            stderr_text = stderr_b.decode("utf-8", errors="replace")
            if proc.returncode != 0:
                return False, stderr_text
            return True, stderr_text
        finally:
            shutil.rmtree(user_dir, ignore_errors=True)

    @staticmethod
    def _find_output(outdir: str, suffix: str) -> Optional[Path]:
        candidates = sorted(Path(outdir).glob(f"*{suffix}"))
        return candidates[0] if candidates else None

    @staticmethod
    def _cleanup_partial_hwpx_artifacts(output_dir: str) -> None:
        """E2: HwpxConverter 가 실패 직전까지 남긴 잔여물을 PDF 폴백 직전에 제거."""
        for name in ("hwpx_structured.json", "hwpx_preview.pdf"):
            p = Path(output_dir) / name
            try:
                if p.exists():
                    p.unlink()
            except OSError as e:
                logger.warning(f"cleanup_partial_hwpx_artifacts: failed to remove {p}: {e}")
        # page_*.png 는 PDFConverter 가 덮어쓰므로 굳이 지우지 않음 (오히려 IO 절약).

    # ---------------------------------------------------------------- public

    async def convert(
        self,
        file_path: str,
        output_dir: str,
        **kwargs,
    ) -> Dict[str, Any]:
        self.ensure_output_dir(output_dir)

        temp_root = tempfile.mkdtemp(prefix="hwp_convert_")
        try:
            # ----- 1차: HWP → HWPX
            ok = False
            stderr_hwpx = ""
            try:
                ok, stderr_hwpx = await self._libreoffice(
                    "hwpx", file_path, temp_root, self.LIBREOFFICE_TIMEOUT_S
                )
            except ConversionTimeoutError as e:
                logger.warning(f"HWPX export timeout, will try PDF fallback: {e}")

            hwpx_out = self._find_output(temp_root, ".hwpx") if ok else None
            if hwpx_out and hwpx_out.exists() and hwpx_out.stat().st_size > 0:
                from app.utils.converters import HwpxConverter

                t0 = time.monotonic()
                try:
                    result = await HwpxConverter().convert(
                        str(hwpx_out), output_dir, **kwargs
                    )
                    lo_ms = int((time.monotonic() - t0) * 1000)
                    md = result.setdefault("metadata", {})
                    md["source_format"] = "hwp_via_libreoffice_to_hwpx"
                    md["libreoffice_to_hwpx_ms"] = lo_ms
                    logger.info(
                        f"HWP via libreoffice→hwpx OK: file={Path(file_path).name} libreoffice_ms={lo_ms}"
                    )
                    return result
                except (ConversionFailedError, ConversionTimeoutError) as e:
                    # A3/C7: ConversionTimeoutError 도 동일하게 PDF 폴백 경로로 흘려보낸다.
                    logger.warning(
                        f"HWPX path failed after libreoffice export, falling back to PDF: "
                        f"{type(e).__name__}: {e}"
                    )
                    # E2: HwpxConverter 가 partial 출력 (hwpx_structured.json, hwpx_preview.pdf, page_*.png)
                    # 을 output_dir 에 남겼을 수 있다. PDF 폴백 전에 정리.
                    self._cleanup_partial_hwpx_artifacts(output_dir)

            if not ok:
                logger.info(
                    f"libreoffice hwpx export unavailable or failed; trying PDF. "
                    f"stderr={stderr_hwpx[-200:]!r}"
                )

            # ----- 2차: HWP → PDF
            ok_pdf, stderr_pdf = await self._libreoffice(
                "pdf", file_path, temp_root, self.LIBREOFFICE_TIMEOUT_S
            )
            pdf_out = self._find_output(temp_root, ".pdf") if ok_pdf else None
            if pdf_out and pdf_out.exists() and pdf_out.stat().st_size > 0:
                from app.utils.converters import PDFConverter

                pdf_conv = PDFConverter()
                result = await pdf_conv.convert(
                    str(pdf_out),
                    output_dir,
                    dpi=kwargs.get("dpi", 200),
                    format=kwargs.get("format", "png"),
                )
                md = result.setdefault("metadata", {})
                md["source_format"] = "hwp_via_libreoffice_to_pdf"
                md["source_file"] = file_path
                logger.info(
                    f"HWP via libreoffice→pdf OK (fallback): file={Path(file_path).name}"
                )
                return result

            preview = (stderr_pdf or stderr_hwpx or "")[-300:].strip()
            raise ConversionFailedError(
                "HWP 변환에 실패했습니다. 한컴 한글에서 HWPX 로 저장한 후 다시 업로드해 주세요. "
                "(암호화·DRM 적용 HWP 는 자동 처리할 수 없습니다.)"
                + (f"\n[libreoffice]: {preview}" if preview else "")
            )
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    async def validate(self, file_path: str) -> bool:
        if not os.path.exists(file_path):
            logger.error(f"HWP 파일 없음: {file_path}")
            return False
        if not self.can_handle(file_path):
            logger.error(f"HWP 가 아님: {file_path}")
            return False
        if os.path.getsize(file_path) == 0:
            logger.error("HWP 가 비어 있음")
            return False
        return True
