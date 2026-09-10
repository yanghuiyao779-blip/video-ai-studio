from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.models import Job

ARTIFACT_FILES = {
    "markdown": "result.md",
    "txt": "transcript.txt",
    "srt": "subtitles.srt",
    "vtt": "subtitles.vtt",
    "json": "result.json",
    "docx": "result.docx",
    "zip": "all-files.zip",
}


def get_job(db: Session, job_id: str) -> Job | None:
    return db.get(Job, job_id)


def list_jobs(db: Session, limit: int = 100) -> list[Job]:
    return list(db.scalars(select(Job).order_by(desc(Job.created_at)).limit(limit)))


def update_job(db: Session, job_id: str, **fields) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise RuntimeError(f"Job {job_id} not found")
    for key, value in fields.items():
        setattr(job, key, value)
    job.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)
    return job


def complete_job(db: Session, job_id: str, **fields) -> Job:
    fields.update(
        status="completed",
        stage="completed",
        progress=100,
        completed_at=datetime.now(timezone.utc),
        error_code=None,
        error_message=None,
    )
    return update_job(db, job_id, **fields)


def fail_job(db: Session, job_id: str, message: str, code: str = "processing_error") -> Job:
    safe_message = message.strip()[-2000:] if message else "处理失败"
    return update_job(
        db,
        job_id,
        status="failed",
        stage="failed",
        error_code=code,
        error_message=safe_message,
    )


def metadata_dict(job: Job) -> dict | None:
    if not job.metadata_json:
        return None
    try:
        return json.loads(job.metadata_json)
    except json.JSONDecodeError:
        return None


def artifact_links(job: Job) -> dict[str, str]:
    if not job.output_dir:
        return {}
    root = Path(job.output_dir)
    links: dict[str, str] = {}
    for name, filename in ARTIFACT_FILES.items():
        if (root / filename).is_file():
            links[name] = f"/api/jobs/{job.id}/artifacts/{name}"
    return links


def serialize_job(job: Job) -> dict:
    return {
        "id": job.id,
        "source_url": job.source_url,
        "source_type": job.source_type or "url",
        "source_filename": job.source_filename,
        "platform": job.platform,
        "title": job.title,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "language": job.language,
        "asr_model": job.asr_model,
        "summary_enabled": job.summary_enabled,
        "summary_language": job.summary_language,
        "summary_preset": job.summary_preset or "standard",
        "summary_instruction": job.summary_instruction,
        "summary_excerpt": job.summary_excerpt,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "metadata": metadata_dict(job),
        "artifacts": artifact_links(job),
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
    }
