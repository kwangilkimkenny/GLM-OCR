"""HWPX 구조화 JSON → layout_ocr `pages_result` 어댑터.

`HwpxConverter` 가 metadata 에 동봉한 `hwpx_structured` (open-hangul-ai 의
hwpx-cli `--to json` 결과) 를 layout_ocr 가 기대하는 schema 로 변환한다.

layout_ocr 가 기대하는 형태 (참조: apps/backend/app/core/steps/layout_ocr.py:213-219):

    pages_result: List[{
        "page_index": int,
        "image_file": str,
        "layout": {"blocks": List[{
            "layout_type": str,             # text | title | table | image | stamp | signature
            "layout_box": [x1, y1, x2, y2], # PIXEL 좌표 (preview PNG 기준)
            "content": str | None,
            "index": int,
            "image_path": str | None,
            "page_index": int,
        }]}
    }]

Phase 1 의 의도적 단순화:
    - HWPX 의 흐름 레이아웃은 paragraph-level bbox 가 native 하지 않다.
    - 모든 블록의 `layout_box` 는 미리보기 PNG 의 페이지 전체 픽셀 [0, 0, W, H].
      (UI 의 FieldHighlightBox 가 픽셀 단위라 정규화 [0,1] 를 쓰면 1px×1px 점이 됨.)
    - 또한 HWPX sections 와 미리보기 PDF page 수는 일치하지 않을 수 있으므로 (대부분 1 section ↔ N pages),
      Phase 1 에선 **모든 element 를 첫 페이지에 모으고**, 나머지 page 는 빈 layout 으로 padding.
      정확한 element→page 매핑은 Phase 2-D 의 PDF text-map.
"""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.utils.logger import logger


# Phase 1 page-level bbox 기본값 (page_size 가 없을 때만 사용).
# A4 @ 200DPI (PDFConverter 기본) ≈ 1654×2339; 단 frontend 가 originalWidth/Height 로
# 실제 이미지 크기를 알고 있으므로 이 절대값은 큰 의미가 없다.
_FALLBACK_PAGE_W = 1654
_FALLBACK_PAGE_H = 2339

# "(인)" / "(서명)" 등 인근 텍스트로 stamp/signature 분기.
_STAMP_HINT_RE = re.compile(r"\((인|印|도장|seal)\)", re.IGNORECASE)
_SIGNATURE_HINT_RE = re.compile(r"\((서명|sign|signature)\)", re.IGNORECASE)

# SWEEP: markdown 표 셀에서 '|' 가 raw 로 들어가면 컬럼 카운트가 깨짐 → escape.
_MD_CELL_PIPE_RE = re.compile(r"\|")


def _full_page_box(page_size: Optional[Dict[str, Any]]) -> List[float]:
    """C2: layout_box 를 픽셀 [0, 0, W, H] 로 — UI 가 픽셀 단위로 그려야 1px 점 문제 없음."""
    w = h = None
    if isinstance(page_size, dict):
        w = page_size.get("width")
        h = page_size.get("height")
    try:
        w = float(w) if w is not None else float(_FALLBACK_PAGE_W)
        h = float(h) if h is not None else float(_FALLBACK_PAGE_H)
    except (TypeError, ValueError):
        w = float(_FALLBACK_PAGE_W)
        h = float(_FALLBACK_PAGE_H)
    return [0.0, 0.0, w, h]


def _runs_to_text(runs: Any) -> str:
    """paragraph.runs 또는 cell.paragraphs[].runs 에서 텍스트만 이어붙임."""
    if not isinstance(runs, list):
        return ""
    out: List[str] = []
    for r in runs:
        if isinstance(r, dict):
            t = r.get("text")
            if isinstance(t, str):
                out.append(t)
            elif isinstance(t, list):
                # 이중 nested (run inside run) 가능성 방어
                out.append(_runs_to_text(t))
    return "".join(out)


def _paragraph_text(el: Dict[str, Any]) -> str:
    """paragraph element 에서 텍스트 추출. runs 가 없으면 'text' / 'content' 폴백."""
    txt = _runs_to_text(el.get("runs"))
    if txt:
        return txt
    for k in ("text", "content"):
        v = el.get(k)
        if isinstance(v, str) and v:
            return v
    return ""


def _is_heading(el: Dict[str, Any]) -> bool:
    style = el.get("style") or {}
    if isinstance(style, dict):
        if style.get("heading") or style.get("isHeading"):
            return True
        name = (style.get("name") or "").lower()
        if "heading" in name or "title" in name or "제목" in name:
            return True
    # 스타일 메타가 없을 때 글꼴 크기 휴리스틱
    size = (el.get("textProps") or {}).get("size") if isinstance(el.get("textProps"), dict) else None
    if isinstance(size, (int, float)) and size >= 18:
        return True
    return False


def _escape_md_cell(text: str) -> str:
    """SWEEP: GFM 표 셀의 '|' escape — 컬럼 카운트가 깨지지 않게."""
    return _MD_CELL_PIPE_RE.sub(r"\|", text)


