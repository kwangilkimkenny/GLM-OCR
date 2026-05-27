"""
FastAPI应用入口
"""
import sys
from pathlib import Path


from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import asyncio

from app.api.tasks import router as tasks_router
from app.api.system import router as system_router
from app.api.regions import router as regions_router
from app.api.audit import router as audit_router
from app.core.cleanup_worker import cleanup_loop
from app.core.task_manager import init_task_system, shutdown_task_system
from app.db.database import init_db, close_db
from app.models import audit as _audit_model  # noqa: F401  — Base 에 테이블 등록
from app.utils.logger import logger
from app.utils.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理 + 자동 삭제 워커"""
    logger.info("Application starting up...")
    await init_db()
    await init_task_system()

    # 3-B 자동 삭제 워커 시작
    cleanup_stop = asyncio.Event()
    cleanup_task = asyncio.create_task(cleanup_loop(cleanup_stop))
    app.state.cleanup_stop = cleanup_stop
    app.state.cleanup_task = cleanup_task

    logger.info("Application startup complete")
    yield

    logger.info("Application shutting down...")
    cleanup_stop.set()
    try:
        await asyncio.wait_for(cleanup_task, timeout=5)
    except (asyncio.TimeoutError, Exception):
        cleanup_task.cancel()
    await shutdown_task_system()
    await close_db()
    logger.info("Application shutdown complete")


# 创建FastAPI应用
app = FastAPI(
    title=f"{settings.APP_NAME}",
    description="Async task execution system",
    version=settings.APP_VERSION,
    lifespan=lifespan
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(system_router, prefix="/api/v1")
app.include_router(regions_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "version": settings.APP_VERSION
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
