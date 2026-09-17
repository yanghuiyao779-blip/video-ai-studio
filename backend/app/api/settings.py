import httpx
import shutil
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.api.schemas import LLMSettingsIn, LLMSettingsOut, LLMTestResponse, StorageStats, TaskDefaults
from app.core.config import get_settings
from app.db.models import Job, User
from app.db.session import get_db
from app.services.llm import OpenAICompatibleLLM
from app.services.setting_store import get_llm_config, llm_public_view, task_defaults_public_view, update_llm_config, update_task_defaults

router = APIRouter(prefix="/settings", tags=["settings"])


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            # A worker may delete a temporary file while statistics are read.
            continue
    return total


def _rag_index_size(db: Session) -> int:
    """Return the PostgreSQL table plus index size; SQLite/dev mode has none."""
    try:
        # A savepoint keeps the request usable when RAG migration 0005 has
        # not yet been applied in a development database.
        with db.begin_nested():
            value = db.execute(text("SELECT pg_total_relation_size('creator_corpus_chunks')")).scalar()
        return int(value or 0)
    except Exception:
        return 0


def _storage_stats(db: Session, freed_temporary_bytes: int = 0) -> StorageStats:
    settings = get_settings()
    data_dir = settings.data_dir.resolve()
    jobs_dir = data_dir / "jobs"
    uploads_dir = data_dir / "uploads"
    creators_dir = data_dir / "creators"
    models_dir = Path("/models")
    profile_dir = settings.douyin_profile_dir
    task_results = 0
    temporary = 0
    removable = 0
    active_ids = set(db.scalars(select(Job.id).where(Job.status.in_({"queued", "processing", "cancel_requested"}))))
    for job_dir in (jobs_dir.iterdir() if jobs_dir.exists() else []):
        if not job_dir.is_dir():
            continue
        work_dir = job_dir / "work"
        # Result storage and transient work are intentionally mutually
        # exclusive, so the UI does not count the same bytes twice.
        for item in job_dir.rglob("*"):
            try:
                if item.is_file() and work_dir not in item.parents:
                    task_results += item.stat().st_size
            except OSError:
                continue
        size = _directory_size(work_dir)
        temporary += size
        if job_dir.name not in active_ids:
            removable += size
    disk_free = shutil.disk_usage(data_dir).free
    return StorageStats(
        data_dir=str(data_dir), total_bytes=_directory_size(data_dir),
        task_results_bytes=task_results, jobs_bytes=task_results + temporary,
        uploads_bytes=_directory_size(uploads_dir), creator_artifacts_bytes=_directory_size(creators_dir),
        rag_index_bytes=_rag_index_size(db), playwright_profile_bytes=_directory_size(profile_dir),
        models_bytes=_directory_size(models_dir), temporary_bytes=temporary, disk_free_bytes=disk_free,
        removable_temporary_bytes=removable, freed_temporary_bytes=freed_temporary_bytes,
        measured_at=datetime.now(timezone.utc),
    )


@router.get("/llm", response_model=LLMSettingsOut)
def get_llm_settings(
    _: User = Depends(current_user), db: Session = Depends(get_db)
) -> LLMSettingsOut:
    return LLMSettingsOut(**llm_public_view(db))


@router.put("/llm", response_model=LLMSettingsOut)
def put_llm_settings(
    payload: LLMSettingsIn,
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> LLMSettingsOut:
    update_llm_config(
        db,
        provider=payload.provider,
        base_url=payload.base_url,
        model=payload.model,
        api_key=payload.api_key,
        temperature=payload.temperature,
        custom_prompt=payload.custom_prompt,
        embedding_model=payload.embedding_model,
        clear_api_key=payload.clear_api_key,
    )
    return LLMSettingsOut(**llm_public_view(db))


@router.post("/llm/test", response_model=LLMTestResponse)
def test_llm_settings(
    _: User = Depends(current_user), db: Session = Depends(get_db)
) -> LLMTestResponse:
    config = get_llm_config(db)
    if config is None:
        raise HTTPException(status_code=400, detail="尚未配置 AI API Key")
    try:
        with OpenAICompatibleLLM(config) as client:
            result = client.test()
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        if code in {401, 403}:
            detail = "AI 服务鉴权失败，请检查 API Key、Base URL 和模型名称"
        elif code == 429:
            detail = "AI 服务请求过于频繁或额度受限，请稍后再试"
        else:
            detail = f"AI 服务返回 HTTP {code}，请检查服务商配置"
        raise HTTPException(status_code=400, detail=detail) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"连接测试失败：{str(exc)[:240]}") from exc
    return LLMTestResponse(ok=True, message=f"连接成功：{result[:80]}")


@router.get("/task-defaults", response_model=TaskDefaults)
def get_task_defaults(_: User = Depends(current_user), db: Session = Depends(get_db)) -> TaskDefaults:
    return TaskDefaults(**task_defaults_public_view(db))


@router.put("/task-defaults", response_model=TaskDefaults)
def put_task_defaults(payload: TaskDefaults, _: User = Depends(current_user), db: Session = Depends(get_db)) -> TaskDefaults:
    update_task_defaults(db, payload.model_dump())
    return TaskDefaults(**task_defaults_public_view(db))


@router.get("/storage", response_model=StorageStats)
def get_storage(_: User = Depends(current_user), db: Session = Depends(get_db)) -> StorageStats:
    return _storage_stats(db)


@router.delete("/storage/temporary", response_model=StorageStats)
def clean_temporary(_: User = Depends(current_user), db: Session = Depends(get_db)) -> StorageStats:
    before = _storage_stats(db)
    settings = get_settings()
    active_ids = set(db.scalars(select(Job.id).where(Job.status.in_({"queued", "processing", "cancel_requested"}))))
    for work_dir in (settings.data_dir / "jobs").glob("*/work"):
        if work_dir.parent.name not in active_ids:
            shutil.rmtree(work_dir, ignore_errors=True)
    after = _storage_stats(db)
    return after.model_copy(update={"freed_temporary_bytes": max(0, before.removable_temporary_bytes - after.removable_temporary_bytes)})
