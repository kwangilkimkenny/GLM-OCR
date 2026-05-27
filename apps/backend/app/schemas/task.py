"""
任务相关的Pydantic Schema
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Dict, Any, List
from datetime import datetime


class DocumentType(str, Enum):
    """우리카드 POC 문서 유형. 추출기/검증기 선택의 키로 사용한다.

    AUTO 는 vLLM 분류기로 자동 판별 후 위 4종 중 하나로 라우팅된다.
    """

    AUTO = "auto"                                  # 자동 감지 (Qwen2.5-VL 분류)
    MERCHANT_APPLICATION = "merchant_application"  # 가맹점 가입신청서
    ID_CARD = "id_card"                            # 신분증 (주민·운전·외국인)
    BANK_BOOK = "bank_book"                        # 통장 사본
    BUSINESS_REG = "business_reg"                  # 사업자등록증
    FREEFORM = "freeform"                          # 자유 업로드 (분류·추출 없이 raw OCR만)


class TaskSubmitRequest(BaseModel):
    """任务提交请求"""

    original_filename: str = Field(..., description="原始文件名")
    file_type: str = Field(..., description="文件类型")
    file_size: int = Field(..., gt=0, description="文件大小")
    file_path: str = Field(..., description="文件路径")
    processing_mode: str = Field(default="pipeline", description="处理模式")
    priority: int = Field(default=2, ge=1, le=4, description="优先级 (1-4)")
    ocr_config: Optional[Dict[str, Any]] = Field(default=None, description="OCR配置")
    output_format: str = Field(default="markdown", description="输出格式")
    retry_config: Optional[Dict[str, Any]] = Field(default=None, description="重试配置")
    document_type: DocumentType = Field(
        default=DocumentType.FREEFORM,
        description="우리카드 POC 문서 유형. 후처리 추출기 선택에 사용된다.",
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "original_filename": "document.pdf",
                "file_type": "pdf",
                "file_size": 1024000,
                "file_path": "/path/to/document.pdf",
                "processing_mode": "pipeline",
                "priority": 2,
                "ocr_config": {"dpi": 300, "image_format": "png", "language": "mixed"},
                "output_format": "markdown",
            }
        }
    )


class TaskSubmitResponse(BaseModel):
    """任务提交响应"""

    task_id: str
    status: str
    message: str


class TaskStatusResponse(BaseModel):
    """任务状态响应"""

    task_id: str
    document_id: str
    status: str
    progress: float
    current_step: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    error_message: Optional[str]
    result_file_path: Optional[str]
    processing_mode: str
    priority: int
    retry_count: int
    worker_id: Optional[str]
    metadata: Optional[Dict] = None
    full_markdown: Optional[str] = None
    layout: Optional[List] = None


class TaskInfo(BaseModel):
    """任务信息（用于列表）"""

    task_id: str
    document_id: str
    status: str
    progress: float
    current_step: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    processing_mode: str
    priority: int


class TaskListResponse(BaseModel):
    """任务列表响应"""

    tasks: List[TaskInfo]
    total: int


class TaskCancelResponse(BaseModel):
    """任务取消响应"""

    task_id: str
    status: str
    message: str
