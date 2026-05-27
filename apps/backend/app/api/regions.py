"""ROI(Region of Interest) OCR API.

사용자가 프론트엔드에서 드래그로 그린 영역만 잘라 vLLM 으로 보내고
영역별 텍스트를 돌려준다. 손글씨 hint 토글 지원.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.core.region_ocr import process_regions
from app.schemas.response import ApiResponse
from app.utils.config import settings
from app.utils.logger import logger
from app.utils.upload_file_manager import file_upload_handler


router = APIRouter(prefix="/tasks", tags=["regions"])


@router.post(
    "/region-ocr",
    response_model=ApiResponse[dict],
    status_code=status.HTTP_200_OK,
)
async def region_ocr(
    file: UploadFile = File(..., description="처리할 이미지 또는 PDF 한 페이지"),
    regions: str = Form(
        ...,
        description='JSON 배열. 예: [{"name":"applicant","bbox":[100,200,400,260],"handwriting":true}]',
    ),
    handwriting: bool = Form(
        True,
        description="기본 손글씨 prompt 사용 여부. 영역별로 override 가능 (region.handwriting).",
    ),
):
    """업로드한 이미지에서 지정 영역만 OCR.

    각 region 의 bbox 는 원본 픽셀 좌표 [x0, y0, x1, y1] 이어야 한다.
    """
    try:
        parsed = json.loads(regions)
        if not isinstance(parsed, list):
            raise ValueError("regions must be a JSON array")
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid regions JSON: {e}",
        )

    task_id = str(uuid.uuid4())
    save_dir = Path(settings.OUTPUT_DIR) / "region-ocr" / task_id
    save_dir.mkdir(parents=True, exist_ok=True)

    try:
        saved_path = await file_upload_handler.save_to_path(
            file=file,
            filename=file.filename,
            upload_dir=str(save_dir),
        )
    except Exception as e:
        logger.error(f"region-ocr: failed to save upload: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save upload: {e}",
        )

    # PDF 면 첫 페이지를 PNG 로 변환
    src_path = Path(saved_path)
    if src_path.suffix.lower() == ".pdf":
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(saved_path)
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            png_path = save_dir / "page_0001.png"
            pix.save(str(png_path))
            doc.close()
            image_path = str(png_path)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to render PDF page: {e}",
            )
    else:
        image_path = saved_path

    snapshot_dir = save_dir / "rois"
    results = await process_regions(
        image_path=image_path,
        regions=parsed,
        handwriting=handwriting,
        snapshot_dir=str(snapshot_dir),
    )

    summary: dict[str, Any] = {
        "task_id": task_id,
        "image_path": image_path,
        "region_count": len(results),
        "regions": results,
    }
    return ApiResponse(success=True, data=summary, message="Region OCR completed")
