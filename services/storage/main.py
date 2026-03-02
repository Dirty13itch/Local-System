"""Storage Service — file management and model repository.

Manages the 180TB HDD array and NVMe storage on VAULT.
Provides file upload/download, model distribution, and storage metrics.
"""

from __future__ import annotations

import hashlib
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import aiofiles
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

from local_system.config import get_settings
from local_system.models import HealthResponse
from local_system.utils import generate_id, setup_logging

settings = get_settings()
logger = setup_logging("storage", settings)

DATA_DIR = Path(os.getenv("STORAGE_DATA_DIR", "/data"))
MODELS_DIR = DATA_DIR / "models"
FILES_DIR = DATA_DIR / "files"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Storage service starting")
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    app.state.start_time = time.time()
    # In-memory file index (would be backed by PostgreSQL in production)
    app.state.file_index: dict[str, dict] = {}
    app.state.model_index: dict[str, dict] = {}
    yield
    logger.info("Storage service stopped")


app = FastAPI(
    title="Local-System Storage",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> HealthResponse:
    return HealthResponse(
        service="storage",
        node=settings.node.name.value,
        uptime_seconds=time.time() - app.state.start_time,
    )


# --- File Operations ---


@app.post("/v1/files/upload")
async def upload_file(file: UploadFile = File(...)) -> dict:
    """Upload a file to storage."""
    file_id = generate_id("file")
    filename = file.filename or "unnamed"
    dest = FILES_DIR / file_id / filename
    dest.parent.mkdir(parents=True, exist_ok=True)

    sha256 = hashlib.sha256()
    size = 0

    async with aiofiles.open(dest, "wb") as f:
        while chunk := await file.read(8192):
            await f.write(chunk)
            sha256.update(chunk)
            size += len(chunk)

    entry = {
        "id": file_id,
        "filename": filename,
        "path": str(dest),
        "size_bytes": size,
        "checksum": sha256.hexdigest(),
        "content_type": file.content_type or "application/octet-stream",
        "created_at": time.time(),
    }
    app.state.file_index[file_id] = entry

    logger.info(f"File uploaded: {filename} ({size} bytes)")
    return entry


@app.get("/v1/files/{file_id}")
async def get_file_info(file_id: str) -> dict:
    entry = app.state.file_index.get(file_id)
    if not entry:
        raise HTTPException(status_code=404, detail="File not found")
    return entry


@app.get("/v1/files/{file_id}/download")
async def download_file(file_id: str) -> FileResponse:
    entry = app.state.file_index.get(file_id)
    if not entry:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        entry["path"],
        filename=entry["filename"],
        media_type=entry["content_type"],
    )


@app.delete("/v1/files/{file_id}")
async def delete_file(file_id: str) -> dict:
    entry = app.state.file_index.pop(file_id, None)
    if not entry:
        raise HTTPException(status_code=404, detail="File not found")
    path = Path(entry["path"])
    if path.exists():
        path.unlink()
        if path.parent.exists() and not any(path.parent.iterdir()):
            path.parent.rmdir()
    return {"deleted": True, "id": file_id}


@app.get("/v1/files")
async def list_files(limit: int = 100, offset: int = 0) -> dict:
    files = list(app.state.file_index.values())
    return {
        "files": files[offset : offset + limit],
        "total": len(files),
    }


# --- Model Repository ---


@app.post("/v1/models/register")
async def register_model(body: dict) -> dict:
    """Register a model in the repository."""
    model_id = generate_id("model")
    entry = {
        "id": model_id,
        "name": body.get("name", ""),
        "backend": body.get("backend", "ollama"),
        "file_id": body.get("file_id"),
        "quantization": body.get("quantization", ""),
        "parameter_count": body.get("parameter_count", ""),
        "context_length": body.get("context_length", 4096),
        "registered_at": time.time(),
    }
    app.state.model_index[model_id] = entry
    return entry


@app.get("/v1/models")
async def list_models() -> list[dict]:
    return list(app.state.model_index.values())


@app.get("/v1/models/{model_id}")
async def get_model(model_id: str) -> dict:
    entry = app.state.model_index.get(model_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Model not found")
    return entry


# --- Storage Metrics ---


@app.get("/v1/storage/stats")
async def storage_stats() -> dict:
    """Get storage usage statistics."""
    stats = {}
    for name, path in [("data", DATA_DIR), ("models", MODELS_DIR), ("files", FILES_DIR)]:
        try:
            usage = os.statvfs(path)
            total = usage.f_blocks * usage.f_frsize
            free = usage.f_bfree * usage.f_frsize
            used = total - free
            stats[name] = {
                "total_gb": round(total / (1024**3), 2),
                "used_gb": round(used / (1024**3), 2),
                "free_gb": round(free / (1024**3), 2),
                "percent_used": round((used / total) * 100, 1) if total > 0 else 0,
            }
        except Exception:
            stats[name] = {"error": "path not available"}
    return stats
