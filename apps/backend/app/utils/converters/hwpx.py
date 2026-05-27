"""HWPX 변환기 — open-hangul-ai 의 hwpx-cli 를 subprocess 로 호출.

흐름:
    1. `hwpx-cli info`       : 빠른 메타데이터 추출 (페이지 수, 암호화 여부)
    2. `hwpx-cli ... --to json --pretty -o ...` : 어댑터 입력용 구조화 JSON
    3. `hwpx-cli ... --to pdf -o ...`           : UI 미리보기용 PDF
    4. PDFConverter 위임      : PDF → PNG (페이지별)

산출물:
    - output_files: 페이지별 PNG 경로 (PdfConverter 와 호환)
    - metadata.source_format = "hwpx"
    - metadata.hwpx_structured = (CLI JSON 그대로) — ephemeral, pdf_to_image 가 context 로 옮긴 뒤 pop
    - metadata.hwpx_info = (info 명령 결과)
    - metadata.parse_time_ms / pdf_time_ms

뒤이은 `pdf_to_image` 단계가 `source_format == "hwpx"` 면 context 에 skip_ocr 플래그 + hwpx_structured 를 세팅하고,
`layout_ocr` 단계가 그 플래그를 보고 _hwpx_adapter 로 분기한다.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.utils.converters.base import BaseConverter
from app.utils.converters.exceptions import (
    ConversionFailedError,
    ConversionTimeoutError,
)
from app.utils.config import settings
from app.utils.logger import logger


# Backend repo root: apps/backend/. tools/hwpx-runner 가 그 아래.
_BACKEND_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_RUNNER_DIR = _BACKEND_ROOT / "tools" / "hwpx-runner"

# E5: 기본 DPI 200 으로 통일 (HwpConverter PDF 폴백과 일치).
_DEFAULT_DPI = 200

# E4: hwpx-cli 가 생성한 *미리보기* PDF 의 메타데이터는 원본 HWPX 와 무관하므로
# PDFConverter 결과에서 다음 키들을 strip 한다 (잘못된 attribution 방지).
_PDF_PREVIEW_METADATA_KEYS_TO_STRIP = {
    "title",
    "author",
    "subject",
    "creator",
    "producer",
    "creation_date",
    "modification_date",
}

# D4: 자식 프로세스에 전달할 env allowlist — 전체 os.environ 을 넘기면 secrets 유출 표면이 커짐.
# 필요한 키만 정확히 전달.
def _safe_subprocess_env() -> Dict[str, str]:
    base = {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "NODE_OPTIONS": os.environ.get("NODE_OPTIONS", "--max-old-space-size=2048"),
    }
    # HOME/LANG/LC_ALL 은 일부 Node 모듈이 의존 — 있으면 통과
    for k in ("HOME", "LANG", "LC_ALL", "TMPDIR"):
        v = os.environ.get(k)
        if v:
            base[k] = v
    # HWPX_CLI_VERBOSE 등 디버그 플래그가 있으면 그대로
    for k in os.environ:
        if k.startswith("HWPX_CLI_"):
            base[k] = os.environ[k]
    return base


class HwpxConverter(BaseConverter):
    """HWPX → 구조화 JSON + 미리보기 PNG 변환기."""

    name = "hwpx_converter"
    supported_extensions = {".hwpx"}

    # subprocess 타임아웃 (env 로 오버라이드 가능)
    INFO_TIMEOUT_S = 10
    CONVERT_TIMEOUT_S = 120

    def __init__(self, runner_dir: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        self.runner_dir = Path(runner_dir) if runner_dir else _DEFAULT_RUNNER_DIR
        self.cli_path = self.runner_dir / "node_modules" / "open-hangul-ai" / "bin" / "hwpx-cli.mjs"

    # ---------------------------------------------------------------- helpers

    def _cli_exists(self) -> bool:
        return self.cli_path.exists()

    async def _run_cli(
        self,
        args: List[str],
        *,
        timeout: int,
        capture_stdout: bool = False,
    ) -> str:
        """node 로 hwpx-cli 를 실행. stdout 을 utf-8 문자열로 반환.

        Raises:
            ConversionFailedError: rc != 0 또는 암호화 케이스
            ConversionTimeoutError: 타임아웃
        """
        if not self._cli_exists():
            raise ConversionFailedError(
                f"hwpx-cli not found at {self.cli_path}. "
                f"Run `cd {self.runner_dir} && npm install` first."
            )

        cmd = ["node", str(self.cli_path), *args]
        logger.debug(f"hwpx-cli exec: {' '.join(cmd)}")

        # D3: 자식을 별도 세션으로 띄워 grandchildren 까지 한꺼번에 종료 가능하게.
        # POSIX 만 지원 (Windows 는 OCR 백엔드 런타임이 아님).
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.runner_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_safe_subprocess_env(),  # D4: env allowlist
            start_new_session=True,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            # D3: process group 단위로 SIGKILL → grandchildren 까지 정리, 그 다음 await 으로 zombie 회수.
            await self._terminate_proc(proc)
            raise ConversionTimeoutError(
                f"hwpx-cli timed out after {timeout}s: args={args}"
            )

        stderr_text = stderr_bytes.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            # A7: 잘못된 substring 매칭 회피 — '암호'/'PBKDF2' 또는 정확한 토큰 'encryption'/'encrypted document' 만.
            lower_err = stderr_text.lower()
            if (
                "암호" in stderr_text
                or "pbkdf2" in lower_err
                or "encrypted document" in lower_err
                or "encrypted hwpx" in lower_err
                or "incorrect password" in lower_err
                or "password required" in lower_err
            ):
                raise ConversionFailedError(
                    "암호화된 HWPX 입니다. 한글에서 암호 해제 후 다시 업로드해 주세요."
                )
            preview = stderr_text[-500:].strip() or f"exit={proc.returncode}"
            raise ConversionFailedError(f"hwpx-cli failed (rc={proc.returncode}): {preview}")

        return stdout_bytes.decode("utf-8", errors="replace")

    @staticmethod
    async def _terminate_proc(proc: "asyncio.subprocess.Process") -> None:
        """타임아웃/실패 시 자식 프로세스를 process group 단위로 강제 종료하고 zombie 회수."""
        pid = getattr(proc, "pid", None)
        if pid is not None:
            try:
                pgid = os.getpgid(pid)
                os.killpg(pgid, 9)  # SIGKILL — grandchildren 까지
            except (ProcessLookupError, PermissionError, OSError):
                # process group 접근 실패 → 직접 kill 폴백
                try:
                    proc.kill()
                except (ProcessLookupError, OSError, AttributeError):
                    pass
        else:
            try:
                proc.kill()
            except (ProcessLookupError, OSError, AttributeError):
                pass
        # zombie 방지를 위해 짧게 wait. 이미 죽었거나 아직 안 죽었으면 0.5s 내에 회수.
        wait_fn = getattr(proc, "wait", None)
        if callable(wait_fn):
            try:
                await asyncio.wait_for(wait_fn(), timeout=0.5)
            except (asyncio.TimeoutError, AttributeError, TypeError):
                logger.warning(
                    f"subprocess (pid={pid}) did not exit within 0.5s after SIGKILL"
                )

    # ---------------------------------------------------------------- public

    async def convert(
        self,
        file_path: str,
        output_dir: str,
        **kwargs,
    ) -> Dict[str, Any]:
        """HWPX → 구조화 JSON + 미리보기 PNG."""
        self.ensure_output_dir(output_dir)
        out_dir = Path(output_dir)

        # Feature flag — env 또는 settings 로 off 시 명시적으로 거부 (factory 가 PdfConverter 로 폴백시키지 않음).
        if not getattr(settings, "HWPX_NATIVE_PATH", True):
            raise ConversionFailedError(
                "HWPX native path is disabled (settings.HWPX_NATIVE_PATH=False). "
                "Convert this file to PDF before uploading."
            )

        # 1) info — 사전 검증
        info_text = await self._run_cli(
            ["info", file_path],
            timeout=self.INFO_TIMEOUT_S,
        )
        try:
            info = json.loads(info_text) if info_text.strip().startswith("{") else {"raw": info_text.strip()}
        except json.JSONDecodeError:
            info = {"raw": info_text.strip()}

        # 2) 구조화 JSON
        json_path = out_dir / "hwpx_structured.json"
        t_parse_start = time.monotonic()
        await self._run_cli(
            ["convert", file_path, "--to", "json", "--pretty", "-o", str(json_path)],
            timeout=self.CONVERT_TIMEOUT_S,
        )
        parse_ms = int((time.monotonic() - t_parse_start) * 1000)
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                structured = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise ConversionFailedError(f"hwpx-cli JSON parse failed: {e}")

        # 3) 미리보기 PDF
        pdf_path = out_dir / "hwpx_preview.pdf"
        t_pdf_start = time.monotonic()
        await self._run_cli(
            ["convert", file_path, "--to", "pdf", "-o", str(pdf_path)],
            timeout=self.CONVERT_TIMEOUT_S,
        )
        pdf_ms = int((time.monotonic() - t_pdf_start) * 1000)

        # 4) PDF → PNG (기존 PdfConverter 위임). E5: DPI 기본 200 으로 통일.
        from app.utils.converters import PDFConverter  # late import to avoid cycle

        pdf_converter = PDFConverter()
        pdf_result = await pdf_converter.convert(
            str(pdf_path),
            output_dir,
            dpi=kwargs.get("dpi", _DEFAULT_DPI),
            format=kwargs.get("format", "png"),
        )

        sections_count = len(structured.get("sections", [])) if isinstance(structured, dict) else 0
        elements_total = sum(
            len(s.get("elements", []))
            for s in (structured.get("sections") or [])
            if isinstance(s, dict)
        ) if isinstance(structured, dict) else 0

        logger.info(
            f"HWPX native: file={Path(file_path).name} "
            f"parse_ms={parse_ms} pdf_ms={pdf_ms} "
            f"sections={sections_count} elements={elements_total} "
            f"pages={pdf_result.get('page_count')} source_format=hwpx"
        )

        metadata = self.get_metadata(file_path)

        # E4: PDFConverter 가 미리보기 PDF 에서 읽어 들인 metadata 는 원본 HWPX 와 무관 — strip.
        pdf_meta = dict(pdf_result.get("metadata") or {})
        for k in _PDF_PREVIEW_METADATA_KEYS_TO_STRIP:
            pdf_meta.pop(k, None)
        # source_file 도 미리보기 PDF 경로를 가리키므로 원본으로 덮어쓰기 위해 제거
        pdf_meta.pop("source_file", None)
        metadata.update(pdf_meta)

        metadata.update(
            {
                "source_format": "hwpx",
                "hwpx_structured": structured,           # ephemeral — pdf_to_image 가 context 로 옮긴 뒤 pop
                "hwpx_info": info,
                "hwpx_parse_ms": parse_ms,
                "hwpx_pdf_ms": pdf_ms,
                "hwpx_structured_path": str(json_path),
                "hwpx_preview_pdf_path": str(pdf_path),
            }
        )

        return {
            "output_files": pdf_result["output_files"],
            "page_count": pdf_result["page_count"],
            "metadata": metadata,
        }

    async def validate(self, file_path: str) -> bool:
        """파일 존재·확장자·CLI 설치 여부만 확인. 진짜 파싱 가능성은 convert() 에서 판단."""
        if not os.path.exists(file_path):
            logger.error(f"HWPX 파일 없음: {file_path}")
            return False
        if not self.can_handle(file_path):
            logger.error(f"HWPX 가 아님: {file_path}")
            return False
        if os.path.getsize(file_path) == 0:
            logger.error("HWPX 가 비어 있음")
            return False
        if not self._cli_exists():
            logger.error(
                f"hwpx-cli 가 설치되지 않음 (expected at {self.cli_path}). "
                f"`cd {self.runner_dir} && npm install` 실행 필요."
            )
            return False
        return True