def _cell_to_text(cell: Dict[str, Any]) -> str:
    """table cell 의 paragraphs → 한 줄 텍스트 (markdown 표 셀용 — 줄바꿈 <br />)."""
    if not isinstance(cell, dict):
        return ""
    paras = cell.get("paragraphs") or cell.get("elements") or []
    lines: List[str] = []
    for p in paras:
        if isinstance(p, dict):
            t = _paragraph_text(p).strip()
            if t:
                lines.append(t)
    direct = cell.get("text")
    if not lines and isinstance(direct, str):
        return _escape_md_cell(direct.strip())
    return "<br />".join(_escape_md_cell(s) for s in lines)


def _table_to_markdown(rows: List[Any]) -> str:
    """table element → GFM 표. rowspan/colspan 은 우선 무시 (Phase 2-D 정밀화)."""
    if not isinstance(rows, list) or not rows:
        return ""

    matrix: List[List[str]] = []
    for row in rows:
        cells = row if isinstance(row, list) else (row.get("cells") if isinstance(row, dict) else None)
        if not isinstance(cells, list):
            continue
        matrix.append([_cell_to_text(c) for c in cells])

    if not matrix:
        return ""

    col_count = max(len(r) for r in matrix)
    # 모든 행 폭이 0 이면 (편향된 hwpx-cli 출력) — markdown 으로 안전하게 빈 문자열 반환.
    if col_count == 0:
        return ""
    matrix = [r + [""] * (col_count - len(r)) for r in matrix]

    header = matrix[0]
    body = matrix[1:] if len(matrix) > 1 else []
    lines = [
        "| " + " | ".join(header) + " |",
        "|" + "|".join(["---"] * col_count) + "|",
    ]
    for r in body:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def _classify_image_block(
    el: Dict[str, Any],
    nearby_text: str,
) -> str:
    """image element 를 image / stamp / signature 중 하나로 분류."""
    label = (el.get("label") or el.get("kind") or "").lower()
    if label in {"stamp", "seal"}:
        return "stamp"
    if label in {"signature", "sign"}:
        return "signature"

    if _STAMP_HINT_RE.search(nearby_text):
        return "stamp"
    if _SIGNATURE_HINT_RE.search(nearby_text):
        return "signature"

    return "image"


