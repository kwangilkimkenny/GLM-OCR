"""
版面分析和OCR处理步骤
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core.document_classifier import classify_document
from app.core.document_segmenter import segment_documents
from app.core.flows.base import ProcessingContext
from app.core.image_quality import analyze_image, is_low_quality
from app.core.ocr_client import LayoutAndOCRClient
from app.core.steps._hwpx_adapter import adapt_hwpx_to_layout_blocks
from app.core.table_structure import recognize_table
from app.utils.config import settings
from app.utils.image_preprocess import auto_preprocess_file, preprocess_image_file
from app.utils.image_processer import crop_image_by_bbox_to_path, vlm_bbox_convert
from app.utils.logger import logger


# 우리카드 POC 엔진 라우팅
ENGINE_URLS = {
    "qwen": "http://localhost:5002/glmocr/parse",       # vLLM Qwen2.5-VL-7B-AWQ
    "glm-ocr": "http://localhost:5003/glmocr/parse",    # Ollama GLM-OCR 1.1B
}
PRIMARY_ENGINE = "qwen"
SECONDARY_ENGINE = "glm-ocr"


class LayoutOcrStepInput:
    image_files_path: List[str]
    page_count: Optional[int]
    images_dir: Optional[str]

    def __init__(
        self,
        image_files_path: List[str],
        page_count: Optional[int] = None,
        images_dir: Optional[str] = None,
    ) -> None:
        self.image_files_path = image_files_path
        self.page_count = page_count
        self.images_dir = images_dir


async def layout_and_ocr(
    context: ProcessingContext,
    input: LayoutOcrStepInput,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> Dict[str, Any]:
    task_id = context.task_id
    ocr_config = context.ocr_config or {}

    image_files = input.image_files_path
    images_dir = input.images_dir
    page_count = input.page_count
    # A2: 하위 _process_with_engine 이 page_size.get('width') 를 무조건 호출하므로 None 으로 흘리면 안 됨.
    page_size = (context.metadata or {}).get("page_size") or {}
    output_dir = context.get_output_dir()
    logger.info(f"[{task_id}] Starting layout and OCR processing")
    logger.info(f"[{task_id}] Processing {page_count} pages from {images_dir}")

    # ──── HWPX 네이티브 경로: VLM/전처리 모두 우회, 어댑터만 호출 ────
    if context.get("skip_ocr") and context.get("hwpx_structured"):
        adapted = adapt_hwpx_to_layout_blocks(
            hwpx_json=context.get("hwpx_structured"),
            preview_pngs=image_files,
            output_dir=output_dir,
            images_dir=images_dir,
            page_size=page_size,  # C2: 픽셀 단위 bbox 산정용
        )
        # ocr_result.json 으로 영속화 (merge_results 가 파일에서 다시 읽음)
        try:
            with open(adapted["ocr_result_file"], "w", encoding="utf-8") as f:
                json.dump(adapted, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[{task_id}] persist HWPX adapter result failed: {e}")
        logger.info(
            f"[{task_id}] HWPX adapter completed: "
            f"pages={adapted.get('total_pages')} source_format=hwpx_native"
        )
        return adapted

    # 2-B + 6-A/B: 자동 전처리. preprocess 또는 auto_quality 옵션 ON 일 때.
    # - preprocess=True 만 → 기존 deskew+CLAHE+unsharp (수동 옵션 유지)
    # - auto_quality=True → image_quality 진단 후 SR/deshadow/illumination 자동 적용
    quality_reports: list[dict] = []
    if ocr_config.get("preprocess") or ocr_config.get("auto_quality"):
        use_auto = bool(ocr_config.get("auto_quality"))
        binarize = bool(ocr_config.get("preprocess_binarize", False))
        preprocessed_files: list[str] = []
        for src in image_files:
            try:
                stem = os.path.splitext(os.path.basename(src))[0]
                dst = os.path.join(output_dir, f"{stem}_preproc.png")
                if use_auto:
                    info = auto_preprocess_file(src, dst)
                    qr = info.get("quality_report") or {}
                    quality_reports.append({"file": src, **qr})
                    logger.info(
                        f"[{task_id}] auto-quality: short_side={qr.get('short_side')} "
                        f"upscale_x{qr.get('upscale_factor', 1.0)} "
                        f"backend={info.get('sr_backend', 'n/a')} "
                        f"skipped={info.get('skipped', False)}"
                    )
                else:
                    info = preprocess_image_file(
                        src, dst, do_deskew=True, binarize=binarize
                    )
                    logger.info(f"[{task_id}] preprocessed: {info}")
                preprocessed_files.append(dst)
            except Exception as e:
                logger.warning(f"[{task_id}] preprocess failed for {src}: {e}; using original")
                preprocessed_files.append(src)
        image_files = preprocessed_files

    # 2-C: 혼합 문서 분리 — auto_segment 옵션 + 다중 페이지일 때만
    segments: list[dict] = []
    if ocr_config.get("auto_segment") and len(image_files) > 1:
        try:
            segments = await segment_documents(image_files)
            logger.info(
                f"[{task_id}] segmented into {len(segments)} document(s): "
                f"{[(s['document_type'], s['page_count']) for s in segments]}"
            )
            # 가장 큰 segment 의 유형으로 document_type 라우팅 (단일 추출기 흐름 유지)
            if segments:
                primary = max(segments, key=lambda s: s["page_count"])
                if ocr_config.get("document_type") in (None, "auto", "freeform"):
                    ocr_config["document_type"] = primary["document_type"]
                    ocr_config["_classified"] = {
                        "document_type": primary["document_type"],
                        "raw_response": "auto_segment primary",
                        "processing_time_ms": sum(
                            c["processing_time_ms"] for s in segments for c in s["classifications"]
                        ),
                    }
                    context.ocr_config = ocr_config
        except Exception as e:
            logger.warning(f"[{task_id}] auto_segment failed: {e}")

    # 2-A: 문서 유형 자동 분류 (document_type=='auto' 일 때, 분할 안 했을 때만)
    if ocr_config.get("document_type") == "auto" and image_files:
        try:
            cls = await classify_document(image_files[0])
            classified = cls["document_type"]
            ocr_config["document_type"] = classified
            ocr_config["_classified"] = cls  # merge_results 가 metadata 에 노출
            context.ocr_config = ocr_config
            logger.info(
                f"[{task_id}] auto-classified document_type='{classified}' "
                f"({cls['processing_time_ms']}ms, raw={cls['raw_response']!r})"
            )
        except Exception as e:
            logger.warning(f"[{task_id}] auto-classification failed: {e}; falling back to freeform")
            ocr_config["document_type"] = "freeform"
            context.ocr_config = ocr_config

    try:
        result = await _call_ocr_service(
            page_size=page_size,
            image_files=image_files,
            images_dir=images_dir,
            page_count=page_count,
            config=ocr_config,
            output_dir=output_dir,
            progress_callback=progress_callback,
        )
        # 6-D: 표 구조 인식 후처리 — table_structure 옵션 ON 이고 layout 에 table 블록이 있을 때
        tables_meta: list[dict] = []
        if ocr_config.get("table_structure"):
            try:
                tables_meta = _recognize_tables_in_result(task_id, result, output_dir)
                if tables_meta:
                    result["tables"] = tables_meta
                    logger.info(f"[{task_id}] table_structure: {len(tables_meta)} table(s) recognized")
            except Exception as e:
                logger.warning(f"[{task_id}] table_structure failed: {e}")

        # 분류·세분화 메타데이터를 result + ocr_result.json 양쪽에 저장
        # (merge_results 가 file 로부터 다시 읽어들이기 때문)
        extra: dict[str, Any] = {}
        if ocr_config.get("_classified"):
            result["classified"] = ocr_config["_classified"]
            extra["classified"] = ocr_config["_classified"]
        if segments:
            result["segments"] = segments
            extra["segments"] = segments
        if quality_reports:
            result["quality_reports"] = quality_reports
            extra["quality_reports"] = quality_reports
        if tables_meta:
            extra["tables"] = tables_meta
        if extra:
            try:
                ocr_result_file = Path(output_dir) / "ocr_result.json"
                if ocr_result_file.exists():
                    with open(ocr_result_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    data.update(extra)
                    with open(ocr_result_file, "w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.warning(f"[{task_id}] failed to persist extra meta: {e}")
        logger.info(f"[{task_id}] Layout and OCR processing completed")
        return result
    except Exception as e:
        logger.error(f"[{task_id}] Layout and OCR processing failed: {e}")
        raise


async def _process_with_engine(
    engine_url: str,
    image_files: List[str],
    page_size: Dict[str, Any],
    output_dir: str,
    with_image_crop: bool,
    block_idx_start: int = 1,
    timeout: float = 600.0,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """단일 엔진으로 image_files 를 OCR 처리.

    Returns:
        (pages_result, ref_image_paths)
    """
    cli = LayoutAndOCRClient(timeout=timeout)
    page_width = page_size.get("width")
    page_height = page_size.get("height")
    block_idx = block_idx_start
    ref_image_paths: List[str] = []
    pages_result: List[Dict[str, Any]] = []

    for i, image_file in enumerate(image_files):
        page_num = i + 1
        result = await cli.process_single_image(image_file, custom_url=engine_url)
        page_blocks: List[Dict[str, Any]] = []
        for block in result:
            block_label = block.get("label", "text")
            block_bbox = block.get("bbox_2d", [0, 0, 0, 0])
            block_content = block.get("content", None)
            normalized_box = vlm_bbox_convert(block_bbox, page_width, page_height)

            image_path_field = None
            if with_image_crop and block_label == "image":
                try:
                    split_filename = f"split_{page_num}_{block_idx:04d}.png"
                    split_path = os.path.join(output_dir, split_filename)
                    crop_image_by_bbox_to_path(image_file, normalized_box, split_path)
                    image_path_field = split_path
                    ref_image_paths.append(image_path_field)
                except Exception as e:
                    logger.warning(f"crop block {block_idx} failed: {e}")

            page_blocks.append(
                {
                    "layout_type": block_label,
                    "layout_box": normalized_box,
                    "content": block_content,
                    "index": block_idx,
                    "image_path": image_path_field,
                    "page_index": page_num,
                }
            )
            block_idx += 1

        pages_result.append(
            {
                "page_index": page_num,
                "image_file": image_file,
                "layout": {"blocks": page_blocks},
            }
        )

    return pages_result, ref_image_paths


async def _call_ocr_service(
    image_files: List[str],
    images_dir: str,
    page_count: int,
    config: Dict[str, Any],
    output_dir: str,
    page_size: Dict[str, Any],
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> Dict[str, Any]:
    if progress_callback:
        await progress_callback(0.0, f"Initializing OCR service for {page_count} pages")

    custom_url = config.get("custom_url") if config else None
    engine = (config or {}).get("engine", "qwen")

    if engine == "both":
        primary_url = ENGINE_URLS[PRIMARY_ENGINE]
        secondary_url = ENGINE_URLS[SECONDARY_ENGINE]
        logger.info(
            f"OCR engine='both' → primary={primary_url}, secondary={secondary_url}"
        )

        if progress_callback:
            await progress_callback(5.0, f"Running primary engine ({PRIMARY_ENGINE})")

        # Turing GPU 환경에서 두 엔진 동시 호출은 vLLM backpressure 로 timeout 위험.
        # POC 안정성 우선 — 순차 실행 (primary → secondary). 시간은 ~90s.
        primary_pages, ref_image_paths = await _process_with_engine(
            primary_url,
            image_files,
            page_size,
            output_dir,
            with_image_crop=True,
        )

        if progress_callback:
            await progress_callback(55.0, f"Running secondary engine ({SECONDARY_ENGINE})")

        secondary_pages, _ = await _process_with_engine(
            secondary_url,
            image_files,
            page_size,
            output_dir,
            with_image_crop=False,
            block_idx_start=10001,
        )

        if progress_callback:
            await progress_callback(100.0, "Both engines completed")

        ocr_result_file = Path(output_dir) / "ocr_result.json"
        ocr_result_data: Dict[str, Any] = {
            "success": True,
            "pages": primary_pages,
            "secondary_pages": secondary_pages,
            "primary_engine": PRIMARY_ENGINE,
            "secondary_engine": SECONDARY_ENGINE,
            "total_pages": page_count,
            "images_dir": images_dir,
            "ocr_result_file": str(ocr_result_file),
            "ref_image_paths": ref_image_paths,
        }
    else:
        if custom_url:
            engine_url = custom_url
        else:
            engine_url = ENGINE_URLS.get(engine, ENGINE_URLS["qwen"])
            logger.info(f"OCR engine='{engine}' → {engine_url}")

        pages_result, ref_image_paths = await _process_with_engine(
            engine_url, image_files, page_size, output_dir, with_image_crop=True
        )

        if progress_callback:
            await progress_callback(100.0, "OCR processing completed")

        ocr_result_file = Path(output_dir) / "ocr_result.json"
        ocr_result_data = {
            "success": True,
            "pages": pages_result,
            "total_pages": page_count,
            "images_dir": images_dir,
            "ocr_result_file": str(ocr_result_file),
            "ref_image_paths": ref_image_paths,
        }

    try:
        with open(ocr_result_file, "w", encoding="utf-8") as f:
            json.dump(ocr_result_data, f, ensure_ascii=False, indent=2)
        logger.info(f"OCR results saved to: {ocr_result_file}")
    except Exception as e:
        logger.error(f"Failed to save OCR results: {e}")

    return ocr_result_data


def _recognize_tables_in_result(
    task_id: str, ocr_result: Dict[str, Any], output_dir: str
) -> List[Dict[str, Any]]:
    """OCR 결과의 layout 블록에서 "table" 라벨 박스를 찾아 셀 구조 재구성.

    VLM 이 markdown 으로 변환한 표 외에, LORE++/gridline 으로 logical row/col 을 보장.

    Returns:
        각 표마다 {page_index, page_image, table_bbox_norm, rows, cols, cells, html, backend}
    """
    tables_meta: List[Dict[str, Any]] = []
    pages = ocr_result.get("pages") or []
    for page in pages:
        page_index = page.get("page_index")
        image_file = page.get("image_file")
        if not image_file or not os.path.exists(image_file):
            continue
        blocks = (page.get("layout") or {}).get("blocks") or []
        for block in blocks:
            if (block.get("layout_type") or "").lower() != "table":
                continue
            norm_box = block.get("layout_box") or []
            if len(norm_box) != 4:
                continue
            # norm 0..1000 → 픽셀
            try:
                import cv2  # local
                img = cv2.imread(image_file)
                if img is None:
                    continue
                h, w = img.shape[:2]
                x1 = int(norm_box[0] * w / 1000)
                y1 = int(norm_box[1] * h / 1000)
                x2 = int(norm_box[2] * w / 1000)
                y2 = int(norm_box[3] * h / 1000)
                structure = recognize_table(img, [x1, y1, x2, y2])
                tables_meta.append(
                    {
                        "page_index": page_index,
                        "page_image": image_file,
                        "block_index": block.get("index"),
                        "table_bbox": [x1, y1, x2, y2],
                        "table_bbox_norm": norm_box,
                        "rows": structure.rows,
                        "cols": structure.cols,
                        "backend": structure.backend,
                        "cells": [c.to_dict() for c in structure.cells],
                        "html": structure.html,
                    }
                )
            except Exception as e:
                logger.warning(
                    f"[{task_id}] table recognition skipped (page={page_index}, "
                    f"block={block.get('index')}): {e}"
                )
                continue
    return tables_meta
