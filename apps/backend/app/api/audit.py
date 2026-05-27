"""감사 로그 API."""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from app.db.database import AsyncSessionLocal
from app.models.audit import AuditEntry
from app.schemas.response import ApiResponse


router = APIRouter(prefix="/audit", tags=["audit"])


class AuditCreate(BaseModel):
    task_id: Optional[str] = None
    action: str = Field(..., description="edit/approve/reject/reset/mask_toggle/export")
    field_name: Optional[str] = None
    value_from: Optional[str] = None
    value_to: Optional[str] = None
    note: Optional[str] = None


class AuditDTO(BaseModel):
    id: int
    task_id: Optional[str]
    action: str
    field_name: Optional[str]
    value_from: Optional[str]
    value_to: Optional[str]
    user_agent: Optional[str]
    ip_address: Optional[str]
    note: Optional[str]
    created_at: datetime


@router.post("", response_model=ApiResponse[AuditDTO], status_code=status.HTTP_201_CREATED)
async def create_audit(payload: AuditCreate, request: Request):
    ua = request.headers.get("user-agent")
    ip = request.client.host if request.client else None
    async with AsyncSessionLocal() as db:
        entry = AuditEntry(
            task_id=payload.task_id,
            action=payload.action,
            field_name=payload.field_name,
            value_from=payload.value_from,
            value_to=payload.value_to,
            user_agent=ua,
            ip_address=ip,
            note=payload.note,
        )
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
    return ApiResponse(
        success=True,
        data=AuditDTO(
            id=entry.id,
            task_id=entry.task_id,
            action=entry.action,
            field_name=entry.field_name,
            value_from=entry.value_from,
            value_to=entry.value_to,
            user_agent=entry.user_agent,
            ip_address=entry.ip_address,
            note=entry.note,
            created_at=entry.created_at,
        ),
        message="Audit entry created",
    )


@router.get("", response_model=ApiResponse[dict])
async def list_audit(
    task_id: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
):
    async with AsyncSessionLocal() as db:
        stmt = select(AuditEntry).order_by(desc(AuditEntry.created_at))
        if task_id:
            stmt = stmt.where(AuditEntry.task_id == task_id)
        stmt = stmt.limit(limit).offset(offset)
        rows = (await db.execute(stmt)).scalars().all()
    items: list[dict[str, Any]] = []
    for r in rows:
        items.append(
            {
                "id": r.id,
                "task_id": r.task_id,
                "action": r.action,
                "field_name": r.field_name,
                "value_from": r.value_from,
                "value_to": r.value_to,
                "user_agent": r.user_agent,
                "ip_address": r.ip_address,
                "note": r.note,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return ApiResponse(
        success=True,
        data={"items": items, "total": len(items), "limit": limit, "offset": offset},
        message="OK",
    )
