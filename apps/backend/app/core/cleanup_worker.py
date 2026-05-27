"""업로드 파일 자동 삭제 워커 — Phase 3-B.

OUTPUT_DIR 의 각 task 서브디렉토리를 RETENTION_MINUTES 보다 오래되면 삭제한다.
"테스트 환경 N분 후 자동 삭제" 시연 멘트와 짝.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path

from app.utils.config import settings
from app.utils.logger import logger


# 환경 변수로 override 가능
RETENTION_MINUTES = int(os.environ.get("WOORI_RETENTION_MINUTES", "30"))
CLEANUP_INTERVAL_SECONDS = int(os.environ.get("WOORI_CLEANUP_INTERVAL", "60"))

# 시연용 항상 보존 디렉토리 (region-ocr 결과 등 별도 보관 원하면 추가)
_PROTECTED_DIRS = {"region-ocr"}  # 하위는 자체 TTL 로 별도 관리해도 OK


def storage_summary() -> dict:
    """현재 OUTPUT_DIR 의 task 개수 / 합계 크기 / 가장 오래된 항목 시각."""
    base = Path(settings.OUTPUT_DIR)
    if not base.exists():
        return {"task_count": 0, "total_bytes": 0, "oldest_at": None, "retention_minutes": RETENTION_MINUTES}
    total = 0
    count = 0
    oldest = None
    for p in base.iterdir():
        if not p.is_dir() or p.name in _PROTECTED_DIRS:
            continue
        count += 1
        try:
            for root, _dirs, files in os.walk(p):
                for f in files:
                    fp = Path(root) / f
                    try:
                        total += fp.stat().st_size
                    except OSError:
                        pass
            mtime = p.stat().st_mtime
            if oldest is None or mtime < oldest:
                oldest = mtime
        except OSError:
            pass
    return {
        "task_count": count,
        "total_bytes": total,
        "total_mb": round(total / (1024 * 1024), 2),
        "oldest_at": oldest,
        "retention_minutes": RETENTION_MINUTES,
        "cleanup_interval_seconds": CLEANUP_INTERVAL_SECONDS,
    }


def _newest_mtime(path: Path) -> float:
    """디렉토리 트리 전체에서 가장 최근 mtime. 0 이면 stat 실패."""
    try:
        newest = path.stat().st_mtime
    except OSError:
        return 0.0
    for root, dirs, files in os.walk(path):
        for name in dirs + files:
            try:
                m = (Path(root) / name).stat().st_mtime
                if m > newest:
                    newest = m
            except OSError:
                pass
    return newest


def _is_expired(path: Path, ttl_seconds: int) -> bool:
    """트리 내 가장 최근 쓰기 기준으로 만료 판정.

    상위 task 디렉토리 mtime 만 보면, 하위 디렉토리에 파일을 계속 쓰는
    장시간 작업이 만료로 오판돼 진행 중에 삭제될 수 있다(race). 트리 전체의
    최신 mtime 을 liveness 신호로 사용해 활성 작업을 보호한다.
    """
    newest = _newest_mtime(path)
    if newest <= 0:
        return False
    return (time.time() - newest) > ttl_seconds


def cleanup_once() -> dict:
    """한 번 스캔해서 만료된 디렉토리 삭제. 통계 반환."""
    base = Path(settings.OUTPUT_DIR)
    if not base.exists():
        return {"deleted": 0, "kept": 0}
    ttl = RETENTION_MINUTES * 60
    deleted = 0
    kept = 0
    for p in base.iterdir():
        if not p.is_dir() or p.name in _PROTECTED_DIRS:
            continue
        if _is_expired(p, ttl):
            try:
                # 삭제 직전 재확인 — 판정과 rmtree 사이에 새 쓰기가 들어온 경우 보호.
                if not _is_expired(p, ttl):
                    kept += 1
                    continue
                shutil.rmtree(p)
                deleted += 1
                logger.info(f"cleanup_worker: deleted expired task dir {p.name}")
            except OSError as e:
                logger.warning(f"cleanup_worker: failed to delete {p}: {e}")
        else:
            kept += 1
    return {"deleted": deleted, "kept": kept}


async def cleanup_loop(stop_event: asyncio.Event) -> None:
    """주기적으로 cleanup_once 호출."""
    logger.info(
        f"cleanup_worker started: retention={RETENTION_MINUTES}min, interval={CLEANUP_INTERVAL_SECONDS}s"
    )
    while not stop_event.is_set():
        try:
            stats = cleanup_once()
            if stats["deleted"]:
                logger.info(f"cleanup_worker: {stats}")
        except Exception as e:
            logger.warning(f"cleanup_worker error: {e}")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=CLEANUP_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass
