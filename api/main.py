import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import Optional

from api.routers import requirements, files, stats, config

app = FastAPI(
    title="需求追溯链 API",
    description="半导体芯片需求追溯链管理系统后端 API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(requirements.router, prefix="/api/requirements", tags=["需求处理"])
app.include_router(files.router, prefix="/api/files", tags=["文件管理"])
app.include_router(stats.router, prefix="/api/stats", tags=["统计信息"])
app.include_router(config.router, prefix="/api/config", tags=["系统配置"])

os.makedirs(os.path.join(PROJECT_ROOT, "api/uploads"), exist_ok=True)
os.makedirs(os.path.join(PROJECT_ROOT, "api/output"), exist_ok=True)

app.mount("/uploads", StaticFiles(directory=os.path.join(PROJECT_ROOT, "api/uploads")), name="uploads")
app.mount("/output", StaticFiles(directory=os.path.join(PROJECT_ROOT, "api/output")), name="output")


@app.get("/")
async def root():
    return {
        "message": "需求追溯链 API 服务运行中",
        "version": "1.0.0",
        "docs": "/docs",
        "redoc": "/redoc"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
