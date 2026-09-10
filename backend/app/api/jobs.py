from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.api.schemas import (
    JobCreate,
    JobResummarizeRequest,
    JobResponse,
    JobResultResponse,
    TranscriptUpdateRequest,
    VideoPreviewRequest,
    VideoPreviewResponse,
)
from app.core.config import get_settings
from app.db.models import Job, User
from app.db.session import get_db
from app.services.downloader import VideoDownloader
from app.services.errors import classify_exception
from app.services.jobs import ARTIFACT_FILES, get_job, list_jobs, serialize_job
from app.services.domain import Transcript, TranscriptSegment
from app.services.exporters import export_all
from app.services.platforms import UnsafeURLError, detect_platform, validate_public_url
from app.services.setting_store import get_llm_config

router = APIRouter(prefix="/jobs", tags=["jobs"])

ALLOWED_UPLOAD_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v",
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus",
}
ALLOWED_ASR_MODELS = {"tiny", "base", "small", "medium", "large-v3"}
ALLOWED_SUMMARY_PRESETS = {
    "standard", "detailed", "course", "meeting", "interview", "knowledge", "short_copy", "transcript", "custom"
}


def _enqueue(job_id: str, mode: str = "process") -> None:
    settings = get_settings()
    if settings.queue_mode == "celery":
        if mode == "resummarize":
            from app.workers.celery_app import resummarize_job_task

            resummarize_job_task.delay(job_id)
        else:
            from app.workers.celery_app import process_job_task

            process_job_task.delay(job_id)


def _queue_failed(db: Session, job: Job) -> None:
    job.status = "failed"
    job.stage = "failed"
    job.error_code = "queue_error"
    job.error_message = "任务队列暂时不可用，请检查 Worker 和 Redis 后重试。"
    db.commit()
    db.refresh(job)


def _safe_filename(filename: str | None) -> str:
    name = Path(filename or "upload.bin").name.strip() or "upload.bin"
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]", "_", name)
    if len(name) > 180:
        suffix = Path(name).suffix
        name = f"{Path(name).stem[: max(1, 180 - len(suffix))]}{suffix}"
    return name


@router.post("/preview", response_model=VideoPreviewResponse)
def preview_video(
    payload: VideoPreviewRequest,
    _: User = Depends(current_user),
) -> VideoPreviewResponse:
    source_url = str(payload.source_url)
    try:
        validate_public_url(source_url)
        platform = detect_platform(source_url)
        preview = VideoDownloader().preview(source_url)
    except UnsafeURLError as exc:
        raise HTTPException(status_code=400, detail="该链接指向受限制的网络地址，无法处理。") from exc
    except Exception as exc:
        _, message = classify_exception(exc)
        raise HTTPException(status_code=400, detail=message) from exc
    metadata = preview.metadata
    return VideoPreviewResponse(
        source_url=source_url,
        platform=platform,
        title=preview.title,
        uploader=metadata.get("uploader"),
        duration=metadata.get("duration"),
        thumbnail=metadata.get("thumbnail"),
        extractor=metadata.get("extractor"),
    )


