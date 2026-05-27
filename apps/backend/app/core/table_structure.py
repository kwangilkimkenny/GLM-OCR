"""표 구조 인식 (Phase 6-D).

PP-DocLayoutV3 가 "table" 박스를 찾으면, 그 영역에서 셀의 (논리적 행, 논리적 열,
공간적 bbox) 를 회귀해 행/열 인덱스를 보장한다.

백엔드:
    1. **lore** — LORE++ TSR (torch). 가중치 `models/table_structure/lore_pp.pth`
    2. **gridline** — Hough lines + 격자 휴리스틱 (항상 가능). 단순 격자표는 정확,
       병합 셀/계층 헤더는 제한적.

출력 포맷:
    {
        "rows": <int>, "cols": <int>,
        "cells": [
            {"row": 0, "col": 0, "row_span": 1, "col_span": 1,
             "bbox": [x1, y1, x2, y2], "text": ""}
        ],
        "backend": "lore" | "gridline",
        "html": "<table>...</table>",
    }
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


DEFAULT_TBL_DIR = Path(__file__).resolve().parents[2] / "data" / "table_structure"
TBL_DIR = Path(os.environ.get("WOORI_TABLE_DIR") or DEFAULT_TBL_DIR)
LORE_WEIGHT = TBL_DIR / "lore_pp.pth"

_LOCK = threading.Lock()
_MODEL_CACHE: dict[str, object] = {}


@dataclass
class TableCell:
    row: int
    col: int
    row_span: int
    col_span: int
    bbox: list[int]  # [x1, y1, x2, y2] (table-local 픽셀 좌표)
    text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TableStructure:
    rows: int
    cols: int
    cells: list[TableCell] = field(default_factory=list)
    backend: str = ""
    html: str = ""

    def to_dict(self) -> dict:
        return {
            "rows": self.rows,
            "cols": self.cols,
            "cells": [c.to_dict() for c in self.cells],
            "backend": self.backend,
            "html": self.html,
        }


# ────── Gridline heuristic ──────


def _detect_grid_lines(gray: np.ndarray) -> tuple[list[int], list[int]]:
    """Morphology 로 수평/수직 라인 픽셀을 분리하고, projection 으로 좌표 추출.

    Returns (y_lines, x_lines) — 정렬된 행 분리/열 분리 좌표 리스트.
    """
    h, w = gray.shape
    # adaptive threshold (배경 변동에 강건)
    bw = cv2.adaptiveThreshold(
        cv2.bitwise_not(gray), 255,
        cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2,
    )

    horiz_kernel_len = max(20, w // 30)
    vert_kernel_len = max(20, h // 30)
    horiz_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (horiz_kernel_len, 1))
    vert_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, vert_kernel_len))

    horiz = cv2.morphologyEx(bw, cv2.MORPH_OPEN, horiz_kernel, iterations=1)
    vert = cv2.morphologyEx(bw, cv2.MORPH_OPEN, vert_kernel, iterations=1)

    # row 라인의 y 좌표: horiz 영상의 row 별 sum
    row_proj = horiz.sum(axis=1)
    col_proj = vert.sum(axis=0)
    # peak detection — 단순 임계값
    row_threshold = max(row_proj.max() * 0.4, 1)
    col_threshold = max(col_proj.max() * 0.4, 1)

    y_lines = _merge_close(np.where(row_proj > row_threshold)[0].tolist(), gap=5)
    x_lines = _merge_close(np.where(col_proj > col_threshold)[0].tolist(), gap=5)
    return y_lines, x_lines


def _merge_close(values: list[int], gap: int) -> list[int]:
    """인접한 좌표들을 클러스터 평균으로 병합."""
    if not values:
        return []
    values = sorted(values)
    clusters: list[list[int]] = [[values[0]]]
    for v in values[1:]:
        if v - clusters[-1][-1] <= gap:
            clusters[-1].append(v)
        else:
            clusters.append([v])
    return [int(round(sum(c) / len(c))) for c in clusters]


def _gridline_structure(table_img: np.ndarray) -> TableStructure:
    """격자선 기반 표 셀 추출 — 병합 셀 검출 포함."""
    gray = cv2.cvtColor(table_img, cv2.COLOR_BGR2GRAY) if table_img.ndim == 3 else table_img
    h, w = gray.shape
    y_lines, x_lines = _detect_grid_lines(gray)

    # 격자선이 부족하면 표 경계만 추정
    if len(y_lines) < 2:
        y_lines = [0, h]
    elif y_lines[0] > 5:
        y_lines = [0] + y_lines
    if y_lines[-1] < h - 5:
        y_lines = y_lines + [h]
    if len(x_lines) < 2:
        x_lines = [0, w]
    elif x_lines[0] > 5:
        x_lines = [0] + x_lines
    if x_lines[-1] < w - 5:
        x_lines = x_lines + [w]

    rows = len(y_lines) - 1
    cols = len(x_lines) - 1

    # 표 안쪽에 가까운 라인이 끊겨 있는지 확인하여 row_span/col_span 회귀
    # (단순 휴리스틱: 격자 위치에 라인 픽셀이 일정 비율 이상 차지하면 셀이 분리되었다고 본다)
    inv = cv2.bitwise_not(gray)
    _, line_mask = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

    cells: list[TableCell] = []
    visited = np.zeros((rows, cols), dtype=bool)
    for r in range(rows):
        for c in range(cols):
            if visited[r, c]:
                continue
            x1, y1 = x_lines[c], y_lines[r]
            x2, y2 = x_lines[c + 1], y_lines[r + 1]
            # 병합 검출: 오른쪽 셀과 사이에 수직선이 약하면 col_span +
            col_span = 1
            while c + col_span < cols:
                divider_x = x_lines[c + col_span]
                strip = line_mask[y1:y2, max(0, divider_x - 2): divider_x + 3]
                if strip.size == 0:
                    break
                fill_ratio = float(strip.sum()) / (255.0 * max(strip.size, 1))
                # 라인 픽셀이 ~30% 이상이면 분리되어 있다고 봄
                if fill_ratio > 0.3:
                    break
                col_span += 1
            row_span = 1
            while r + row_span < rows:
                divider_y = y_lines[r + row_span]
                strip = line_mask[max(0, divider_y - 2): divider_y + 3, x1: x_lines[c + col_span]]
                if strip.size == 0:
                    break
                fill_ratio = float(strip.sum()) / (255.0 * max(strip.size, 1))
                if fill_ratio > 0.3:
                    break
                row_span += 1
            visited[r:r + row_span, c:c + col_span] = True
            x2 = x_lines[c + col_span]
            y2 = y_lines[r + row_span]
            cells.append(
                TableCell(
                    row=r, col=c,
                    row_span=row_span, col_span=col_span,
                    bbox=[int(x1), int(y1), int(x2), int(y2)],
                )
            )

    return TableStructure(rows=rows, cols=cols, cells=cells, backend="gridline")


# ────── LORE++ (torch, optional) ──────


def _lore_available() -> bool:
    try:
        import torch  # noqa: F401
    except ImportError:
        return False
    return LORE_WEIGHT.exists()


def _lore_structure(table_img: np.ndarray) -> TableStructure:
    """LORE++ 추론 진입점. 공식 구현(`AdvancedLiterateMachinery/LORE-TSR`)을 import 시도.

    아키텍처 자체가 크고 가중치+소스 모두 필요하므로, 이 모듈은 import 가능성만 확인.
    실패 시 gridline 으로 폴백.
    """
    try:
        import importlib

        # 공식 LORE 가 PYTHONPATH 또는 site-packages 에 설치되어 있어야 함.
        for candidate in ("lore_tsr", "AdvancedLiterateMachinery.LORE"):
            try:
                mod = importlib.import_module(candidate)
                infer = getattr(mod, "infer_table_structure", None)
                if callable(infer):
                    raw = infer(table_img, weight_path=str(LORE_WEIGHT))
                    return _coerce_to_structure(raw, backend_name="lore")
            except ImportError:
                continue
    except Exception:
        pass
    # 폴백
    out = _gridline_structure(table_img)
    out.backend = "gridline (lore unavailable)"
    return out


def _coerce_to_structure(raw: dict, *, backend_name: str) -> TableStructure:
    rows = int(raw.get("rows", 0))
    cols = int(raw.get("cols", 0))
    cells_raw = raw.get("cells", [])
    cells: list[TableCell] = []
    for c in cells_raw:
        cells.append(
            TableCell(
                row=int(c.get("row", 0)),
                col=int(c.get("col", 0)),
                row_span=int(c.get("row_span", 1)),
                col_span=int(c.get("col_span", 1)),
                bbox=list(c.get("bbox", [0, 0, 0, 0])),
                text=str(c.get("text", "")),
            )
        )
    return TableStructure(rows=rows, cols=cols, cells=cells, backend=backend_name)


# ────── HTML 직렬화 (병합 셀 표현) ──────


def cells_to_html(structure: TableStructure) -> str:
    """병합 셀 정확하게 표현하는 HTML 직렬화."""
    if structure.rows == 0 or structure.cols == 0:
        return "<table></table>"
    # 각 셀의 (row, col) → 셀
    grid: dict[tuple[int, int], TableCell] = {(c.row, c.col): c for c in structure.cells}
    # span 으로 가려진 셀 표시
    covered: set[tuple[int, int]] = set()
    for c in structure.cells:
        for rr in range(c.row, c.row + c.row_span):
            for cc in range(c.col, c.col + c.col_span):
                if (rr, cc) != (c.row, c.col):
                    covered.add((rr, cc))

    rows_html = []
    for r in range(structure.rows):
        cells_html = []
        for c in range(structure.cols):
            if (r, c) in covered:
                continue
            cell = grid.get((r, c))
            if cell is None:
                cells_html.append("<td></td>")
                continue
            attrs = []
            if cell.row_span > 1:
                attrs.append(f'rowspan="{cell.row_span}"')
            if cell.col_span > 1:
                attrs.append(f'colspan="{cell.col_span}"')
            attr_str = (" " + " ".join(attrs)) if attrs else ""
            text = cell.text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            cells_html.append(f"<td{attr_str}>{text}</td>")
        rows_html.append("<tr>" + "".join(cells_html) + "</tr>")
    return "<table>" + "".join(rows_html) + "</table>"


# ────── Public API ──────


def recognize_table(
    image_path: str | np.ndarray,
    table_bbox: Optional[list[int]] = None,
    *,
    backend: Optional[str] = None,
) -> TableStructure:
    """표 이미지에서 셀 구조 인식.

    Args:
        image_path: 전체 페이지 이미지 또는 BGR ndarray
        table_bbox: [x1, y1, x2, y2] — 페이지 안의 표 영역. None 이면 전체 이미지를 표로 본다.
        backend: "lore" | "gridline" | None (자동)
    """
    if isinstance(image_path, np.ndarray):
        img = image_path
    else:
        img = cv2.imread(str(image_path))
        if img is None:
            raise ValueError(f"failed to read: {image_path}")

    if table_bbox:
        x1, y1, x2, y2 = [int(v) for v in table_bbox]
        x1, y1 = max(0, x1), max(0, y1)
        x2 = min(img.shape[1], x2)
        y2 = min(img.shape[0], y2)
        if x2 - x1 < 10 or y2 - y1 < 10:
            return TableStructure(rows=0, cols=0, backend="invalid_bbox")
        crop = img[y1:y2, x1:x2]
    else:
        crop = img

    chosen = backend or ("lore" if _lore_available() else "gridline")
    if chosen == "lore":
        try:
            structure = _lore_structure(crop)
        except Exception:
            structure = _gridline_structure(crop)
            structure.backend = "gridline (lore error)"
    else:
        structure = _gridline_structure(crop)

    structure.html = cells_to_html(structure)
    return structure


def backend_status() -> dict:
    return {
        "lore": {
            "available": _lore_available(),
            "weight": str(LORE_WEIGHT),
            "weight_exists": LORE_WEIGHT.exists(),
        },
        "gridline": {"available": True, "note": "OpenCV morphology + Hough"},
    }