def _decode_image_binary(value: Any) -> Optional[bytes]:
    """structured.images[id] 의 값에서 raw bytes 추출."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return bytes(value)
    if isinstance(value, dict):
        if value.get("__binary"):
            return None
        data = value.get("data") or value.get("base64") or value.get("content")
        if isinstance(data, str):
            try:
                # D5: validate=True 로 진짜 base64 인지 검사 — 비-base64 input 에 garbage 안 만듦.
                return base64.b64decode(data, validate=True)
            except Exception:
                return None
    if isinstance(value, str):
        try:
            return base64.b64decode(value, validate=True)
        except Exception:
            return None
    return None


def _dump_image(
    images: Dict[str, Any],
    bin_id: Any,
    output_dir: Path,
    page_idx: int,
    block_idx: int,
) -> Optional[str]:
    if not bin_id or not isinstance(images, dict):
        return None
    raw = _decode_image_binary(images.get(str(bin_id)) or images.get(bin_id))
    if not raw:
        return None
    out_path = output_dir / f"hwpx_img_p{page_idx}_b{block_idx}.png"
    try:
        with open(out_path, "wb") as f:
            f.write(raw)
        return str(out_path)
    except OSError as e:
        logger.warning(f"failed to dump HWPX image: {e}")
        return None


def adapt_hwpx_to_layout_blocks(
    hwpx_json: Dict[str, Any],
    preview_pngs: List[str],
    output_dir: str,
    images_dir: Optional[str] = None,
    page_size: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """HWPX JSON → layout_ocr 호환 결과 dict.

    Args:
        hwpx_json: hwpx-cli `--to json` 출력.
        preview_pngs: HwpxConverter 가 만든 페이지별 미리보기 PNG 경로 리스트.
        output_dir: 어댑터가 dump 한 이미지·결과 JSON 을 저장할 디렉토리.
        images_dir: 페이지 미리보기 이미지 디렉토리 (그대로 응답에 포함).
        page_size: 페이지의 픽셀 dimension {"width": int, "height": int}.
                   layout_box 를 페이지 전체 픽셀 [0, 0, W, H] 로 채우는 데 사용.

    Returns: layout_ocr 의 `_call_ocr_service` 반환 dict 와 동일 schema.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sections = hwpx_json.get("sections") if isinstance(hwpx_json, dict) else None
    if not isinstance(sections, list) or not sections:
        sections = [{"elements": []}]

    images: Dict[str, Any] = hwpx_json.get("images") if isinstance(hwpx_json, dict) else {}
    if not isinstance(images, dict):
        images = {}

    full_page_box = _full_page_box(page_size)  # C2: 픽셀 좌표

    # ------------------------------------------------------------------ phase-1 paging
    # C3/E6: HWPX section 수 ≠ 미리보기 PDF page 수 — 정확한 매핑은 Phase 2-D.
    # 현재는: **모든 element 를 첫 페이지에 합치고**, page_count = len(preview_pngs) 로 패딩.
    # 이렇게 하면 (a) 미리보기 PNG 가 1개도 누락되지 않고, (b) 사용자가 PDF 페이지를 모두 볼 수 있음.
    n_preview = len(preview_pngs)
    # preview 가 비었으면 (어디서 잘못된 경우) section 수만큼 페이지를 만든다.
    n_pages = n_preview if n_preview > 0 else len(sections)
    if n_pages == 0:
        n_pages = 1

    # 모든 section 의 element 를 평탄화
    flat_elements: List[Dict[str, Any]] = []
    for section in sections:
        if isinstance(section, dict):
            els = section.get("elements")
            if isinstance(els, list):
                flat_elements.extend(el for el in els if isinstance(el, dict))

    # 페이지 1 에 모든 블록 배치
    blocks_page_one: List[Dict[str, Any]] = []
    block_idx = 1
    recent_text_buffer: List[str] = []
    total_paragraphs = 0
    total_tables = 0
    total_images = 0

    for el in flat_elements:
        etype = (el.get("type") or "").lower()

        if etype == "paragraph":
            text = _paragraph_text(el)
            if not text.strip():
                continue
            recent_text_buffer.append(text)
            if len(recent_text_buffer) > 3:
                recent_text_buffer.pop(0)
            blocks_page_one.append(
                {
                    "layout_type": "title" if _is_heading(el) else "text",
                    "layout_box": list(full_page_box),
                    "content": text,
                    "index": block_idx,
                    "image_path": None,
                    "page_index": 1,
                }
            )
            block_idx += 1
            total_paragraphs += 1
            continue

        if etype == "table":
            rows = el.get("rows") or []
            md = _table_to_markdown(rows)
            if not md:
                continue
            blocks_page_one.append(
                {
                    "layout_type": "table",
                    "layout_box": list(full_page_box),
                    "content": md,
                    "index": block_idx,
                    "image_path": None,
                    "page_index": 1,
                }
            )
            block_idx += 1
            total_tables += 1
            continue

        if etype in {"image", "pic", "picture"}:
            nearby = " ".join(recent_text_buffer[-2:])
            kind = _classify_image_block(el, nearby)
            bin_id = el.get("binaryItemId") or el.get("binaryId") or el.get("imageRef")
            image_path = _dump_image(images, bin_id, out_dir, 1, block_idx)
            blocks_page_one.append(
                {
                    "layout_type": kind,
                    "layout_box": list(full_page_box),
                    "content": _stamp_signature_content(kind, image_path),  # C5
                    "index": block_idx,
                    "image_path": image_path,
                    "page_index": 1,
                }
            )
            block_idx += 1
            total_images += 1
            continue

        if etype == "pagebreak":
            continue

        # unknown — 텍스트가 있으면 폴백
        fallback_text = _paragraph_text(el)
        if fallback_text.strip():
            blocks_page_one.append(
                {
                    "layout_type": "text",
                    "layout_box": list(full_page_box),
                    "content": fallback_text,
                    "index": block_idx,
                    "image_path": None,
                    "page_index": 1,
                }
            )
            block_idx += 1
            total_paragraphs += 1

    # n_pages 개의 page entry 생성, 첫 페이지에 blocks_page_one, 나머지는 빈 layout
    pages_result: List[Dict[str, Any]] = []
    for i in range(n_pages):
        image_file = preview_pngs[i] if i < len(preview_pngs) else None
        pages_result.append(
            {
                "page_index": i + 1,
                "image_file": image_file,
                "layout": {"blocks": blocks_page_one if i == 0 else []},
            }
        )

    ocr_result_file = str(out_dir / "ocr_result.json")
    result: Dict[str, Any] = {
        "success": True,
        "pages": pages_result,
        "total_pages": len(pages_result),
        "images_dir": images_dir or str(out_dir),
        "ocr_result_file": ocr_result_file,
        "ref_image_paths": [],
        "source_format": "hwpx_native",
    }

    logger.info(
        "HWPX adapter: pages=%d (preview=%d sections=%d) "
        "paragraphs=%d tables=%d images=%d blocks=%d",
        len(pages_result),
        n_preview,
        len(sections),
        total_paragraphs,
        total_tables,
        total_images,
        block_idx - 1,
    )
    return result


# C5: stamp/signature 블록의 content 는 빈 문자열 — extractor 가 '(이미지)' 같은
# 더미 문자열을 라벨 옆 값으로 오인하지 않게 한다. UI 표시(<img>) 는
# merge_results._pages_to_markdown_and_layout 의 image-rewrite 분기가
# layout_type in {image, stamp, signature} 모두에서 emit 한다.
def _stamp_signature_content(kind: str, image_path: Optional[str]) -> str:
    return ""
