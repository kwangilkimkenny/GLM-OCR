"""
结果合并步骤
"""

from typing import Dict, Any, List, Optional, Callable
from pathlib import Path
import json
import os

from app.core.flows.base import ProcessingContext
from app.core.extractors import consensus_merge, get_extractor
from app.core.seal_signature_matcher import verify_elements
from app.core.validators import (
    apply_grounding,
    apply_masking_policy,
    detect_pii_in_text,
)
from app.utils.logger import logger


def _to_json_safe(obj: Any) -> Any:
    """JSON 직렬화 불가능한 값(IFDRational, Fraction, set 등) 을 안전 타입으로 변환.

    스마트폰 사진의 EXIF 메타데이터가 metadata 에 흘러들어와 json.dump 가
    실패하는 케이스를 방어.
    """
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _to_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_json_safe(v) for v in obj]
    if isinstance(obj, set):
        return [_to_json_safe(v) for v in sorted(obj, key=str)]
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    # IFDRational, Fraction 등 numeric-like
    if hasattr(obj, "__float__"):
        try:
            return float(obj)
        except (TypeError, ValueError):
            pass
    return str(obj)


def _pages_to_markdown_and_layout(
    pages: list, image_url_base: str = "http://localhost:8000/api/v1/tasks/file"
) -> tuple[str, list]:
    """pages → (full_markdown, flat layout block list)."""
    md_lines: list[str] = []
    layout_blocks: list[dict] = []
    for page in pages:
        blocks = page.get("layout", {}).get("blocks", [])
        for block in blocks:
            text = block.get("content", "")
            layout_type = block.get("layout_type", "")
            # C5: stamp/signature 도 image_path 가 있으면 image 와 동일하게 <img> 로 렌더.
            # 그래야 HWPX 어댑터의 stamp/signature 블록이 UI 에서 보이고, extractor 가 placeholder 텍스트를 값으로 잘못 추출하지 않는다.
            if layout_type in ("image", "stamp", "signature", "seal", "sign"):
                img_path = block.get("image_path")
                if img_path and not os.path.isabs(img_path):
                    img_path = os.path.abspath(img_path)
                if img_path:
                    alt = layout_type.title()
                    text = f'<div style="text-align: center;"><img src="{image_url_base}?path={img_path}" alt="{alt}"/></div>\n'
                else:
                    # image_path 가 없는 stamp/signature — extractor 오염 방지 위해 빈 텍스트.
                    text = ""
            md_lines.append(f"{text}\n")
            layout_blocks.append(
                {
                    "block_content": text,
                    "bbox": block.get("layout_box"),
                    "block_id": block.get("index"),
                    "page_index": block.get("page_index"),
                    "layout_type": layout_type,
                }
            )
    return "".join(md_lines), layout_blocks


def _extract_stamps_and_signatures(layout_blocks: list[dict]) -> dict[str, list[dict]]:
    """PP-Layout 의 stamp/signature 클래스를 별도로 모은다 (워크플로우·시각화용)."""
    out: dict[str, list[dict]] = {"stamps": [], "signatures": [], "tables": []}
    for b in layout_blocks:
        t = (b.get("layout_type") or "").lower()
        entry = {
            "bbox": b.get("bbox"),
            "page_index": b.get("page_index"),
            "block_id": b.get("block_id"),
        }
        if t in {"stamp", "seal"}:
            out["stamps"].append(entry)
        elif t in {"signature", "sign"}:
            out["signatures"].append(entry)
        elif t == "table":
            out["tables"].append(entry)
    return out


class MergeResultsStepInput:
    ocr_result_path: str

    def __init__(self, ocr_result_path: str) -> None:
        self.ocr_result_path = ocr_result_path



