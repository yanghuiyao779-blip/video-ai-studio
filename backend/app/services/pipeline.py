from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from app.core.config import get_settings
from app.db.models import Job, User
from app.db.session import SessionLocal
from app.services.asr import transcribe
from app.services.domain import Transcript, TranscriptSegment
from app.services.downloader import VideoDownloader
from app.services.errors import classify_exception
from app.services.exporters import export_all
from app.services.jobs import complete_job, fail_job, update_job
from app.services.media import binary_available, extract_audio
from app.services.platforms import detect_platform, validate_public_url
from app.services.setting_store import get_llm_config
from app.services.summarizer import summarize_transcript

logger = logging.getLogger(__name__)


class JobCancelled(RuntimeError):
    pass


def _cancellation_requested(job_id: str) -> bool:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        return bool(job and job.status in {"cancel_requested", "cancelled"})


def _mark_cancelled(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return
        update_job(
            db,
            job_id,
            status="cancelled",
            stage="cancelled",
            error_code=None,
            error_message=None,
        )


def _fail(job_id: str, exc: Exception) -> None:
    if _cancellation_requested(job_id):
        logger.info("Job %s cancelled by user", job_id)
        _mark_cancelled(job_id)
        return
    logger.exception("Job %s failed", job_id)
    code, message = classify_exception(exc)
    with SessionLocal() as db:
        fail_job(db, job_id, message, code=code)
    # Source media and extracted audio are transient by default.  A failed
    # task used to leave its work directory forever; keep it only when the
    # administrator explicitly enables source-media retention.
    settings = get_settings()
    if not settings.keep_source_media:
        shutil.rmtree(settings.data_dir / "jobs" / job_id / "work", ignore_errors=True)


def _validated_upload_path(source_path: str, job_id: str) -> Path:
    settings = get_settings()
    path = Path(source_path).resolve()
    allowed = (settings.data_dir / "uploads" / job_id).resolve()
    if allowed not in path.parents or not path.is_file():
        raise RuntimeError("Uploaded source file was not found")
    if path.stat().st_size > settings.max_download_bytes:
        raise RuntimeError("Uploaded media exceeds configured size limit")
    return path


def process_job(job_id: str) -> None:
    settings = get_settings()
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None or job.status == "cancelled":
            return
        if job.status == "cancel_requested":
            _mark_cancelled(job_id)
            return
        owner = db.get(User, job.owner_id) if job.owner_id else None
        allow_server_credentials = bool(owner and owner.username == settings.admin_username)
        source_url = job.source_url
        source_type = job.source_type or "url"
        source_path = job.source_path
        source_filename = job.source_filename
        requested_model = job.asr_model or settings.asr_model
        requested_language = job.language or None
        summary_enabled = job.summary_enabled
        summary_language = job.summary_language
        summary_preset = job.summary_preset or "standard"
        summary_instruction = job.summary_instruction

    job_root = settings.data_dir / "jobs" / job_id
    work_dir = job_root / "work"
    output_dir = job_root / "output"
    if job_root.exists():
        shutil.rmtree(job_root)
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    def progress(value: int, stage: str) -> None:
        with SessionLocal() as progress_db:
            current = progress_db.get(Job, job_id)
            if current is None:
                raise JobCancelled("Job no longer exists")
            if current.status in {"cancel_requested", "cancelled"}:
                raise JobCancelled("Job cancelled by user")
            update_job(
                progress_db,
                job_id,
                status="processing",
                stage=stage,
                progress=max(0, min(99, int(value))),
                output_dir=str(output_dir),
                error_code=None,
                error_message=None,
            )

    try:
        if not binary_available(settings.ffmpeg_binary):
            raise RuntimeError("ffmpeg binary was not found")
        if not binary_available(settings.ffprobe_binary):
            raise RuntimeError("ffprobe binary was not found")

        if source_type == "upload":
            progress(6, "loading_upload")
            if not source_path:
                raise RuntimeError("Uploaded source file was not found")
            media_path = _validated_upload_path(source_path, job_id)
            platform = "local"
            title = source_filename or media_path.name
            download_metadata = {
                "title": title,
                "size": media_path.stat().st_size,
                "source_type": "upload",
            }
            with SessionLocal() as db:
                update_job(
                    db,
                    job_id,
                    platform=platform,
                    title=title,
                    metadata_json=json.dumps(download_metadata, ensure_ascii=False),
                )
        else:
            progress(2, "validating_url")
            validate_public_url(source_url)
            platform = detect_platform(source_url)
            with SessionLocal() as db:
                update_job(db, job_id, platform=platform)

            progress(8, "downloading")
            download = VideoDownloader(progress=progress, allow_server_credentials=allow_server_credentials).download(source_url, work_dir)
            media_path = download.file_path
            title = download.title
            download_metadata = download.metadata
            with SessionLocal() as db:
                update_job(
                    db,
                    job_id,
                    title=download.title,
                    metadata_json=json.dumps(download.metadata, ensure_ascii=False),
                )

        from app.services.assistant_tools import capture_video_frames
        capture_video_frames(job_id, media_path)

        progress(34, "extracting_audio")
        audio_path = extract_audio(media_path, work_dir / "audio.wav")

        progress(44, "transcribing")
        transcript = transcribe(audio_path, requested_model, requested_language)
        if not transcript.segments:
            raise RuntimeError("No speech was detected in the media")
        progress(76, "segmenting")

        # Persist the transcript before any external LLM call. If the AI provider
        # later fails, users can still read/download the transcript and retry only
        # the summary instead of repeating download, FFmpeg and ASR work.
        progress(78, "saving_transcript")
        export_all(
            output_dir=output_dir,
            source_url=source_url,
            platform=platform,
            title=title,
            metadata=download_metadata,
            transcript=transcript,
            summary=None,
        )

        summary: str | None = None
        if summary_enabled and summary_preset != "transcript":
            with SessionLocal() as db:
                llm_config = get_llm_config(db)
            if llm_config is not None:
                progress(80, "summarizing")
                summary = summarize_transcript(
                    transcript.segments,
                    llm_config,
                    summary_language,
                    summary_preset=summary_preset,
                    summary_instruction=summary_instruction,
                    progress=progress,
                )
            else:
                progress(94, "summary_skipped_no_api_key")
        else:
            progress(94, "summary_disabled")

        progress(97, "exporting")
        export_all(
            output_dir=output_dir,
            source_url=source_url,
            platform=platform,
            title=title,
            metadata=download_metadata,
            transcript=transcript,
            summary=summary,
        )
        excerpt = summary[:500] if summary else None
        result_metadata = dict(download_metadata)
        result_metadata.update(
            {
                "transcript_language": transcript.language,
                "transcript_duration": transcript.duration,
                "segment_count": len(transcript.segments),
                "summary_generated": bool(summary),
            }
        )
        if not settings.keep_source_media:
            shutil.rmtree(work_dir, ignore_errors=True)
            if source_type == "upload" and source_path:
                upload_root = Path(source_path).resolve().parent
                allowed_uploads = (settings.data_dir / "uploads").resolve()
                if allowed_uploads in upload_root.parents:
                    shutil.rmtree(upload_root, ignore_errors=True)
        with SessionLocal() as db:
            complete_job(
                db,
                job_id,
                title=title,
                platform=platform,
                summary_excerpt=excerpt,
                metadata_json=json.dumps(result_metadata, ensure_ascii=False),
                output_dir=str(output_dir),
            )
    except JobCancelled:
        logger.info("Job %s cancelled by user", job_id)
        _mark_cancelled(job_id)
        if not settings.keep_source_media:
            shutil.rmtree(work_dir, ignore_errors=True)
    except Exception as exc:
        _fail(job_id, exc)


def resummarize_job(job_id: str) -> None:
    """Regenerate only the AI summary from the persisted transcript result."""
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None or job.status == "cancelled":
            return
        if job.status == "cancel_requested":
            _mark_cancelled(job_id)
            return
        output_dir = Path(job.output_dir or "")
        summary_language = job.summary_language
        summary_preset = job.summary_preset or "standard"
        summary_instruction = job.summary_instruction

    result_path = output_dir / "result.json"

    def progress(value: int, stage: str) -> None:
        with SessionLocal() as progress_db:
            current = progress_db.get(Job, job_id)
            if current is None:
                raise JobCancelled("Job no longer exists")
            if current.status in {"cancel_requested", "cancelled"}:
                raise JobCancelled("Job cancelled by user")
            update_job(
                progress_db,
                job_id,
                status="processing",
                stage=stage,
                progress=max(0, min(99, int(value))),
                error_code=None,
                error_message=None,
            )

    try:
        progress(78, "loading_transcript")
        if not result_path.is_file():
            raise RuntimeError("Persisted transcript result was not found")
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        transcript_data = payload.get("transcript") or {}
        segments = [
            TranscriptSegment(
                start=float(item.get("start", 0)),
                end=float(item.get("end", 0)),
                text=str(item.get("text", "")).strip(),
            )
            for item in transcript_data.get("segments", [])
            if str(item.get("text", "")).strip()
        ]
        if not segments:
            raise RuntimeError("No persisted transcript is available for re-summarization")

        with SessionLocal() as db:
            llm_config = get_llm_config(db)
        if llm_config is None:
            raise RuntimeError("No LLM API key configured")

        progress(82, "resummarizing")

        def summary_progress(value: int, stage: str) -> None:
            stage_map = {
                "summarizing": "resummarizing",
                "synthesizing_summary": "resynthesizing_summary",
            }
            progress(value, stage_map.get(stage, stage))

        summary = summarize_transcript(
            segments,
            llm_config,
            summary_language,
            summary_preset=summary_preset,
            summary_instruction=summary_instruction,
            progress=summary_progress,
        )

        progress(97, "reexporting")
        transcript = Transcript(
            language=str(transcript_data.get("language") or "unknown"),
            language_probability=transcript_data.get("language_probability"),
            duration=float(transcript_data.get("duration") or (segments[-1].end if segments else 0)),
            segments=segments,
        )
        export_all(
            output_dir=output_dir,
            source_url=str(payload.get("source_url") or ""),
            platform=str(payload.get("platform") or "unknown"),
            title=str(payload.get("title") or "未命名视频"),
            metadata=payload.get("metadata") or {},
            transcript=transcript,
            summary=summary,
        )
        with SessionLocal() as db:
            complete_job(db, job_id, summary_excerpt=summary[:500])
    except JobCancelled:
        logger.info("Job %s cancelled by user", job_id)
        _mark_cancelled(job_id)
    except Exception as exc:
        _fail(job_id, exc)
