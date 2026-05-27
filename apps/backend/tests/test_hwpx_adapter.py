"""HWPX → layout_ocr 어댑터 단위 테스트.

CLI/LibreOffice 의존성 없이 순수 파이썬 로직만 검증한다.
hwpx-cli JSON 출력은 fixture 로 모킹.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from app.core.steps._hwpx_adapter import (
    _classify_image_block,
    _is_heading,
    _runs_to_text,
    _table_to_markdown,
    adapt_hwpx_to_layout_blocks,
)


# ---------- 보조 함수 ----------


def test_runs_to_text_simple():
    runs = [{"text": "안녕"}, {"text": " "}, {"text": "세상"}]
    assert _runs_to_text(runs) == "안녕 세상"


def test_runs_to_text_handles_missing_field():
    runs = [{"text": "a"}, {}, {"text": "b"}]
    assert _runs_to_text(runs) == "ab"


def test_runs_to_text_with_non_list_returns_empty():
    assert _runs_to_text(None) == ""
    assert _runs_to_text("not a list") == ""


def test_is_heading_explicit_flag():
    assert _is_heading({"style": {"heading": True}}) is True
    assert _is_heading({"style": {"isHeading": True}}) is True


def test_is_heading_by_style_name():
    assert _is_heading({"style": {"name": "Heading 1"}}) is True
    assert _is_heading({"style": {"name": "본문 제목"}}) is True


def test_is_heading_by_large_font_size():
    assert _is_heading({"textProps": {"size": 20}}) is True
    assert _is_heading({"textProps": {"size": 12}}) is False


def test_is_heading_default_false():
    assert _is_heading({}) is False
    assert _is_heading({"style": {}}) is False


def test_table_to_markdown_basic():
    rows = [
        [{"text": "이름"}, {"text": "전화"}],
        [{"text": "홍길동"}, {"text": "010-1234"}],
    ]
    md = _table_to_markdown(rows)
    lines = md.splitlines()
    assert lines[0] == "| 이름 | 전화 |"
    assert lines[1] == "|---|---|"
    assert lines[2] == "| 홍길동 | 010-1234 |"


def test_table_to_markdown_pads_ragged_rows():
    rows = [
        [{"text": "a"}, {"text": "b"}, {"text": "c"}],
        [{"text": "1"}],  # 짧은 행 — 빈 셀로 패딩
    ]
    md = _table_to_markdown(rows)
    lines = md.splitlines()
    assert lines[0] == "| a | b | c |"
    assert lines[2] == "| 1 |  |  |"


def test_table_to_markdown_with_paragraphs_in_cells():
    rows = [
        [
            {"paragraphs": [{"runs": [{"text": "헤더1"}]}]},
            {"paragraphs": [{"runs": [{"text": "헤더2"}]}]},
        ],
        [
            {"paragraphs": [
                {"runs": [{"text": "줄1"}]},
                {"runs": [{"text": "줄2"}]},
            ]},
            {"paragraphs": [{"runs": [{"text": "단일"}]}]},
        ],
    ]
    md = _table_to_markdown(rows)
    assert "헤더1" in md
    assert "줄1<br />줄2" in md


def test_table_to_markdown_empty_returns_empty_string():
    assert _table_to_markdown([]) == ""
    assert _table_to_markdown(None) == ""  # type: ignore[arg-type]


def test_table_to_markdown_escapes_pipe_in_cells():
    """SWEEP: cell text 에 '|' 가 있으면 컬럼 수가 깨지지 않도록 escape."""
    rows = [
        [{"text": "key"}, {"text": "value"}],
        [{"text": "regex"}, {"text": "a|b|c"}],
    ]
    md = _table_to_markdown(rows)
    # cell 내 '|' 가 백슬래시 escape 되어 있어야 markdown 파서가 컬럼 분리로 오인하지 않음
    assert "a\\|b\\|c" in md
    # raw 한 '| a|b|c |' 패턴이 안 들어가야 함
    assert " a|b|c " not in md


def test_table_to_markdown_all_empty_rows_returns_empty():
    """SWEEP: 모든 row 가 빈 list 면 '||' 같은 깨진 markdown 대신 빈 문자열."""
    assert _table_to_markdown([[], []]) == ""


def test_classify_image_explicit_label():
    assert _classify_image_block({"label": "stamp"}, "") == "stamp"
    assert _classify_image_block({"kind": "signature"}, "") == "signature"


def test_classify_image_from_nearby_text():
    assert _classify_image_block({}, "본부장 (인)") == "stamp"
    assert _classify_image_block({}, "신청인 (서명)") == "signature"
    assert _classify_image_block({}, "general text") == "image"


# ---------- adapt_hwpx_to_layout_blocks ----------


@pytest.fixture
def text_only_json():
    return {
        "sections": [
            {
                "elements": [
                    {"type": "paragraph", "style": {"heading": True}, "runs": [{"text": "제목입니다"}]},
                    {"type": "paragraph", "runs": [{"text": "본문 첫 줄."}]},
                    {"type": "paragraph", "runs": [{"text": "본문 둘째 줄."}]},
                ]
            }
        ],
        "images": {},
    }


def test_adapter_text_only(tmp_path, text_only_json):
    result = adapt_hwpx_to_layout_blocks(
        text_only_json, [], str(tmp_path), page_size={"width": 1240, "height": 1754}
    )
    assert result["success"] is True
    assert result["total_pages"] == 1
    assert result["source_format"] == "hwpx_native"
    blocks = result["pages"][0]["layout"]["blocks"]
    assert len(blocks) == 3
    assert blocks[0]["layout_type"] == "title"
    assert blocks[0]["content"] == "제목입니다"
    assert blocks[1]["layout_type"] == "text"
    assert blocks[1]["index"] == 2
    # C2: page-level bbox 가 픽셀 단위 (page_size 의 W×H) 로 emit 됨
    for b in blocks:
        assert b["layout_box"] == [0.0, 0.0, 1240.0, 1754.0]


def test_adapter_default_pixel_box_when_no_page_size(tmp_path, text_only_json):
    """C2 회귀: page_size 가 안 들어와도 픽셀 단위 fallback 박스를 emit."""
    result = adapt_hwpx_to_layout_blocks(text_only_json, [], str(tmp_path))
    b = result["pages"][0]["layout"]["blocks"][0]
    x0, y0, x1, y1 = b["layout_box"]
    assert x0 == 0.0 and y0 == 0.0
    # 폴백 페이지 사이즈 (A4 @ 200DPI 근방)
    assert x1 > 100 and y1 > 100


def test_adapter_with_table(tmp_path):
    j = {
        "sections": [
            {
                "elements": [
                    {"type": "paragraph", "runs": [{"text": "표 헤더"}]},
                    {
                        "type": "table",
                        "rows": [
                            [{"text": "A"}, {"text": "B"}],
                            [{"text": "1"}, {"text": "2"}],
                        ],
                    },
                ]
            }
        ],
        "images": {},
    }
    result = adapt_hwpx_to_layout_blocks(j, [], str(tmp_path))
    blocks = result["pages"][0]["layout"]["blocks"]
    table_block = next(b for b in blocks if b["layout_type"] == "table")
    assert "| A | B |" in table_block["content"]
    assert "| 1 | 2 |" in table_block["content"]


def test_adapter_with_image_dumps_png(tmp_path):
    # 1x1 빨간 PNG (8바이트 헤더 + IHDR 등)
    one_px_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf"
        b"\xc0\x00\x00\x00\x03\x00\x01\xa9\xb4\x1c[\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    j = {
        "sections": [
            {
                "elements": [
                    {"type": "paragraph", "runs": [{"text": "본부장 (인)"}]},
                    {"type": "image", "binaryItemId": "BIN0001"},
                ]
            }
        ],
        "images": {"BIN0001": base64.b64encode(one_px_png).decode("ascii")},
    }
    result = adapt_hwpx_to_layout_blocks(j, [], str(tmp_path))
    image_block = next(
        b for b in result["pages"][0]["layout"]["blocks"] if b["layout_type"] == "stamp"
    )
    assert image_block["image_path"] is not None
    assert Path(image_block["image_path"]).exists()
    assert Path(image_block["image_path"]).stat().st_size > 0
    # C5: stamp/signature content 는 비어 있음 (extractor 오염 방지). image_path 는 별도로 보존.
    assert image_block["content"] == ""


def test_adapter_pages_track_preview_count(tmp_path):
    """C3/E6: pages_result 의 길이는 미리보기 PNG 개수와 일치해야 한다 (sections 수 아님)."""
    j = {
        "sections": [
            {"elements": [{"type": "paragraph", "runs": [{"text": "first block"}]}]},
            {"elements": [{"type": "paragraph", "runs": [{"text": "second block"}]}]},
        ],
        "images": {},
    }
    # 2개 section, 5개 미리보기 PNG → 5개 page (모든 블록은 page 1 에 모이고, page 2-5 는 빈 layout)
    result = adapt_hwpx_to_layout_blocks(
        j, ["a.png", "b.png", "c.png", "d.png", "e.png"], str(tmp_path)
    )
    assert result["total_pages"] == 5
    assert [p["page_index"] for p in result["pages"]] == [1, 2, 3, 4, 5]
    assert result["pages"][0]["image_file"] == "a.png"
    assert result["pages"][4]["image_file"] == "e.png"
    # 모든 element 는 page 1 에
    assert len(result["pages"][0]["layout"]["blocks"]) == 2
    for i in range(1, 5):
        assert result["pages"][i]["layout"]["blocks"] == []


def test_adapter_no_preview_falls_back_to_sections(tmp_path):
    """미리보기 PNG 가 비어 있을 때 (failure 시나리오) 는 section 수로 페이지 채움."""
    j = {
        "sections": [
            {"elements": [{"type": "paragraph", "runs": [{"text": "a"}]}]},
            {"elements": [{"type": "paragraph", "runs": [{"text": "b"}]}]},
        ],
        "images": {},
    }
    result = adapt_hwpx_to_layout_blocks(j, [], str(tmp_path))
    assert result["total_pages"] == 2
    # 모든 블록은 page 1 에
    assert len(result["pages"][0]["layout"]["blocks"]) == 2
    assert result["pages"][1]["layout"]["blocks"] == []


def test_adapter_empty_input_returns_one_empty_page(tmp_path):
    result = adapt_hwpx_to_layout_blocks({}, [], str(tmp_path))
    assert result["total_pages"] == 1
    assert result["pages"][0]["layout"]["blocks"] == []


def test_adapter_unknown_element_with_text_falls_back_to_text(tmp_path):
    j = {
        "sections": [
            {
                "elements": [
                    {"type": "weirdcustom", "runs": [{"text": "그래도 텍스트"}]},
                ]
            }
        ],
        "images": {},
    }
    result = adapt_hwpx_to_layout_blocks(j, [], str(tmp_path))
    blocks = result["pages"][0]["layout"]["blocks"]
    assert len(blocks) == 1
    assert blocks[0]["layout_type"] == "text"
    assert blocks[0]["content"] == "그래도 텍스트"


def test_adapter_block_index_is_global_sequential(tmp_path):
    j = {
        "sections": [
            {"elements": [
                {"type": "paragraph", "runs": [{"text": "p1"}]},
                {"type": "paragraph", "runs": [{"text": "p2"}]},
            ]},
            {"elements": [
                {"type": "paragraph", "runs": [{"text": "p3"}]},
            ]},
        ],
        "images": {},
    }
    result = adapt_hwpx_to_layout_blocks(j, [], str(tmp_path))
    indices = [
        b["index"]
        for page in result["pages"]
        for b in page["layout"]["blocks"]
    ]
    assert indices == [1, 2, 3]