async def merge_results(
    context: ProcessingContext,
    input: MergeResultsStepInput,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> Dict[str, Any]:
    """
    合并OCR结果

    Args:
        context: 处理上下文
        input: MergeResultsStepInput，包含 ocr_result_path
        progress_callback: 进度回调函数

    Returns:
        Dict[str, Any]: 合并后的结果
    """
    task_id = context.task_id
    output_format = context.output_format
    output_dir = context.get_output_dir()
    result_path = input.ocr_result_path
    logger.info(f"[{task_id}] Starting result merge")

    try:
        if progress_callback:
            await progress_callback(0.0, "Initializing merge")

        # 从文件读取OCR结果
        ocr_results = {}
        try:
            with open(result_path, "r", encoding="utf-8") as f:
                result_data = json.load(f)
                ocr_results.update(result_data)
        except Exception as e:
            logger.error(
                f"[{task_id}] Failed to read OCR result from {result_path}: {e}"
            )

        # 根据输出格式进行合并
        md_output_path, json_output_path = await _merge_to_markdown(
            context, ocr_results, output_dir, progress_callback
        )

        if progress_callback:
            await progress_callback(100.0, "Merge completed")

        result = {
            "md_output_path": md_output_path,
            "json_output_path": json_output_path,
            "output_files": [md_output_path, json_output_path],
            "metadata": {
                "format": output_format,
                "total_pages": len(ocr_results.get("pages", [])),
            },
        }

        logger.info(
            f"[{task_id}] Result merge completed: md_output_path:{md_output_path},json_output_path:{json_output_path}"
        )

        return result

    except Exception as e:
        logger.error(f"[{task_id}] Result merge failed: {e}")
        raise


async def _merge_to_markdown(
    context: ProcessingContext,
    ocr_results: Dict[str, Any],
    output_dir: str,
    progress_callback: Optional[Callable[[float, str], None]] = None,
):
    """合并为Markdown格式 (+ 우리카드 POC 필드 추출 + 비교 모드 합의)"""
    pages = ocr_results.get("pages", [])
    result: Dict[str, Any] = {"metadata": context.metadata}

    # 메인(또는 단일) 엔진 결과
    full_md, merge_res_layout = _pages_to_markdown_and_layout(pages)
    result["full_markdown"] = full_md
    result["layout"] = merge_res_layout
    # 도장/서명/표 별도 추적 (시각화·승인 워크플로우용)
    doc_elements = _extract_stamps_and_signatures(merge_res_layout)
    # Phase 4: 사전 등록 라이브러리와 도장/서명 유사도 비교 (옵션)
    if (context.ocr_config or {}).get("verify_seals", True):
        first_image = (pages[0] or {}).get("image_file") if pages else None
        if first_image:
            try:
                doc_elements = verify_elements(doc_elements, first_image)
            except Exception as e:
                logger.warning(f"[{context.task_id}] seal verify failed: {e}")
    result["doc_elements"] = doc_elements
    # Phase 2-C: layout_ocr 가 segments 를 만들었으면 그대로 노출
    if ocr_results.get("segments"):
        result["segments"] = ocr_results["segments"]

    if progress_callback:
        await progress_callback(100.0, f"Merging {len(pages)} pages")

    # 우리카드 POC: document_type 별 필드 추출
    document_type = (context.ocr_config or {}).get("document_type")
    engine = (context.ocr_config or {}).get("engine", "qwen")
    extractor = get_extractor(document_type)

    secondary_pages = ocr_results.get("secondary_pages")
    primary_engine = ocr_results.get("primary_engine", "qwen")
    secondary_engine = ocr_results.get("secondary_engine", "glm-ocr")

    masking_level = (context.ocr_config or {}).get("masking_level", "partial")
    if masking_level not in {"none", "partial", "full"}:
        masking_level = "partial"

    if extractor is not None:
        try:
            primary_extraction = extractor.extract(full_md, raw_blocks=merge_res_layout)

            if secondary_pages:
                # 비교 모드: 보조 엔진 결과도 추출 → 합의 병합
                secondary_md, secondary_layout = _pages_to_markdown_and_layout(
                    secondary_pages
                )
                secondary_extraction = extractor.extract(
                    secondary_md, raw_blocks=secondary_layout
                )

                merged, summary = consensus_merge(
                    primary_extraction,
                    secondary_extraction,
                    primary_engine=primary_engine,
                    secondary_engine=secondary_engine,
                )
                # Grounding: 두 엔진의 raw 텍스트 합본에서 검증
                grounding_stats = apply_grounding(
                    merged.fields, full_md + "\n" + secondary_md
                )
                masking_stats = apply_masking_policy(merged.fields, masking_level)
                result["extracted_fields"] = merged.to_dict()
                result["cross_validation"] = summary
                result["grounding"] = grounding_stats
                result["pii"] = {
                    "masking_level": masking_level,
                    "stats": masking_stats,
                    "extra_in_text": detect_pii_in_text(full_md),
                }
                # 보조 엔진의 raw markdown 도 응답에 노출 (side-by-side 비교용)
                result["secondary_markdown"] = secondary_md
                result["secondary_layout"] = secondary_layout
                logger.info(
                    f"[{context.task_id}] consensus: agreed={summary['agreed']} "
                    f"conflict={summary['conflict']} single={summary['single']} "
                    f"total={summary['total']}"
                )
            else:
                # 단일 엔진: grounding + PII 마스킹 적용
                grounding_stats = apply_grounding(primary_extraction.fields, full_md)
                masking_stats = apply_masking_policy(primary_extraction.fields, masking_level)
                result["extracted_fields"] = primary_extraction.to_dict()
                result["grounding"] = grounding_stats
                result["pii"] = {
                    "masking_level": masking_level,
                    "stats": masking_stats,
                    "extra_in_text": detect_pii_in_text(full_md),
                }
                logger.info(
                    f"[{context.task_id}] Extracted {len(primary_extraction.fields)} "
                    f"fields, grounded={grounding_stats['grounded']+grounding_stats['normalized']}/"
                    f"{sum(grounding_stats.values())}"
                )
        except Exception as e:
            logger.warning(f"[{context.task_id}] Field extraction failed: {e}")
            result["extracted_fields"] = {
                "document_type": document_type,
                "fields": [],
                "error": str(e),
            }

    # POC 메트릭
    if isinstance(result.get("metadata"), dict):
        result["metadata"]["document_type"] = document_type
        if secondary_pages:
            result["metadata"]["primary_engine"] = primary_engine
            result["metadata"]["secondary_engine"] = secondary_engine
        classified = ocr_results.get("classified")
        if classified:
            result["metadata"]["classified"] = classified

        # E3: source_format 우선순위 — 변환기-level (e.g. "hwp_via_libreoffice_to_hwpx") 가
        # 어댑터의 "hwpx_native" 보다 더 informative. metadata 의 값을 우선 채택하고,
        # 어댑터가 추가로 'hwpx_native' 표시를 주면 별도 필드 source_path 에 보존.
        meta_src = result["metadata"].get("source_format")
        adapter_src = ocr_results.get("source_format")
        if meta_src and adapter_src and meta_src != adapter_src:
            result["metadata"]["source_format"] = meta_src
            result["metadata"]["source_path"] = adapter_src
        elif adapter_src and not meta_src:
            result["metadata"]["source_format"] = adapter_src
        # else: meta_src 가 있으면 그대로, 없으면 그대로 (PDF/Image 경로)

        # C4: HWPX 네이티브 경로는 단일 엔진만 가능 — engine='both' 가 요청됐어도 무시됨.
        # metadata.engine 을 그에 맞게 정리하고, 'both' 였으면 경고 로그.
        hwpx_active = (
            isinstance(result["metadata"].get("source_format"), str)
            and result["metadata"]["source_format"].startswith("hwpx")
            or result["metadata"].get("source_path") == "hwpx_native"
        )
        if hwpx_active:
            if engine == "both":
                logger.warning(
                    f"[{context.task_id}] engine='both' was requested but HWPX native path "
                    f"is single-engine; cross_validation will be absent. "
                    f"metadata.engine downgraded to 'hwpx_native'."
                )
            result["metadata"]["engine"] = "hwpx_native"
        else:
            result["metadata"]["engine"] = engine

    # 写入文件
    md_output_path = str(Path(output_dir) / "result.md")
    with open(md_output_path, "w", encoding="utf-8") as f:
        f.write(full_md)
    json_output_path = str(Path(output_dir) / "merged.json")
    safe_result = _to_json_safe(result)
    with open(json_output_path, "w", encoding="utf-8") as f:
        json.dump(safe_result, f, ensure_ascii=False, indent=2)

    return md_output_path, json_output_path
