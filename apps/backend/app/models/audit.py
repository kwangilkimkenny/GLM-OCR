"""감사 로그 모델 — Phase 3-A.

평가자가 추출 결과를 수정·승인·거부한 이력을 영속화한다.
누가(IP/UA) 언제 어떤 task 의 어떤 필드를 어떻게 바꿨는지 기록.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditEntry(Base):
    """HITL 액션 영속화."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # edit/approve/reject/reset/mask_toggle/export
    field_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    value_from: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    value_to: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<AuditEntry({self.action} task={self.task_id} field={self.field_name})>"