@router.post("/upload", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def upload_job(
    file: UploadFile = File(...),
    language: str = Form(""),
    asr_model: str = Form("small"),
    summary_enabled: bool = Form(True),
    summary_language: str = Form("Chinese"),
    summary_preset: str = Form("standard"),
    summary_instruction: str = Form(""),
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> JobResponse:
    settings = get_settings()
    filename = _safe_filename(file.filename)
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail="不支持该文件格式，请上传常见的视频或音频文件。")
    if asr_model not in ALLOWED_ASR_MODELS:
        raise HTTPException(status_code=400, detail="不支持该语音识别模型")
    if summary_preset not in ALLOWED_SUMMARY_PRESETS:
        raise HTTPException(status_code=400, detail="不支持该摘要模板")
    if summary_preset == "custom" and not summary_instruction.strip():
        raise HTTPException(status_code=400, detail="自定义摘要需要填写整理要求")

    job_id = str(uuid4())
    upload_root = (settings.data_dir / "uploads" / job_id).resolve()
    upload_root.mkdir(parents=True, exist_ok=False)
    target = (upload_root / filename).resolve()
    if upload_root not in target.parents:
        shutil.rmtree(upload_root, ignore_errors=True)
        raise HTTPException(status_code=400, detail="文件名无效")

    written = 0
    try:
        with target.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > settings.max_download_bytes:
                    raise HTTPException(status_code=413, detail="上传文件超过系统允许的最大大小")
                output.write(chunk)
    except Exception:
        shutil.rmtree(upload_root, ignore_errors=True)
        raise
    finally:
        await file.close()

    if written == 0:
        shutil.rmtree(upload_root, ignore_errors=True)
        raise HTTPException(status_code=400, detail="上传文件为空")

    job = Job(
        id=job_id,
        source_url=f"upload://{filename}",
        source_type="upload",
        source_filename=filename,
        source_path=str(target),
        platform="local",
        title=filename,
        language=language or None,
        asr_model=asr_model,
        summary_enabled=summary_enabled,
        summary_language=summary_language[:40] or "Chinese",
        summary_preset=summary_preset,
        summary_instruction=summary_instruction.strip()[:4000] or None,
        metadata_json=json.dumps({"title": filename, "size": written}, ensure_ascii=False),
        status="queued",
        stage="queued",
        progress=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        _enqueue(job.id)
    except Exception:
        _queue_failed(db, job)
    return JobResponse(**serialize_job(job))


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobCreate,
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> JobResponse:
    source_url = str(payload.source_url)
    if payload.summary_preset == "custom" and not (payload.summary_instruction or "").strip():
        raise HTTPException(status_code=400, detail="自定义摘要需要填写整理要求")
    try:
        validate_public_url(source_url)
    except UnsafeURLError as exc:
        raise HTTPException(status_code=400, detail="该链接指向受限制的网络地址，无法处理。") from exc
    job = Job(
        source_url=source_url,
        source_type="url",
        language=payload.language or None,
        asr_model=payload.asr_model or None,
        summary_enabled=payload.summary_enabled,
        summary_language=payload.summary_language,
        summary_preset=payload.summary_preset,
        summary_instruction=payload.summary_instruction,
        status="queued",
        stage="queued",
        progress=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    try:
        _enqueue(job.id)
    except Exception:
        _queue_failed(db, job)
    return JobResponse(**serialize_job(job))


@router.get("", response_model=list[JobResponse])
def get_jobs(
    limit: int = Query(default=100, ge=1, le=200),
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[JobResponse]:
    return [JobResponse(**serialize_job(job)) for job in list_jobs(db, limit=limit)]


@router.get("/{job_id}", response_model=JobResponse)
def get_job_detail(
    job_id: str,
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> JobResponse:
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return JobResponse(**serialize_job(job))


@router.get("/{job_id}/result", response_model=JobResultResponse)
def get_job_result(
    job_id: str,
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> JobResultResponse:
    job = get_job(db, job_id)
    if job is None or not job.output_dir:
        raise HTTPException(status_code=404, detail="任务结果不存在")
    root = Path(job.output_dir).resolve()
    allowed_root = (get_settings().data_dir / "jobs").resolve()
    if allowed_root not in root.parents:
        raise HTTPException(status_code=404, detail="任务结果不存在")
    result_path = root / "result.json"
    if not result_path.is_file():
        raise HTTPException(status_code=409, detail="任务尚未生成可阅读结果")
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="任务结果文件损坏或无法读取") from exc
    return JobResultResponse(**payload)


@router.put("/{job_id}/transcript", response_model=JobResultResponse)
def update_transcript(
    job_id: str,
    payload: TranscriptUpdateRequest,
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> JobResultResponse:
    """Persist user corrections and regenerate exports without rerunning ASR."""
    job = get_job(db, job_id)
    if job is None or not job.output_dir:
        raise HTTPException(status_code=404, detail="任务结果不存在")
    root = Path(job.output_dir).resolve()
    allowed_root = (get_settings().data_dir / "jobs").resolve()
    result_path = root / "result.json"
    if allowed_root not in root.parents or not result_path.is_file():
        raise HTTPException(status_code=404, detail="任务结果不存在")
    try:
        saved = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="任务结果文件损坏或无法读取") from exc
    segments = [TranscriptSegment(start=item.start, end=item.end, text=item.text.strip()) for item in payload.segments]
    if any(item.end < item.start for item in segments):
        raise HTTPException(status_code=400, detail="文字稿时间范围无效")
    transcript_data = saved.get("transcript") or {}
    transcript = Transcript(
        language=str(transcript_data.get("language") or job.language or "unknown"),
        language_probability=float(transcript_data.get("language_probability") or 0),
        duration=max(float(transcript_data.get("duration") or 0), max(item.end for item in segments)),
        segments=segments,
    )
    metadata = saved.get("metadata") if isinstance(saved.get("metadata"), dict) else {}
    # A transcript edit invalidates any prior AI wording. Keep exports usable and
    # let the user regenerate the summary from the corrected source.
    export_all(root, job.source_url, str(saved.get("platform") or job.platform or "generic"), str(saved.get("title") or job.title or "视频解析"), metadata, transcript, None)
    metadata = {**metadata, "transcript_edited": True, "summary_stale": bool(saved.get("summary"))}
    update_job(db, job.id, summary_excerpt=None, metadata_json=json.dumps(metadata, ensure_ascii=False))
    refreshed = json.loads(result_path.read_text(encoding="utf-8"))
    return JobResultResponse(**refreshed)


@router.post("/{job_id}/cancel", response_model=JobResponse)
def cancel_job(
    job_id: str,
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> JobResponse:
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status not in {"queued", "processing", "cancel_requested"}:
        raise HTTPException(status_code=409, detail="当前任务状态不能取消")
    if job.status == "queued":
        job.status = "cancelled"
        job.stage = "cancelled"
    else:
        # Cooperative cancellation: long-running FFmpeg/ASR/LLM calls may finish
        # their current operation before the worker observes this flag.
        job.status = "cancel_requested"
        job.stage = "cancel_requested"
    job.error_code = None
    job.error_message = None
    db.commit()
    db.refresh(job)
    return JobResponse(**serialize_job(job))


@router.post("/{job_id}/retry", response_model=JobResponse)
def retry_job(
    job_id: str,
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> JobResponse:
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status not in {"failed", "completed", "cancelled"}:
        raise HTTPException(status_code=409, detail="只有失败、已取消或已完成的任务可以重新执行")
    if job.source_type == "upload" and (not job.source_path or not Path(job.source_path).is_file()):
        raise HTTPException(status_code=409, detail="本地源文件已清理，不能重新执行完整流程；已完成任务仍可重新生成 AI 摘要。")
    job.status = "queued"
    job.stage = "queued"
    job.progress = 0
    job.error_code = None
    job.error_message = None
    job.completed_at = None
    db.commit()
    db.refresh(job)
    try:
        _enqueue(job.id)
    except Exception:
        _queue_failed(db, job)
    return JobResponse(**serialize_job(job))


@router.post("/{job_id}/resummarize", response_model=JobResponse)
def resummarize_job(
    job_id: str,
    payload: JobResummarizeRequest,
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> JobResponse:
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status not in {"completed", "failed"} or not job.output_dir:
        raise HTTPException(status_code=409, detail="只有已生成文字稿的任务才能重新生成摘要")
    if payload.summary_preset == "custom" and not (payload.summary_instruction or "").strip():
        raise HTTPException(status_code=400, detail="自定义摘要需要填写整理要求")
    if get_llm_config(db) is None:
        raise HTTPException(status_code=400, detail="尚未配置 AI API Key，请先在设置中配置并测试连接")
    result_path = Path(job.output_dir) / "result.json"
    if not result_path.is_file():
        raise HTTPException(status_code=409, detail="该任务没有可复用的文字稿结果")
    job.summary_enabled = True
    job.summary_language = payload.summary_language
    job.summary_preset = payload.summary_preset
    job.summary_instruction = payload.summary_instruction
    job.status = "queued"
    job.stage = "resummarize_queued"
    job.progress = 76
    job.error_code = None
    job.error_message = None
    job.completed_at = None
    db.commit()
    db.refresh(job)
    try:
        _enqueue(job.id, mode="resummarize")
    except Exception:
        _queue_failed(db, job)
    return JobResponse(**serialize_job(job))


@router.get("/{job_id}/artifacts/{artifact_name}")
def download_artifact(
    job_id: str,
    artifact_name: str,
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    filename = ARTIFACT_FILES.get(artifact_name)
    if filename is None:
        raise HTTPException(status_code=404, detail="未知文件类型")
    job = get_job(db, job_id)
    if job is None or not job.output_dir:
        raise HTTPException(status_code=404, detail="文件不存在")
    root = Path(job.output_dir).resolve()
    allowed_root = (get_settings().data_dir / "jobs").resolve()
    if allowed_root not in root.parents:
        raise HTTPException(status_code=404, detail="文件不存在")
    file_path = (root / filename).resolve()
    if root not in file_path.parents or not file_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(file_path, filename=f"{job_id}-{filename}")


@router.delete("/{job_id}", status_code=204)
def delete_job(
    job_id: str,
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    job = get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job.status in {"queued", "processing", "cancel_requested"}:
        raise HTTPException(status_code=409, detail="正在处理或取消中的任务不能删除")

    paths_to_remove: list[Path] = []
    if job.output_dir:
        paths_to_remove.append(Path(job.output_dir).resolve().parent)
    if job.source_type == "upload" and job.source_path:
        paths_to_remove.append(Path(job.source_path).resolve().parent)

    db.delete(job)
    db.commit()
    allowed_jobs = (get_settings().data_dir / "jobs").resolve()
    allowed_uploads = (get_settings().data_dir / "uploads").resolve()
    for root in paths_to_remove:
        if root.is_dir() and (allowed_jobs in root.parents or allowed_uploads in root.parents):
            shutil.rmtree(root, ignore_errors=True)
    return None
