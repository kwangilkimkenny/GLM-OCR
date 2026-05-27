"""
系统监控API
"""
import json
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import desc, select

from app.schemas import MetricsResponse, HealthResponse
from app.schemas.response import ApiResponse
from app.core.cleanup_worker import cleanup_once, storage_summary
from app.core.task_manager import get_task_manager
from app.db.database import AsyncSessionLocal
from app.models.audit import AuditEntry
from app.models.task import Task, TaskStatus
from app.utils.logger import logger
from app.utils.config import settings


router = APIRouter(prefix="/system", tags=["system"])


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics():
    """
    获取系统指标

    返回任务和Worker的统计信息
    """
    try:
        task_manager = get_task_manager()
        metrics = await task_manager.get_metrics()

        # 直接返回，FastAPI会自动验证
        return metrics

    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get metrics: {str(e)}"
        )


@router.get("/storage", response_model=ApiResponse[dict])
async def get_storage_summary():
    """업로드 데이터 디스크 사용량 (자동 삭제 워커 메트릭)."""
    return ApiResponse(success=True, data=storage_summary(), message="OK")


@router.post("/storage/cleanup", response_model=ApiResponse[dict])
async def trigger_cleanup_now():
    """즉시 한 번 cleanup 실행 (시연 / 관리자용)."""
    return ApiResponse(success=True, data=cleanup_once(), message="cleanup executed")


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


@router.get("/metrics-summary", response_model=ApiResponse[dict])
async def metrics_summary(
    recent: int = Query(50, ge=1, le=500, description="최근 N개 task 기준 집계"),
):
    """최근 task 처리 통계 (시연 + 운영 관측용).

    집계 항목:
    - 최근 N개 task: 완료/실패/처리중 카운트
    - 평균 처리 시간(초)
    - 추출 결과의 grounding/cross_validation/pii 통계 평균
    - audit_log 의 action 분포
    """
    summary: dict[str, Any] = {
        "recent": recent,
        "tasks": {"completed": 0, "failed": 0, "processing": 0, "pending": 0, "other": 0},
        "avg_execution_seconds": 0.0,
        "grounding": {"avg_grounded_ratio": 0.0},
        "cross_validation": {"avg_conflict": 0.0, "avg_agreed": 0.0, "task_count": 0},
        "fields_per_task_avg": 0.0,
        "audit_actions": {},
    }

    async with AsyncSessionLocal() as db:
        stmt = select(Task).order_by(desc(Task.created_at)).limit(recent)
        rows = (await db.execute(stmt)).scalars().all()

        exec_times: list[float] = []
        grounded_ratios: list[float] = []
        conflicts: list[float] = []
        agreed: list[float] = []
        field_counts: list[int] = []

        for t in rows:
            status_counter = summary["tasks"]
            if t.status == TaskStatus.COMPLETED:
                status_counter["completed"] += 1
            elif t.status == TaskStatus.FAILED:
                status_counter["failed"] += 1
            elif t.status == TaskStatus.PROCESSING:
                status_counter["processing"] += 1
            elif t.status == TaskStatus.PENDING:
                status_counter["pending"] += 1
            else:
                status_counter["other"] += 1
            if t.started_at and t.completed_at:
                exec_times.append((t.completed_at - t.started_at).total_seconds())
            if not t.result_file_path:
                continue
            try:
                with open(t.result_file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            g = data.get("grounding") or {}
            grounded = g.get("grounded", 0) + g.get("normalized", 0)
            total_g = grounded + g.get("ungrounded", 0)
            if total_g:
                grounded_ratios.append(grounded / total_g)
            cv = data.get("cross_validation")
            if cv and isinstance(cv, dict):
                conflicts.append(float(cv.get("conflict") or 0))
                agreed.append(float(cv.get("agreed") or 0))
                summary["cross_validation"]["task_count"] += 1
            fields = ((data.get("extracted_fields") or {}).get("fields") or [])
            field_counts.append(len(fields))

        # audit 액션 분포
        audit_rows = (
            await db.execute(select(AuditEntry).order_by(desc(AuditEntry.created_at)).limit(200))
        ).scalars().all()
        ac = Counter(r.action for r in audit_rows)
        summary["audit_actions"] = dict(ac)

    summary["avg_execution_seconds"] = _avg(exec_times)
    summary["grounding"]["avg_grounded_ratio"] = _avg(grounded_ratios)
    summary["cross_validation"]["avg_conflict"] = _avg(conflicts)
    summary["cross_validation"]["avg_agreed"] = _avg(agreed)
    summary["fields_per_task_avg"] = _avg([float(n) for n in field_counts])
    return ApiResponse(success=True, data=summary, message="OK")


@router.get("/phase6-status", response_model=ApiResponse[dict])
async def phase6_status():
    """Phase 6 모듈(SR/텍스트검출/표구조) 백엔드 가용성.

    가중치/패키지 설치 상태 확인 + 자동 선택될 백엔드 안내.
    운영 모니터링 + 시연 자리 점검용.
    """
    from app.core import super_resolution, text_detection, table_structure

    # 캐시 무효화 후 fresh status (가중치를 런타임에 추가했을 수 있음)
    super_resolution._BACKENDS_CACHE = None

    sr_backends = [
        {"name": b.name, "available": b.available, "note": b.note}
        for b in super_resolution.list_backends()
    ]
    sr_chosen = super_resolution.select_backend().name

    data = {
        "super_resolution": {
            "backends": sr_backends,
            "auto_selected": sr_chosen,
            "weight_dir": str(super_resolution.SR_DIR),
        },
        "text_detection": text_detection.backend_status(),
        "table_structure": table_structure.backend_status(),
    }
    return ApiResponse(success=True, data=data, message="OK")


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    健康检查
    """
    try:
        task_manager = get_task_manager()

        return HealthResponse(
            status="healthy",
            task_manager_running=task_manager.is_running,
            workers_count=len(task_manager.workers),
            active_workers=sum(1 for w in task_manager.workers if w.is_running),
            version=settings.APP_VERSION
        )

    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return HealthResponse(
            status="unhealthy",
            error=str(e)
        )
