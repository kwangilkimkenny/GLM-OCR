# HWP / HWPX 지원으로 OCR 업그레이드 계획 (v2)

> 작성일: 2026-05-26 · 갱신: 2026-05-26 (v2 — 어댑터 명세·CLI 검증·롤백 추가)
> 베이스: `WOORI_POC_PLAN_V2.md`
> 외부 자산: [`kwangilkimkenny/open-hangul-ai`](https://github.com/kwangilkimkenny/open-hangul-ai) (MIT)
>
> **한 줄**: 이미지/PDF 만 받던 OCR 에 **HWPX 네이티브 파싱 (OCR 우회)** 와 **레거시 HWP 자동 변환** 경로를 추가해, 한글 문서에서 정확도 100% + 응답 시간 1/20 을 동시에 달성한다.

---

## 0. 왜 — 문제와 가치

| 항목 | 현재 (PDF/Image only) | 업그레이드 후 |
|---|---|---|
| `.hwpx` 처리 | 사용자가 직접 PDF 로 변환 후 업로드 → VLM-OCR | **드롭 즉시 처리**. ZIP/XML 직접 파싱 → 글자 손실 0% |
| `.hwp` 처리 | 미지원 (Frontend 가 거부) | LibreOffice headless → HWPX 변환 → 네이티브 경로 |
| 5페이지 표 위주 문서 평균 응답 시간 | ≈ 30~60s (Qwen2.5-VL 호출) | **< 2s** (CLI 파싱) |
| Grounding 의 `source_match` | OCR 결과끼리 매칭 → 깨진 글자가 fuzzy ratio 떨어뜨림 | native text 끼리 매칭 → ungrounded 비율 대폭 감소 |
| 도장·서명 영역 | OCR 좌표 (이미지 픽셀) | HWPX 의 `<hp:pic>` 좌표 + 임베디드 PNG 원본 (위변조 검출 Phase 4 에 직접 입력) |
| 표 셀 구조 | OCR 가 라인을 추정 (가끔 깨짐) | HWPX `<hp:tbl>` rowspan/colspan 그대로 |

핵심 인사이트: 우리카드 평가자가 보유한 양식 (신청서·약관·고객 제출 서류) 상당수가 한글 문서. 그 트랙을 PDF 변환 없이 직접 처리하면, "단순 OCR 경쟁사" 와 차별점이 즉시 생긴다.

---

## 1. open-hangul-ai 자산 재확인 (정밀)

| 자산 | 경로 | 우리 쪽 사용 결정 |
|---|---|---|
| `hwpx-cli convert <file> --to json` | `bin/hwpx-cli.mjs` | ✅ **메인 진입점**. stdout=JSON, stderr=log, `--password` 지원, exit code 0/1/2 명확 |
| `hwpx-cli convert <file> --to pdf` | 동상 | ✅ **미리보기 생성**. LibreOffice 없이 HWPX→PDF 직접. 폰트 자동 주입 |
| `hwpx-cli info <file>` | 동상 | ✅ **사전 검증**. 페이지 수·암호화 여부만 빠르게 확인 |
| `parseHwpxHeadless` (`src/lib/headless/`) | `headless-parser.js` | (대안) CLI 가 무거우면 Node `-e` 인라인 호출. 우선은 CLI 채택 |
| `extractPlainText` / `extractStructuredText` / `extractTables` | `src/lib/headless/text-extractor.js` | (자동 포함) CLI 의 `--to text`/`--to json` 이 내부에서 호출 |
| `DocumentStructureExtractor` | `src/lib/ai/structure-extractor.ts` | △ Phase 2 보류. JSON 결과에 충분한 표 구조가 있으면 backend 휴리스틱으로 충분 |
| `HWPXViewer` (React) | npm `open-hangul-ai` | △ Phase 2. PdfViewer 와 좌표계 매칭 미검증 |
| `hwp-crypto`, `hwp5-encryption-notice` | `src/lib/vanilla/security/` | ❌ Backend 가 CLI exit code 로 동일 정보를 받으므로 별도 도입 불필요 |
| `src/lib/ocr/` (tesseract.js) | `src/lib/ocr/` | ❌ 우리 VLM 이 우월. 미사용 |
| `hwpx-to-hwp-converter` | `src/lib/vanilla/export/` | △ Phase 5 시연용 (수정된 결과를 .hwp 로 다운로드) |
| **HWP 바이너리 reader** | — | ❌ **이 저장소엔 없음**. LibreOffice 로 우회 |

**라이선스**: MIT. npm 의존성 또는 vendoring 모두 가능. 추천: npm (업데이트 추적 용이).

---

## 2. 아키텍처

### 2.1 전체 흐름

```
[Frontend Upload]
   .hwpx / .hwp / .pdf / .png / .jpg
            │
            ▼
   FastAPI /tasks/upload  (multipart)
            │
            ▼
   ┌────────────────────────────────────────────────────────────┐
   │ ConverterFactory.get_converter(file_path)                   │
   │   .hwpx → HwpxConverter      (NEW)                          │
   │   .hwp  → HwpConverter       (NEW, → LibreOffice → .hwpx)   │
   │   .pdf  → PDFConverter        (기존)                         │
   │   .png/.jpg → ImageConverter (기존)                          │
   └────────────────────────────────────────────────────────────┘
            │
            ▼
   pdf_to_image step
     (HWPX 결과면 metadata 에 native_blocks 동봉 + skip_ocr=True 세팅)
            │
            ▼
   layout_ocr step
     if context.skip_ocr:
         pages = adapt_hwpx_to_layout_blocks(metadata.native_blocks)
     else:
         pages = VLM 호출 (기존 경로)
            │
            ▼
   merge_results → 추출기 (Grounding·PII·HITL 모두 동일 schema)
```

### 2.2 결정: **옵션 A — Backend 단일 진실 공급원** (변경 없음)

> 옵션 B (Frontend SimpleHWPXParser 만으로 처리) 는 audit log 단절, PII 통계 분기, schema 불일치 위험이 커서 **기각**. 단 Phase 2 에서 Frontend 미리보기(`HWPXViewer`) 는 별도로 추가 가능.

---

## 3. 어댑터 명세 — HWPX JSON → layout_ocr 블록

> 이 부분이 v1 에서 가장 모호했던 지점. 핵심은 layout_ocr 가 기대하는 schema 와 1:1 매핑이다.

### 3.1 layout_ocr 가 기대하는 schema (현행, `layout_ocr.py:213-219`)

```python
pages_result: List[{
    "page_index": int,
    "image_file": str,
    "layout": {
        "blocks": List[{
            "layout_type": str,            # "text" | "title" | "table" | "image" | "stamp" | "signature"
            "layout_box": [x1, y1, x2, y2],  # normalized 0-1 (vlm_bbox_convert 결과)
            "content": str | None,           # markdown 또는 raw text
            "index": int,                    # 전역 sequential
            "image_path": str | None,        # image 블록일 때만
            "page_index": int,
        }]
    }
}]
```

### 3.2 `hwpx-cli convert --to json` 출력 (관찰값)

```
{
  "sections": [
    {
      "pageWidth": <HWPUNIT>,      // 1 HWPUNIT = 1/7200 inch
      "pageHeight": <HWPUNIT>,
      "elements": [
        { "type": "paragraph", "runs": [{"text": ...}], ... },
        { "type": "table", "rows": [[{cells...}]], ... },
        { "type": "image", "binaryItemId": "...", ... },
        ...
      ]
    }
  ],
  "images": { "<id>": "<base64 or path>" },
  "metadata": { ... }
}
```

### 3.3 어댑터 매핑 규칙

| HWPX element | layout_type | content | layout_box 도출 |
|---|---|---|---|
| `paragraph` (제목 스타일: `style.heading == true`) | `title` | `runs[*].text` 이어붙이기 | **flow-level**: bbox 산정 어려움 → 페이지 전체 (`[0, y_acc, 1, y_acc+h_est]`). Phase 1 은 page-level grounding 만 보장 |
| `paragraph` (일반) | `text` | runs 텍스트 | 위와 동일 |
| `table` | `table` | markdown 표 변환 (헤더 row 추정 + `|` 구분자) | 페이지 전체 또는 page-level box |
| `image` (`hp:pic`) | `image` | `(이미지)` placeholder | HWPX coordinate 가 있으면 px → normalized 변환. 임베디드 binary 는 별도 PNG 로 dump → `image_path` |
| `image` 중 라벨이 stamp/signature 인 경우 | `stamp` / `signature` | 동상 | layout_ocr 의 stamp/signature 분기 자동 작동 (Phase 1-D 노출 로직 그대로) |
| `chart`, `equation` | `text` (raw 텍스트로 폴백) | runs 텍스트 또는 alt-text | 페이지 전체 |
| `pageBreak` | (스킵) | — | `page_index += 1` 트리거 |

**중요 — bbox 처리 방침 (Phase 1)**

HWPX 는 paragraph-level 좌표가 native 하지 않다. 두 선택지:

(a) **빠른 시작 — page-level box**: 모든 블록이 페이지 단위 box 만 가짐. UI hover 가 페이지 전체 강조됨. Grounding 은 정상 작동 (페이지 안에 source 가 있는지로 충분).

(b) **정확한 bbox — PDF 재렌더링 후 text-mapping**: `hwpx-cli convert --to pdf` 로 PDF 생성 → PyMuPDF 의 `page.get_text("dict")` 로 텍스트별 bbox 추출 → HWPX text 와 substring 매칭. 비용 ≈ +1-2s/문서.

**Phase 1 은 (a) 로 시작 → Phase 2 에서 (b) 로 정밀도 ↑.**

### 3.4 어댑터 의사코드

```python
# apps/backend/app/core/steps/_hwpx_adapter.py (NEW)

def adapt_hwpx_to_layout_blocks(hwpx_json: dict, preview_pngs: list[str]) -> dict:
    """HWPX JSON → layout_ocr pages_result schema 변환."""
    pages_result = []
    block_idx = 1
    for page_idx, section in enumerate(hwpx_json["sections"], start=1):
        blocks = []
        for el in section["elements"]:
            if el["type"] == "paragraph":
                text = "".join(r.get("text", "") for r in el.get("runs", []))
                layout_type = "title" if el.get("style", {}).get("heading") else "text"
                blocks.append({
                    "layout_type": layout_type,
                    "layout_box": [0.0, 0.0, 1.0, 1.0],  # Phase 1: page-level
                    "content": text,
                    "index": block_idx,
                    "image_path": None,
                    "page_index": page_idx,
                })
                block_idx += 1
            elif el["type"] == "table":
                blocks.append({
                    "layout_type": "table",
                    "layout_box": [0.0, 0.0, 1.0, 1.0],
                    "content": _table_to_markdown(el["rows"]),
                    "index": block_idx,
                    "image_path": None,
                    "page_index": page_idx,
                })
                block_idx += 1
            elif el["type"] == "image":
                bin_id = el["binaryItemId"]
                png_path = _dump_image(hwpx_json["images"][bin_id], output_dir, page_idx, block_idx)
                blocks.append({
                    "layout_type": _classify_image(el),  # image | stamp | signature
                    "layout_box": _normalize_pic_pos(el, section),
                    "content": "(이미지)",
                    "index": block_idx,
                    "image_path": png_path,
                    "page_index": page_idx,
                })
                block_idx += 1
        pages_result.append({
            "page_index": page_idx,
            "image_file": preview_pngs[page_idx - 1] if page_idx - 1 < len(preview_pngs) else None,
            "layout": {"blocks": blocks},
        })
    return {
        "success": True,
        "pages": pages_result,
        "total_pages": len(hwpx_json["sections"]),
        "images_dir": ...,
        "ocr_result_file": ...,
        "source_format": "hwpx_native",   # merge_results 의 메타에 노출
    }
```

`_classify_image` 는 HWPX 의 imageTag/style/근접 텍스트 휴리스틱 (예: 직전 paragraph 가 "(인) / (서명)" 포함) 으로 stamp/signature 분기. 휴리스틱 실패 시 `image` 폴백.

---

## 4. 컨버터 구현 명세

### 4.1 `HwpxConverter` (신규)

`apps/backend/app/utils/converters/hwpx.py`

```python
class HwpxConverter(BaseConverter):
    name = "hwpx_converter"
    supported_extensions = {".hwpx"}

    def __init__(self, runner_dir: str | None = None):
        super().__init__()
        self.runner_dir = runner_dir or str(
            Path(__file__).resolve().parents[3] / "tools" / "hwpx-runner"
        )
        self.cli = Path(self.runner_dir) / "node_modules" / ".bin" / "hwpx-cli"

    async def convert(self, file_path: str, output_dir: str, **kwargs) -> Dict[str, Any]:
        self.ensure_output_dir(output_dir)

        # 1) info 로 사전 검증 (페이지 수·암호화 여부)
        info = await self._run_cli(["info", file_path], timeout=10)

        # 2) JSON 추출 (native blocks)
        json_path = Path(output_dir) / "hwpx_structured.json"
        await self._run_cli(
            ["convert", file_path, "--to", "json", "--pretty", "-o", str(json_path)],
            timeout=60,
        )
        with open(json_path, "r", encoding="utf-8") as f:
            structured = json.load(f)

        # 3) PDF 미리보기 (UI 용 + 향후 정밀 bbox 매핑용)
        pdf_path = Path(output_dir) / "hwpx_preview.pdf"
        await self._run_cli(
            ["convert", file_path, "--to", "pdf", "-o", str(pdf_path)],
            timeout=60,
        )

        # 4) PDF → PNG (기존 PdfConverter 위임)
        from app.utils.converters import PDFConverter
        pdf_conv = PDFConverter()
        pdf_result = await pdf_conv.convert(
            str(pdf_path),
            output_dir,
            dpi=kwargs.get("dpi", 150),
            format="png",
        )

        return {
            "output_files": pdf_result["output_files"],  # 미리보기 PNG
            "page_count": pdf_result["page_count"],
            "metadata": {
                **pdf_result["metadata"],
                "source_format": "hwpx",
                "hwpx_structured": structured,           # 어댑터 입력
                "hwpx_info": info,
            },
        }

    async def _run_cli(self, args: list[str], timeout: int = 60) -> dict | str:
        proc = await asyncio.create_subprocess_exec(
            "node", str(self.cli), *args,
            cwd=self.runner_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise ConversionTimeoutError(f"hwpx-cli timeout: {args}")

        if proc.returncode != 0:
            if b"encrypted" in stderr.lower() or b"password" in stderr.lower():
                raise ConversionFailedError(
                    "암호화된 HWPX 입니다. 암호 해제 후 다시 업로드해 주세요."
                )
            raise ConversionFailedError(
                f"hwpx-cli failed (rc={proc.returncode}): {stderr.decode(errors='replace')[:500]}"
            )
        return stdout.decode("utf-8", errors="replace")

    async def validate(self, file_path: str) -> bool:
        return os.path.exists(file_path) and file_path.lower().endswith(".hwpx") and self._cli_exists()

    def _cli_exists(self) -> bool:
        return self.cli.exists()
```

**`apps/backend/tools/hwpx-runner/`** (신규 디렉토리):

```
hwpx-runner/
├── package.json    # { "dependencies": { "open-hangul-ai": "^X.Y.Z" } }
├── package-lock.json
└── node_modules/   # gitignore
```

CI/Docker 빌드 단계에서 `cd tools/hwpx-runner && npm ci` 한 번만 실행.

### 4.2 `HwpConverter` (신규)

`apps/backend/app/utils/converters/hwp.py`

```python
class HwpConverter(BaseConverter):
    name = "hwp_converter"
    supported_extensions = {".hwp"}

    async def convert(self, file_path: str, output_dir: str, **kwargs) -> Dict[str, Any]:
        self.ensure_output_dir(output_dir)
        temp = tempfile.mkdtemp(prefix="hwp_to_hwpx_")
        try:
            # 1차: HWP → HWPX
            ok = await self._libreoffice(["--convert-to", "hwpx", "--outdir", temp, file_path], timeout=120)
            if ok:
                hwpx_path = next(Path(temp).glob("*.hwpx"), None)
                if hwpx_path:
                    from app.utils.converters import HwpxConverter
                    result = await HwpxConverter().convert(str(hwpx_path), output_dir, **kwargs)
                    result["metadata"]["source_format"] = "hwp_via_libreoffice_to_hwpx"
                    return result

            # 폴백: HWP → PDF (구조 정보 손실, OCR 로 처리)
            ok = await self._libreoffice(["--convert-to", "pdf", "--outdir", temp, file_path], timeout=120)
            if ok:
                pdf_path = next(Path(temp).glob("*.pdf"), None)
                if pdf_path:
                    from app.utils.converters import PDFConverter
                    result = await PDFConverter().convert(str(pdf_path), output_dir, **kwargs)
                    result["metadata"]["source_format"] = "hwp_via_libreoffice_to_pdf"
                    return result

            raise ConversionFailedError(
                "HWP 변환 실패. 한컴 한글에서 HWPX 로 다시 저장 후 업로드해 주세요. "
                "(암호화된 HWP 는 자동 처리할 수 없습니다.)"
            )
        finally:
            shutil.rmtree(temp, ignore_errors=True)

    async def _libreoffice(self, args: list[str], timeout: int) -> bool:
        cmd = ["libreoffice", "--headless", *args]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            if proc.returncode != 0:
                logger.warning(f"libreoffice {args[0]} failed: {stderr.decode(errors='replace')[:300]}")
                return False
            return True
        except asyncio.TimeoutError:
            proc.kill()
            return False
```

> 주의: LibreOffice 가 정확히 `.hwpx` export 를 지원하는지는 버전에 따라 다름 (7.0+). Phase 1 에서는 PDF 폴백을 default 로 두고, hwpx 폴백을 stretch 로 옮길 수 있다.

### 4.3 등록

`apps/backend/app/utils/converters/__init__.py`:

```python
from app.utils.converters.hwpx import HwpxConverter
from app.utils.converters.hwp import HwpConverter

# ... 기존 ConverterFactory.register 들 아래에
ConverterFactory.register(HwpxConverter)
ConverterFactory.register(HwpConverter)
```

---

## 5. 파이프라인 변경

### 5.1 `pdf_to_image.py` — skip_ocr 플래그 전달

```python
# 변환 결과의 source_format 으로 분기
metadata = result["metadata"]
if metadata.get("source_format", "").startswith("hwpx") or metadata.get("source_format", "").startswith("hwp_via_libreoffice_to_hwpx"):
    context.set("skip_ocr", True)
    context.set("hwpx_structured", metadata.get("hwpx_structured"))
```

### 5.2 `layout_ocr.py` — 어댑터 분기

`layout_and_ocr` 의 try 블록 진입 직전에:

```python
if context.get("skip_ocr") and context.get("hwpx_structured"):
    from app.core.steps._hwpx_adapter import adapt_hwpx_to_layout_blocks
    return adapt_hwpx_to_layout_blocks(
        hwpx_json=context.get("hwpx_structured"),
        preview_pngs=image_files,
        output_dir=output_dir,
    )
```

이 한 줄 분기로 VLM 호출 완전 우회. preprocess / auto_segment 옵션은 자동 무시 (HWPX 는 이미 클린 텍스트).

### 5.3 후처리 (extractors / validators) — 무수정

`extractors/{merchant_application,id_card,bank_book,business_reg}.py` 는 입력이 `pages → blocks` 면 작동하므로 변경 없음.
Grounding 도 raw text 가 native HWPX 텍스트로 채워질 뿐 로직 동일.

---

## 6. Frontend 변경

### 6.1 Allow-list 확장 — `FileUpload.tsx:43-53`

```ts
const ALLOWED_FILE_TYPES = [
  'image/png', 'image/jpeg', 'image/jpg',
  'application/pdf',
  // 한컴 MIME 은 환경마다 다름 → 확장자 폴백 필수
  'application/x-hwp', 'application/haansofthwp',
  'application/vnd.hancom.hwpx', 'application/octet-stream',
]
const ALLOWED_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.pdf', '.hwp', '.hwpx']
const MAX_FILE_SIZE = 50 * 1024 * 1024  // 20 → 50MB (HWPX 임베디드 이미지 고려)
```

안내문 변경: `"형식: png/jpg, pdf, hwp/hwpx"` + 파일 크기 한도 표시 갱신.

### 6.2 입력 input accept — `FileUpload.tsx:306`

```ts
accept='image/*,.pdf,.hwp,.hwpx'
```

### 6.3 결과 표시 — 무수정

`ExtractedFieldsPanel`, `MarkdownPreview`, `useOcrStore`, `PdfViewer` 변경 없음.
다만 **`OCRPage` 상단 메타바**에 `source_format` 뱃지 추가 (`merge_results` 에서 metadata 에 넣어 줌):
- "📄 PDF" / "🖼️ Image" / "📘 HWPX (native)" / "📘 HWP → HWPX" / "📘 HWP → PDF (fallback)"
- 시연자가 "지금 OCR 우회 경로다" 라는 걸 한눈에 알 수 있게.

### 6.4 Phase 2 — HWPX 네이티브 미리보기 (선택)

`HwpxViewer.tsx` 신설, `open-hangul-ai` npm 의존성 추가. PdfViewer 와 동일한 props (`file`, `renderPageOverlay`, `onPageClick`) 로 wrap. **Phase 1 에선 PDF 미리보기 PNG 가 이미 있으므로 PdfViewer 그대로 사용 가능 → Phase 1 끝나기 전까지 보류.**

---

## 7. Phase / 일정 — 갱신

| Phase | 라벨 | 작업 | 추정 LOC | 의존성 |
|---|---|---|---|---|
| **1-E** | HWPX 백엔드 핵심 | runner 디렉토리 + `HwpxConverter` + 어댑터 + skip_ocr + 통합테스트 1 | ~350 | Node 18+ |
| **1-F** | HWP 폴백 | `HwpConverter` + LibreOffice headless. hwpx export → 실패 시 PDF 폴백 | ~150 | LibreOffice 7.0+ |
| **1-G** | 프론트 입력 확장 | allow-list / MAX_FILE_SIZE / source_format 뱃지 | ~50 | — |
| **1-H** | 관측성 | `source_format` 카운터·`parse_time_ms` 히스토그램·fallback 카운터 로그 출력 | ~40 | — |
| **2-D** | 정밀 bbox | PDF text-map (PyMuPDF) 로 paragraph-level bbox 추출 | ~120 | PyMuPDF (이미 dep) |
| **2-E** | HWPX 메타로 휴리스틱 분류 | structured.metadata.title / 표 헤더 라벨로 doc_type 매핑 → VLM 분류 호출 절약 | ~80 | Phase 2-A 와 결합 |
| **2-F** | HWPX 네이티브 뷰어 | Frontend `HwpxViewer` + 좌표계 어댑터 | ~200 | open-hangul-ai npm |
| **3-D** | 변환 감사로그 | `audit_log` 에 source_format · 변환 성공/실패 · sha256 영속화 | ~60 | Phase 3 audit 와 결합 |
| **4-C** | 도장/서명 임베디드 PNG 활용 | HWPX 의 `<hp:pic>` binary 를 그대로 stamp matcher 에 입력 (현재는 OCR crop 사용) → 위변조 검출 정확도 ↑ | ~80 | Phase 4 와 결합 |
| **5-B** | 결과 → HWP export | `hwpx-to-hwp-converter` 차용. 시연자에게 "수정본 HWP 다운로드" 버튼 | ~150 | 시연용 |

**MVP = 1-E + 1-F + 1-G + 1-H**. 이 셋만 끝나면 평가자가 HWPX 신청서를 직접 끌어다 놓을 수 있고, 2 초 안에 결과가 나온다.

---

## 8. 구체 변경 파일 (MVP 1-E~1-H)

### 새 파일
- `apps/backend/tools/hwpx-runner/package.json`
- `apps/backend/tools/hwpx-runner/.gitignore` (`node_modules`)
- `apps/backend/app/utils/converters/hwpx.py`
- `apps/backend/app/utils/converters/hwp.py`
- `apps/backend/app/core/steps/_hwpx_adapter.py`
- `apps/backend/tests/test_hwpx_converter.py`
- `apps/backend/tests/test_hwp_converter.py`
- `apps/backend/tests/test_hwpx_adapter.py`
- `apps/backend/tests/fixtures/sample.hwpx` (작은 텍스트 only)
- `apps/backend/tests/fixtures/sample_with_table.hwpx`
- `apps/backend/tests/fixtures/sample_with_stamp.hwpx`
- `apps/backend/tests/fixtures/sample.hwp` (LibreOffice 변환 성공 케이스)
- `apps/backend/tests/fixtures/sample_encrypted.hwpx` (실패 처리 케이스)
- `THIRD_PARTY_NOTICES.md` (open-hangul-ai MIT attribution)

### 수정 파일
- `apps/backend/app/utils/converters/__init__.py` (converter 등록)
- `apps/backend/app/core/steps/pdf_to_image.py` (skip_ocr 플래그 전달)
- `apps/backend/app/core/steps/layout_ocr.py` (어댑터 분기)
- `apps/backend/app/core/steps/merge_results.py` (response metadata 에 `source_format` 노출)
- `apps/backend/app/schemas/response.py` (`source_format` 필드 추가)
- `apps/backend/Dockerfile` (Node.js + LibreOffice 설치)
- `apps/backend/pyproject.toml` (필요 시 `python-magic` 추가)
- `apps/frontend/src/routes/_ocr/FileUpload.tsx` (allow-list)
- `apps/frontend/src/libs/api.ts` (`source_format` 필드)
- `apps/frontend/src/routes/_ocr/OCRPage.tsx` (뱃지)
- `.gitignore` (`apps/backend/tools/hwpx-runner/node_modules`)

---

## 9. 테스트 시나리오

### 9.1 단위 (`pytest`)

| 테스트 | 입력 | 기대 결과 |
|---|---|---|
| `test_hwpx_converter_text_only` | sample.hwpx | structured.sections[0].elements 에 paragraph N개. `source_format == 'hwpx'` |
| `test_hwpx_converter_with_table` | sample_with_table.hwpx | adapter 가 markdown 표를 생성 (행수·열수 ground truth) |
| `test_hwpx_converter_encrypted` | sample_encrypted.hwpx | `ConversionFailedError("암호화…")` raise |
| `test_hwpx_converter_timeout` | mock subprocess hang | `ConversionTimeoutError` |
| `test_hwpx_adapter_image_block` | structured json with image | block.layout_type=='image', image_path 존재 |
| `test_hwpx_adapter_stamp_classification` | "(인)" 인접 image | block.layout_type=='stamp' |
| `test_hwp_converter_via_hwpx` | sample.hwp | metadata.source_format=='hwp_via_libreoffice_to_hwpx' |
| `test_hwp_converter_pdf_fallback` | LibreOffice mock 으로 hwpx export 실패 | source_format=='hwp_via_libreoffice_to_pdf' |
| `test_skip_ocr_flag` | HWPX 통과 시 layout_ocr 의 VLM 호출 mock 이 0회 | VLM mock.call_count == 0 |

### 9.2 통합 (실제 LibreOffice + Node 가 깔린 환경)

| # | 시나리오 | 검증 포인트 |
|---|---|---|
| I1 | 우리카드 신청서 PDF vs 같은 신청서 HWPX 동시 처리 | 추출 필드 일치율 > 95%. HWPX 의 grounding ungrounded 비율 ≤ PDF |
| I2 | 30페이지 HWPX (계약서) | 응답 시간 < 5s, 메모리 < 500MB |
| I3 | 표 12개 있는 HWPX | 모든 표가 markdown 으로 추출됨, cell 누락 0 |
| I4 | 도장 2개 + 서명 1개 있는 HWPX | layout_type=='stamp' 2건, 'signature' 1건 |
| I5 | 암호화 HWPX | UI 에 명확한 한국어 에러 메시지 |
| I6 | 일반 PDF (회귀) | 기존 OCR 결과와 동일 (regression 0) |
| I7 | HWP (LibreOffice 변환 성공) | 결과가 PDF 경로와 동등 |
| I8 | HWP (변환 실패 → PDF 폴백) | 결과가 PDF 경로와 동등, source_format 메타에 'pdf_fallback' 명시 |

### 9.3 시연 체크리스트
- [ ] Drop `.hwpx` → 2초 이내 결과 표시
- [ ] 상단 뱃지에 "📘 HWPX (native)" 표시
- [ ] 같은 문서 PDF 결과와 비교: ungrounded 0 vs N
- [ ] Frontend allow-list 에서 `.hwp` 도 받음 → 10초 내 결과 (LibreOffice 첫 호출 cold start 포함)

---

## 10. 관측성·롤백·플래그

### 10.1 메트릭 (1-H)

`logger.info` 한 줄로 충분:
```
[task_id] HWPX native: parse_ms=420 sections=1 elements=87 tables=3 images=5 source_format=hwpx
[task_id] HWP fallback: libreoffice_ms=2300 path=hwpx_export source_format=hwp_via_libreoffice_to_hwpx
[task_id] HWP fallback: libreoffice_ms=2300 path=pdf source_format=hwp_via_libreoffice_to_pdf
```
운영 시 grep / Loki 로 집계.

### 10.2 Feature Flag

`app.utils.config.settings.HWPX_NATIVE_PATH: bool = True` (env `HWPX_NATIVE_PATH=0` 로 끌 수 있음).

`HwpxConverter.convert` 안에서:
```python
if not settings.HWPX_NATIVE_PATH:
    # 강제 폴백: LibreOffice 로 HWPX → PDF
    return await self._fallback_to_pdf(file_path, output_dir, **kwargs)
```

### 10.3 롤백

문제 발생 시:
1. 환경변수 `HWPX_NATIVE_PATH=0` → 모든 HWPX 가 PDF 변환 경로로 (HwpConverter 의 PDF 폴백 재사용)
2. 또는 `ConverterFactory` 에서 `HwpxConverter` / `HwpConverter` 등록만 주석 처리 → 업로드 단계에서 `UnsupportedFormatError` 로 거부 (이전 상태와 동등)

**즉 1단계 롤백은 코드 배포 없이 가능**.

---

## 11. 운영·인프라

### 11.1 Docker

`apps/backend/Dockerfile` 추가:
```dockerfile
# Node 18 (Debian-friendly, ~120MB)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y nodejs

# LibreOffice headless (≈ 400MB, 큰 비용)
RUN apt-get install -y --no-install-recommends \
    libreoffice-core libreoffice-writer libreoffice-common \
 && rm -rf /var/lib/apt/lists/*

# HWPX runner
COPY tools/hwpx-runner /app/tools/hwpx-runner
RUN cd /app/tools/hwpx-runner && npm ci --omit=dev
```

이미지 크기 영향: 기존 ≈ 800MB → 추가 후 ≈ 1.3GB. CI 에서는 1회 빌드 후 layer 캐시.

**최적화 (Phase 3 stretch)**: hwpx-runner 를 sidecar 컨테이너로 분리 → HTTP `POST /convert` 형태. backend 이미지 크기 거의 동일하게 유지.

### 11.2 콜드 스타트

- Node CLI 의 첫 import 가 ~200ms 정도. POC 에서는 무시 가능.
- LibreOffice 의 첫 변환은 ~3-4s. **워밍업**: 컨테이너 기동 시 `libreoffice --headless --version` 한 번 실행 (entrypoint).

### 11.3 동시성

- LibreOffice headless 는 같은 user profile 디렉토리에 락 → 동시 호출 시 충돌. 각 호출에 `--env:UserInstallation=file:///tmp/lo-<uuid>` 격리 옵션 추가.
- Node CLI 는 stateless → 자유롭게 병렬 가능.

---

## 12. 위험 매트릭스 (갱신)

| # | 위험 | 가능성 | 영향 | 대응 |
|---|---|---|---|---|
| R1 | HWPX 가 우리 사내 변종에서 깨짐 (변환 실패는 아니지만 일부 element 누락) | 중 | 중 | adapter 가 unknown element 를 silent skip + log 경고. Phase 2-D 의 PDF text-map 으로 누락 텍스트 발견 가능 |
| R2 | LibreOffice 의 hwpx export 가 7.x 일부 버전에서 부재 | 중 | 저 | PDF 폴백이 자동 동작. 운영 LibreOffice 버전 사전 확인 |
| R3 | Node CLI 가 stdout 에 BOM 또는 trailing 공백을 섞음 | 저 | 저 | `--pretty` 안 쓰고 `-o file` 로 저장 → 파일에서 json.load (이미 그렇게 함) |
| R4 | 매우 큰 HWPX (50MB+, 이미지 100개+) → Node OOM | 중 | 중 | `--max-old-space-size=2048` 환경변수, 그래도 실패 시 `ConversionFailedError("문서가 너무 큽니다")` 명확한 메시지 |
| R5 | 한컴 자체 암호 HWP (DRM) | 중 | 저 | `_libreoffice` 실패 → 명시적 한국어 에러 메시지 (open-hangul-ai 의 `hwp5-encryption-notice` 문구 차용) |
| R6 | 동시 LibreOffice 호출 충돌 | 고 | 중 | `UserInstallation` 격리 (11.3) |
| R7 | npm 패키지 cli 가 향후 breaking change | 저 | 중 | `package.json` 에 정확한 버전 핀. `tools/hwpx-runner/package-lock.json` 커밋 |
| R8 | MIT 라이선스 attribution 누락 | 저 | 저 | `THIRD_PARTY_NOTICES.md` 추가 + 빌드 시 NPM `--legal=true` 로 검증 |
| R9 | bbox 가 page-level 만이라 HITL hover 가 정밀하지 않음 | 고 | 저 | Phase 1 명시. Phase 2-D 에서 정밀화. 시연 멘트에서 "HWPX 는 native 텍스트라 OCR 좌표가 불필요" 로 설명 |
| R10 | 우리 사내 HWPX 가 `hwpx-cli` 가 모르는 OLE/Chart 를 포함 | 중 | 저 | adapter 가 unknown element 를 "text" 로 폴백 + 원본 PDF 미리보기는 그대로 보임 |

---

## 13. 샘플 파일 수집 (선행 작업)

| 파일 | 용도 | 수집처 |
|---|---|---|
| `sample.hwpx` (단순 텍스트) | unit | 한컴 한글에서 직접 작성 또는 정부24 등본 |
| `sample_with_table.hwpx` | unit | 같은 양식, 표 12개 우리카드 신청서 형태 |
| `sample_with_stamp.hwpx` | unit | 도장·서명 이미지 삽입 |
| `sample.hwp` (한컴 5.0) | unit | 한글 2018+ 에서 `.hwp` 로 저장 |
| `sample_encrypted.hwpx` | unit | 한글에서 "문서 암호" 설정 |
| `woori_application.hwpx` | 시연 / 통합 | 평가자 협조 필요. 없으면 공개 신청서 양식 모방 |
| `woori_application.pdf` | 시연 비교군 | 위 hwpx 를 PDF 로 export |

샘플은 Git LFS 또는 `.gitignore` 후 별도 fixture 다운로드 스크립트.

---

## 14. 결정해야 할 것

| # | 질문 | 옵션 | 추천 | 결정자 |
|---|---|---|---|---|
| Q1 | hwpx-runner 를 backend 안에 둘지, 별도 sidecar 컨테이너 | 안/밖 | 안 (단순). 운영에서 이미지 비대 우려되면 밖 | 운영 |
| Q2 | open-hangul-ai 의존성 — npm vs vendoring | npm/vendor | npm (업데이트 추적) | 본인 |
| Q3 | HWP 처리 우선순위 — 1-F 를 MVP 에 포함? | yes/no | yes (우리카드 평가자가 .hwp 보낼 가능성 매우 높음) | 본인 |
| Q4 | bbox 정밀도 Phase 1 (a 또는 b) | (a) page-level / (b) PDF text-map | (a) 로 시작 → 2-D | 본인 |
| Q5 | Frontend HWPXViewer 도입 시점 | Phase 1 / Phase 2 / 안 함 | Phase 2 (Phase 1 은 PDF 미리보기로 충분) | 본인 |
| Q6 | 시연용 .hwp export (5-B) 포함 시점 | Phase 5 / 안 함 | 시간 남으면 Phase 5 | 본인 |

---

## 15. 즉시 착수 순서 (1-E 만)

`worktree` 권장 — 메인 브랜치는 WOORI POC Phase 1 진행 중일 수 있음.

1. `git switch -c feat/hwpx-native`
2. `mkdir -p apps/backend/tools/hwpx-runner && cd $_ && npm init -y && npm install open-hangul-ai` → `package-lock.json` 커밋
3. `apps/backend/tools/hwpx-runner/node_modules/.bin/hwpx-cli info <sample>` 로 동작 검증 (manual smoke test)
4. `apps/backend/app/utils/converters/hwpx.py` 작성
5. `apps/backend/app/core/steps/_hwpx_adapter.py` 작성
6. `apps/backend/app/utils/converters/__init__.py` 에 등록
7. `apps/backend/app/core/steps/{pdf_to_image,layout_ocr}.py` 에 skip_ocr 분기
8. `apps/backend/tests/test_hwpx_converter.py` 작성 + `pytest -k hwpx` 통과
9. Frontend `FileUpload.tsx` allow-list 확장
10. 로컬에서 e2e: `.hwpx` 끌어놓기 → 결과 표시 → grounding ok 확인
11. `git commit -m "feat: HWPX native parse path (skip OCR for hwpx inputs)"` → PR

소요: 백엔드 1일, 프론트 1시간, 통합 테스트 0.5일 = **약 1.5~2일**.

---

## 16. 시연 멘트 (Phase 1 끝났을 때 — 갱신)

> "현재까지는 PDF/이미지만 처리했습니다. 이제 **한컴 한글의 표준 HWPX 와 레거시 HWP** 까지 직접 받습니다.
>
> HWPX 는 ZIP+XML 구조라 OCR 을 **거치지 않고** 글자·표·도장을 손실 없이 가져옵니다 — 같은 문서를 PDF 로 올리면 OCR 시간 약 30초가 걸리지만, HWPX 직접 처리는 **2초 미만**. Grounding 도 native 텍스트끼리 매칭하므로 ungrounded 비율이 사실상 0 입니다.
>
> 레거시 HWP 는 LibreOffice headless 로 자동 HWPX 변환 후 동일 경로로 처리합니다. 변환이 실패한 경우 PDF 폴백 후 OCR — 즉 어떤 형식이 들어와도 결과를 돌려줍니다.
>
> 결과 패널의 '📘 HWPX (native)' 뱃지가 'OCR 우회 경로' 임을 표시합니다."

— 단순 OCR 데모 vs **문서 형식 인식 + 적응형 추출 파이프라인** 의 차이가 여기서 드러난다.
