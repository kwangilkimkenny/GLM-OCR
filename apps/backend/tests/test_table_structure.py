"""table_structure 단위 테스트 (Phase 6-D)."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from app.core.table_structure import (
    TableStructure,
    cells_to_html,
    recognize_table,
    backend_status,
)


def _make_grid_image(rows: int, cols: int, cell_w: int = 100, cell_h: int = 60) -> np.ndarray:
    """검은 격자선 + 흰 배경의 단순 표 이미지."""
    h = cell_h * rows + 1
    w = cell_w * cols + 1
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    # 수평선
    for r in range(rows + 1):
        y = r * cell_h
        cv2.line(img, (0, y), (w - 1, y), (0, 0, 0), 2)
    # 수직선
    for c in range(cols + 1):
        x = c * cell_w
        cv2.line(img, (x, 0), (x, h - 1), (0, 0, 0), 2)
    return img


def _make_merged_grid(rows: int, cols: int, merge_first_row: bool = True) -> np.ndarray:
    """첫 번째 행을 단일 셀로 병합한 표."""
    h = 60 * rows + 1
    w = 100 * cols + 1
    img = np.full((h, w, 3), 255, dtype=np.uint8)
    # 외곽
    cv2.rectangle(img, (0, 0), (w - 1, h - 1), (0, 0, 0), 2)
    # 수평선
    for r in range(1, rows):
        y = r * 60
        cv2.line(img, (0, y), (w - 1, y), (0, 0, 0), 2)
    # 수직선 — 첫 행 제외
    for c in range(1, cols):
        x = c * 100
        start_y = 60 if merge_first_row else 0
        cv2.line(img, (x, start_y), (x, h - 1), (0, 0, 0), 2)
    return img


def test_recognize_simple_grid_3x4():
    img = _make_grid_image(rows=3, cols=4)
    structure = recognize_table(img)
    assert isinstance(structure, TableStructure)
    assert structure.rows == 3
    assert structure.cols == 4
    # 셀 12개 (단순 격자는 병합 없음)
    assert len(structure.cells) == 12
    assert structure.backend.startswith("gridline")
    assert "<table>" in structure.html


def test_recognize_with_bbox_crops_correctly():
    page = np.full((400, 600, 3), 255, dtype=np.uint8)
    table_crop = _make_grid_image(rows=2, cols=3)
    h, w = table_crop.shape[:2]
    # 표를 페이지의 (50, 50) 위치에 붙임
    page[50:50 + h, 50:50 + w] = table_crop
    structure = recognize_table(page, [50, 50, 50 + w, 50 + h])
    assert structure.rows == 2
    assert structure.cols == 3


def test_invalid_bbox_returns_empty():
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    structure = recognize_table(img, [10, 10, 11, 11])  # 너무 작음
    assert structure.rows == 0
    assert structure.backend == "invalid_bbox"


def test_html_serialization_with_merged_cell():
    cells = [
        # 첫 번째 행이 colspan=3 으로 병합된 헤더
        type("TC", (), {
            "row": 0, "col": 0, "row_span": 1, "col_span": 3,
            "bbox": [0, 0, 300, 60], "text": "헤더",
            "to_dict": lambda self: {},
        })(),
        type("TC", (), {
            "row": 1, "col": 0, "row_span": 1, "col_span": 1,
            "bbox": [0, 60, 100, 120], "text": "A1",
            "to_dict": lambda self: {},
        })(),
        type("TC", (), {
            "row": 1, "col": 1, "row_span": 1, "col_span": 1,
            "bbox": [100, 60, 200, 120], "text": "B1",
            "to_dict": lambda self: {},
        })(),
        type("TC", (), {
            "row": 1, "col": 2, "row_span": 1, "col_span": 1,
            "bbox": [200, 60, 300, 120], "text": "C1",
            "to_dict": lambda self: {},
        })(),
    ]
    structure = TableStructure(rows=2, cols=3, cells=cells, backend="test")
    html = cells_to_html(structure)
    assert 'colspan="3"' in html
    assert "헤더" in html
    assert "A1" in html and "B1" in html and "C1" in html


def test_html_escapes_special_chars():
    cell = type("TC", (), {
        "row": 0, "col": 0, "row_span": 1, "col_span": 1,
        "bbox": [0, 0, 10, 10], "text": "<script>&",
        "to_dict": lambda self: {},
    })()
    structure = TableStructure(rows=1, cols=1, cells=[cell], backend="test")
    html = cells_to_html(structure)
    assert "&lt;script&gt;" in html
    assert "&amp;" in html


def test_backend_status_keys():
    s = backend_status()
    assert "lore" in s
    assert "gridline" in s
    assert s["gridline"]["available"] is True


def test_invalid_image_path():
    with pytest.raises(ValueError):
        recognize_table("/nonexistent/path.png")
