"""Creator-level orchestration built on top of the existing video Job pipeline."""
from __future__ import annotations

import hashlib
import json
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import yt_dlp
import redis
from sqlalchemy import func, select
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    Creator, CreatorAnalysisRun, CreatorResearchRun, CreatorSkillVersion, CreatorSyncRun, CreatorVideo,
    Job, VideoInsight,
)
from app.db.session import SessionLocal
from app.services.chunking import chunk_segments
from app.services.llm import OpenAICompatibleLLM
from app.services.platforms import detect_platform, validate_public_url
from app.services.setting_store import get_llm_config
from app.services.douyin_resolver import resolve_douyin_creator

INSIGHT_EXTRACTOR_VERSION = "v1"
PROFILE_PROMPT_VERSION = "v1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json(value: str | None, fallback):
    try:
        return json.loads(value) if value else fallback
    except json.JSONDecodeError:
        return fallback


def _parse_json(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.I)
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("LLM did not return a JSON object")
    return parsed


def _video_id(url: str) -> str:
    # Douyin canonical URLs contain a decimal id. Other platforms retain a
    # stable URL-derived key so manual imports remain idempotent.
    match = re.search(r"/(?:video|note)/(\d{8,40})(?:/|$|\?)", url)
    if match:
        return match.group(1)
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:40]


def _serialize_creator(db: Session, creator: Creator) -> dict:
    videos = db.scalar(select(func.count()).select_from(CreatorVideo).where(CreatorVideo.creator_id == creator.id)) or 0
    transcripts = db.scalar(
        select(func.count()).select_from(CreatorVideo).join(Job, CreatorVideo.job_id == Job.id).where(
            CreatorVideo.creator_id == creator.id, Job.status == "completed"
        )
    ) or 0
    insights = db.scalar(
        select(func.count()).select_from(VideoInsight).join(CreatorVideo).where(
            CreatorVideo.creator_id == creator.id, VideoInsight.status == "completed"
        )
    ) or 0
    return {
        "id": creator.id, "platform": creator.platform, "profile_url": creator.profile_url,
        "platform_creator_id": creator.platform_creator_id, "name": creator.name,
        "avatar_url": creator.avatar_url, "status": creator.status,
        "last_synced_at": creator.last_synced_at, "video_count": videos,
        "transcript_count": transcripts, "insight_count": insights,
        "created_at": creator.created_at, "updated_at": creator.updated_at,
    }


def _serialize_sync_run(run: CreatorSyncRun | None) -> dict | None:
    if run is None:
        return None
    return {
        "id": run.id, "status": run.status, "discovered_count": run.discovered_count,
        "created_count": run.created_count, "error_message": run.error_message,
        "created_at": run.created_at, "completed_at": run.completed_at,
    }


def _serialize_research_run(run: CreatorResearchRun | None) -> dict | None:
    if run is None:
        return None
    return {
        "id": run.id, "creator_id": run.creator_id, "status": run.status,
        "batch_size": run.batch_size, "auto_continue": run.auto_continue,
        "target_video_limit": run.target_video_limit,
        "failure_threshold_percent": run.failure_threshold_percent,
        "dispatched_count": run.dispatched_count,
        "sync_run_id": run.sync_run_id, "analysis_run_id": run.analysis_run_id,
        "error_message": run.error_message, "created_at": run.created_at,
        "updated_at": run.updated_at, "completed_at": run.completed_at,
    }


def _serialize_skill(skill: CreatorSkillVersion | None) -> dict | None:
    if skill is None:
        return None
    return {
        "id": skill.id, "version": skill.version, "status": skill.status,
        "created_at": skill.created_at,
        "download_url": f"/api/creators/{skill.creator_id}/skills/{skill.id}/download",
    }


def creator_progress(db: Session, creator_id: str) -> dict[str, int]:
    """Return mutually understandable counters for the creator workbench."""
    videos = list(db.scalars(select(CreatorVideo).where(CreatorVideo.creator_id == creator_id)))
    values = {key: 0 for key in ("discovered", "queued", "transcribing", "transcribed", "analyzing", "analyzed", "failed")}
    for video in videos:
        job = db.get(Job, video.job_id) if video.job_id else None
        if job and job.status == "failed":
            values["failed"] += 1
        elif video.ingest_status in values:
            values[video.ingest_status] += 1
        elif video.ingest_status == "insight_failed":
            values["failed"] += 1
        elif job and job.status in {"queued", "processing", "cancel_requested"}:
            values["transcribing"] += 1
        else:
            values["discovered"] += 1
    values["total"] = len(videos)
    values["completed"] = values["analyzed"]
    return values


def creator_overview(db: Session, creator: Creator) -> dict:
    progress = creator_progress(db, creator.id)
    latest_sync = db.scalar(select(CreatorSyncRun).where(CreatorSyncRun.creator_id == creator.id).order_by(CreatorSyncRun.created_at.desc()))
    latest_profile = db.scalar(select(CreatorAnalysisRun).where(CreatorAnalysisRun.creator_id == creator.id).order_by(CreatorAnalysisRun.created_at.desc()))
    latest_skill = db.scalar(select(CreatorSkillVersion).where(CreatorSkillVersion.creator_id == creator.id).order_by(CreatorSkillVersion.version.desc()))
    latest_research = db.scalar(select(CreatorResearchRun).where(CreatorResearchRun.creator_id == creator.id).order_by(CreatorResearchRun.created_at.desc()))
    if latest_research and latest_research.status in {"queued", "syncing", "transcribing", "analyzing", "profiling"}:
        action = "processing"
    elif progress["total"] == 0:
        action = "sync"
    elif progress["discovered"] or progress["transcribed"]:
        action = "continue"
    elif progress["analyzed"] and latest_skill is None:
        action = "build_profile"
    elif latest_skill:
        action = "ask"
    else:
        action = "wait"
    return {
        "creator": _serialize_creator(db, creator), "progress": progress,
        "latest_sync": _serialize_sync_run(latest_sync),
        "latest_profile": _analysis_response_data(latest_profile),
        "latest_skill": _serialize_skill(latest_skill),
        "latest_research": _serialize_research_run(latest_research),
        "recommended_action": action,
    }


def creator_dashboard(db: Session) -> dict:
    """Single-query counters for the home-page metrics (no Creator N+1)."""
    return {
        "creator_count": db.scalar(select(func.count()).select_from(Creator)) or 0,
        "video_count": db.scalar(select(func.count()).select_from(CreatorVideo)) or 0,
        "transcript_count": db.scalar(select(func.count()).select_from(CreatorVideo).join(Job, CreatorVideo.job_id == Job.id).where(Job.status == "completed")) or 0,
        "insight_count": db.scalar(select(func.count()).select_from(VideoInsight).where(VideoInsight.status == "completed")) or 0,
        "skill_count": db.scalar(select(func.count()).select_from(CreatorSkillVersion)) or 0,
    }


def _analysis_response_data(run: CreatorAnalysisRun | None) -> dict | None:
    if run is None:
        return None
    return {
        "id": run.id, "creator_id": run.creator_id, "status": run.status,
        "prompt_version": run.prompt_version, "input_snapshot": _json(run.input_snapshot_json, {}),
        "profile": _json(run.profile_json, None), "error_message": run.error_message,
        "created_at": run.created_at, "completed_at": run.completed_at,
    }


def create_creator(db: Session, profile_url: str, name: str | None = None) -> Creator:
    identity = resolve_douyin_creator(profile_url)
    existing = db.scalar(select(Creator).where(Creator.platform == "douyin", Creator.sec_user_id == identity.sec_user_id))
    if existing:
        return existing
    creator = Creator(
        platform="douyin", profile_url=identity.canonical_url, source_url=identity.source_url,
        canonical_url=identity.canonical_url, sec_user_id=identity.sec_user_id,
        platform_uid=identity.uid, resolution_method=identity.resolution_method,
        name=name or identity.nickname, platform_creator_id=identity.sec_user_id,
    )
    db.add(creator)
    db.commit()
    db.refresh(creator)
    return creator


def import_video_urls(db: Session, creator: Creator, urls: list[str]) -> int:
    added = 0
    for raw_url in urls:
        url = str(raw_url)
        validate_public_url(url)
        platform = detect_platform(url)
        if platform != creator.platform:
            raise ValueError("导入的视频平台必须与博主平台一致")
        platform_video_id = _video_id(url)
        existing = db.scalar(select(CreatorVideo).where(
            CreatorVideo.platform == platform, CreatorVideo.platform_video_id == platform_video_id
        ))
        if existing:
            if existing.creator_id != creator.id:
                raise ValueError("该视频已归属于另一个博主")
            continue
        db.add(CreatorVideo(
            creator_id=creator.id, platform=platform, platform_video_id=platform_video_id,
            video_url=url, ingest_status="discovered",
        ))
        added += 1
    db.commit()
    return added


def sync_creator(sync_run_id: str) -> None:
    """Best-effort yt-dlp profile enumeration. Manual import remains the safe fallback."""
    with SessionLocal() as db:
        run = db.get(CreatorSyncRun, sync_run_id)
        if not run:
            return
        creator = db.get(Creator, run.creator_id)
        if not creator:
            return
        run.status = "processing"
        creator.status = "syncing"
        db.commit()
        profile_url = creator.canonical_url or creator.profile_url
        sec_user_id = creator.sec_user_id
    try:
        # Prefer browser interception for an identity-resolved Douyin creator.
        # It lets the official web client issue signed paginated requests.
        if sec_user_id:
            from app.services.douyin_playwright import collect_creator_videos
            page = collect_creator_videos(sec_user_id)
            urls = [item.url for item in page.videos]
            completion_reason = page.completion_reason
        else:
            completion_reason = "yt_dlp_fallback"
            # This is deliberately playlist mode (unlike VideoDownloader, which is
        # single-video only). Do not set playlistend: a creator sync must ask
        # the extractor for every currently accessible work, not just page one.
            options = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "noplaylist": False, "ignoreerrors": True}
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(profile_url, download=False) or {}
            entries = [item for item in (info.get("entries") or []) if isinstance(item, dict)]
            urls = []
            for entry in entries:
                entry_url = entry.get("webpage_url") or entry.get("url")
                entry_id = str(entry.get("id") or "")
                if entry_url and not entry_url.startswith("http") and entry_id.isdigit():
                    entry_url = f"https://www.douyin.com/video/{entry_id}"
                if entry_url and entry_url.startswith("http"):
                    urls.append(str(entry_url))
        with SessionLocal() as db:
            run = db.get(CreatorSyncRun, sync_run_id)
            creator = db.get(Creator, run.creator_id) if run else None
            if not run or not creator:
                return
            added = import_video_urls(db, creator, urls) if urls else 0
            run.discovered_count = len(urls)
            run.created_count = added
            run.cursor = completion_reason
            run.status = "completed"
            run.completed_at = _now()
            creator.status = "ready"
            creator.last_synced_at = _now()
            db.commit()
    except Exception as exc:
        with SessionLocal() as db:
            run = db.get(CreatorSyncRun, sync_run_id)
            if run:
                run.status = "failed"
                run.error_message = str(exc)[-2000:]
                run.completed_at = _now()
                creator = db.get(Creator, run.creator_id)
                if creator:
                    creator.status = "ready"
                db.commit()


def create_research_run(
    db: Session,
    creator: Creator,
    batch_size: int = 3,
    auto_continue: bool = False,
    target_video_limit: int | None = 10,
    failure_threshold_percent: int | None = 20,
) -> CreatorResearchRun:
    """Create one bounded research journey; avoid parallel runs for a creator."""
    existing = db.scalar(select(CreatorResearchRun).where(
        CreatorResearchRun.creator_id == creator.id,
        CreatorResearchRun.status.in_({"queued", "syncing", "ready_to_process", "transcribing", "analyzing", "profiling", "paused"}),
    ).order_by(CreatorResearchRun.created_at.desc()))
    if existing:
        return existing
    run = CreatorResearchRun(
        creator_id=creator.id,
        status="queued",
        batch_size=batch_size,
        auto_continue=auto_continue,
        target_video_limit=target_video_limit,
        failure_threshold_percent=failure_threshold_percent,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def update_research_controls(
    db: Session,
    run: CreatorResearchRun,
    *,
    batch_size: int | None = None,
    auto_continue: bool | None = None,
    target_video_limit: int | None = None,
    failure_threshold_percent: int | None = None,
    clear_target_limit: bool = False,
    clear_failure_threshold: bool = False,
) -> CreatorResearchRun:
    """Persist user-selected safety controls without restarting the run."""
    if run.status in {"completed", "failed"}:
        raise ValueError("已结束的研究任务不能再修改控制项")
    if batch_size is not None:
        run.batch_size = batch_size
    if auto_continue is not None:
        run.auto_continue = auto_continue
    if clear_target_limit:
        run.target_video_limit = None
    elif target_video_limit is not None:
        if target_video_limit < run.dispatched_count:
            raise ValueError("处理上限不能小于已提交的视频数")
        run.target_video_limit = target_video_limit
    if clear_failure_threshold:
        run.failure_threshold_percent = None
    elif failure_threshold_percent is not None:
        run.failure_threshold_percent = failure_threshold_percent
    db.commit()
    db.refresh(run)
    return run


@contextmanager
def _advance_lock(research_run_id: str):
    """Coalesce duplicate UI clicks and completion callbacks into one advance.

    Redis is already a mandatory service for Celery.  Failing closed here is
    safer than letting a transient Redis problem duplicate costly media/LLM
    work.  The database video claim below is a second line of defence.
    """
    client = redis.Redis.from_url(get_settings().celery_broker_url)
    lock = client.lock(f"creator-research:{research_run_id}:advance", timeout=120, blocking_timeout=0)
    acquired = False
    try:
        acquired = bool(lock.acquire(blocking=False))
    except redis.RedisError:
        yield False
        return
    try:
        yield acquired
    finally:
        if acquired:
            try:
                lock.release()
            except redis.RedisError:
                pass


def _research_progress(db: Session, run: CreatorResearchRun) -> dict[str, int]:
    """Progress scoped to this run; legacy untagged work falls back safely."""
    videos = list(db.scalars(select(CreatorVideo).where(CreatorVideo.research_run_id == run.id)))
    if not videos and run.dispatched_count:
        # Runs created before migration 0008 did not stamp videos with a run.
        return creator_progress(db, run.creator_id)
    values = {key: 0 for key in ("discovered", "queued", "transcribing", "transcribed", "analyzing", "analyzed", "failed")}
    for video in videos:
        job = db.get(Job, video.job_id) if video.job_id else None
        if job and job.status == "failed":
            values["failed"] += 1
        elif video.ingest_status in values:
            values[video.ingest_status] += 1
        elif video.ingest_status == "insight_failed":
            values["failed"] += 1
    values["total"] = len(videos)
    values["completed"] = values["analyzed"]
    return values


def start_creator_research(research_run_id: str) -> None:
    """Sync once, then optionally start a small transcription batch.

    This task deliberately does not download every work at once. The bounded
    batch is the cost and queue safety control exposed in the UI.
    """
    with SessionLocal() as db:
        run = db.get(CreatorResearchRun, research_run_id)
        if not run or run.status in {"paused", "completed", "failed"}:
            return
        creator = db.get(Creator, run.creator_id)
        if not creator:
            return
        sync_run = CreatorSyncRun(creator_id=creator.id, status="queued")
        db.add(sync_run)
        db.flush()
        run.sync_run_id = sync_run.id
        run.status = "syncing"
        run.error_message = None
        db.commit()
        auto_continue = run.auto_continue
    sync_creator(sync_run.id)
    with SessionLocal() as db:
        run = db.get(CreatorResearchRun, research_run_id)
        sync_run = db.get(CreatorSyncRun, run.sync_run_id) if run and run.sync_run_id else None
        if not run:
            return
        if sync_run is None or sync_run.status == "failed":
            run.status = "failed"
            run.error_message = (sync_run.error_message if sync_run else "主页同步任务丢失")
            run.completed_at = _now()
            db.commit()
            return
        run.status = "ready_to_process"
        db.commit()
    if auto_continue:
        advance_creator_research(research_run_id)


def advance_creator_research(research_run_id: str) -> None:
    """Advance exactly one safe unit of the research state machine.

    It is idempotent: repeated clicks or task callbacks never create duplicate
    jobs because dispatch only selects `discovered` videos and Insight writes
    are deduplicated by transcript hash.
    """
    with _advance_lock(research_run_id) as acquired:
        if not acquired:
            return
        with SessionLocal() as db:
            # Lock the run row as well as using Redis: the lock protects task
            # coalescing, while this protects the durable state transition.
            run = db.scalar(select(CreatorResearchRun).where(CreatorResearchRun.id == research_run_id).with_for_update())
            if not run or run.status in {"paused", "completed", "failed", "syncing", "queued"}:
                return
            creator = db.get(Creator, run.creator_id)
            if not creator:
                return
            progress = _research_progress(db, run)
            if progress["queued"] or progress["transcribing"]:
                run.status = "transcribing"
                db.commit()
                return
            if progress["transcribed"] or progress["analyzing"]:
                # `process_job_task` schedules Insight extraction immediately.
                # Do not enqueue a second extraction call here.
                run.status = "analyzing"
                db.commit()
                return

            attempted = progress["analyzed"] + progress["failed"]
            minimum_sample = min(run.batch_size, run.dispatched_count)
            if (
                run.failure_threshold_percent is not None
                and minimum_sample > 0
                and attempted >= minimum_sample
                and progress["failed"] * 100 >= attempted * run.failure_threshold_percent
            ):
                run.status = "paused"
                run.error_message = (
                    f"失败率 {progress['failed']}/{attempted} "
                    f"已达到 {run.failure_threshold_percent}% 阈值，已自动暂停。"
                )
                db.commit()
                return

            remaining = None
            if run.target_video_limit is not None:
                remaining = max(run.target_video_limit - run.dispatched_count, 0)
            discovered = db.scalar(select(func.count()).select_from(CreatorVideo).where(
                CreatorVideo.creator_id == creator.id,
                CreatorVideo.ingest_status == "discovered",
                CreatorVideo.research_run_id.is_(None),
            )) or 0
            if discovered and (remaining is None or remaining > 0):
                limit = min(run.batch_size, remaining) if remaining is not None else run.batch_size
                run.status = "transcribing"
                db.commit()
                dispatch_creator_jobs(creator.id, limit, research_run_id=run.id)
                return

            if progress["analyzed"]:
                profile = db.scalar(select(CreatorAnalysisRun).where(
                    CreatorAnalysisRun.creator_id == creator.id
                ).order_by(CreatorAnalysisRun.created_at.desc()))
                if profile is None or profile.status == "failed":
                    profile = CreatorAnalysisRun(creator_id=creator.id, status="queued")
                    db.add(profile)
                    db.flush()
                run.analysis_run_id = profile.id
                if profile.status == "completed":
                    skill = db.scalar(select(CreatorSkillVersion).where(
                        CreatorSkillVersion.creator_id == creator.id, CreatorSkillVersion.analysis_run_id == profile.id
                    ))
                    if skill is None:
                        build_skill(db, profile)
                    run.status = "completed"
                    run.completed_at = _now()
                    db.commit()
                    return
                run.status = "profiling"
                db.commit()
                from app.workers.celery_app import build_creator_profile_task
                build_creator_profile_task.delay(profile.id)
                return
            run.status = "failed"
            run.error_message = "没有可分析的视频；请检查同步结果或导入视频链接"
            run.completed_at = _now()
            db.commit()
            return


def pause_creator_research(db: Session, research_run_id: str) -> CreatorResearchRun:
    run = db.get(CreatorResearchRun, research_run_id)
    if run is None:
        raise ValueError("研究任务不存在")
    if run.status not in {"completed", "failed"}:
        run.status = "paused"
        db.commit()
        db.refresh(run)
    return run


def request_auto_advance(creator_id: str) -> None:
    """Wake up opt-in automatic runs after a video/Insight task reaches rest."""
    with SessionLocal() as db:
        runs = list(db.scalars(select(CreatorResearchRun).where(
            CreatorResearchRun.creator_id == creator_id,
            CreatorResearchRun.auto_continue.is_(True),
            CreatorResearchRun.status.in_({"ready_to_process", "transcribing", "analyzing", "profiling"}),
        )))
        run_ids = [run.id for run in runs]
    if run_ids:
        from app.workers.celery_app import advance_creator_research_task
        for run_id in run_ids:
            advance_creator_research_task.delay(run_id)


def dispatch_creator_jobs(creator_id: str, limit: int = 3, research_run_id: str | None = None) -> int:
    """Create a small bounded window of existing Job tasks; never flood media queue."""
    settings = get_settings()
    with SessionLocal() as db:
        statement = select(CreatorVideo).where(
            CreatorVideo.creator_id == creator_id,
            CreatorVideo.ingest_status == "discovered",
        )
        if research_run_id:
            statement = statement.where(CreatorVideo.research_run_id.is_(None))
        # Claim discovered rows under a database lock.  Together with the
        # status update below this prevents two queued advance callbacks from
        # creating two Jobs for the same source video.
        videos = list(db.scalars(statement.order_by(CreatorVideo.created_at).limit(limit).with_for_update(skip_locked=True)))
        for video in videos:
            from app.db.models import User
            owner_id = db.scalar(select(User.id).where(User.username == settings.admin_username))
            job = Job(
                owner_id=owner_id,
                id=str(uuid4()), source_url=video.video_url, source_type="url",
                platform=video.platform, title=video.title, asr_model=settings.asr_model,
                # The structured insight is the LLM work for creator batches;
                # suppressing ordinary summaries avoids paying twice.
                summary_enabled=False, summary_language="Chinese", summary_preset="transcript",
                status="queued", stage="queued", progress=0,
            )
            db.add(job)
            db.flush()
            video.job_id = job.id
            video.ingest_status = "queued"
            if research_run_id:
                video.research_run_id = research_run_id
        if research_run_id:
            run = db.get(CreatorResearchRun, research_run_id)
            if run:
                run.dispatched_count += len(videos)
        db.commit()
        job_ids = [video.job_id for video in videos if video.job_id]
    if settings.queue_mode == "celery":
        from app.workers.celery_app import process_job_task
        for job_id in job_ids:
            process_job_task.delay(job_id)
    return len(job_ids)


def mark_creator_job_transcribed(job_id: str) -> list[str]:
    """Return CreatorVideo ids whose completed Job is ready for Insight extraction."""
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != "completed":
            return []
        videos = list(db.scalars(select(CreatorVideo).where(CreatorVideo.job_id == job_id)))
        ready: list[str] = []
        for video in videos:
            if video.ingest_status in {"queued", "transcribing", "discovered"}:
                video.ingest_status = "transcribed"
                ready.append(video.id)
        db.commit()
        return ready


def _transcript_for_job(job: Job) -> tuple[list, str]:
    result_path = Path(job.output_dir or "") / "result.json"
    if not result_path.is_file():
        raise RuntimeError("任务没有可用文字稿")
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    segments = (payload.get("transcript") or {}).get("segments") or []
    if not segments:
        raise RuntimeError("任务文字稿为空")
    from app.services.domain import TranscriptSegment
    normalized = [TranscriptSegment(start=float(x["start"]), end=float(x["end"]), text=str(x["text"]).strip()) for x in segments if str(x.get("text", "")).strip()]
    transcript_hash = hashlib.sha256(json.dumps(segments, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return normalized, transcript_hash


INSIGHT_SYSTEM = """You extract an auditable reasoning model from a public video transcript. Return valid JSON only. Never invent claims. Every reusable rule must cite one or more exact transcript timestamps. Distinguish the speaker's own view from quoted examples."""
INSIGHT_TASK = """Return this JSON object: {topic:string, main_claims:[{claim,evidence:[{timestamp,excerpt}]}], reasoning_chains:[{steps:[string],evidence:[{timestamp,excerpt}]}], decision_rules:[{condition,action,rationale,evidence:[{timestamp,excerpt}]}], frameworks:[{name,steps:[string],evidence:[{timestamp,excerpt}]}], assumptions:[string], counter_arguments:[string], examples:[string], communication_patterns:{opening:[string],argument_order:[string],tone:[string],analogy_style:[string]}}. Use [] when absent. Timestamp values must be numbers taken from the source chunk."""


def _complete_json(client: OpenAICompatibleLLM, system: str, prompt: str) -> dict:
    last_error: Exception | None = None
    for _ in range(2):
        try:
            return _parse_json(client.complete(system, prompt).content)
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            prompt += "\nYour previous response was invalid. Return one valid JSON object only."
    raise RuntimeError("LLM failed to return valid JSON") from last_error


def analyze_video_insight(creator_video_id: str) -> None:
    creator_id: str | None = None
    with SessionLocal() as db:
        video = db.get(CreatorVideo, creator_video_id)
        if not video or not video.job_id:
            return
        creator_id = video.creator_id
        job = db.get(Job, video.job_id)
        if not job or job.status != "completed":
            return
        segments, transcript_hash = _transcript_for_job(job)
        insight = db.scalar(select(VideoInsight).where(
            VideoInsight.creator_video_id == video.id, VideoInsight.transcript_hash == transcript_hash,
            VideoInsight.extractor_version == INSIGHT_EXTRACTOR_VERSION,
        ))
        if insight and insight.status == "completed":
            return
        if not insight:
            insight = VideoInsight(creator_video_id=video.id, job_id=job.id, transcript_hash=transcript_hash, extractor_version=INSIGHT_EXTRACTOR_VERSION)
            db.add(insight)
        insight.status = "processing"
        insight.error_message = None
        video.ingest_status = "analyzing"
        db.commit()
        insight_id = insight.id
        config = get_llm_config(db)
    try:
        if config is None:
            raise RuntimeError("尚未配置 AI API Key")
        chunks = chunk_segments(segments, get_settings().llm_max_chunk_chars)
        partials: list[dict] = []
        with OpenAICompatibleLLM(config) as client:
            for index, chunk in enumerate(chunks, 1):
                partials.append(_complete_json(client, INSIGHT_SYSTEM, f"{INSIGHT_TASK}\n片段 {index}/{len(chunks)}：\n{chunk}"))
            merged = _complete_json(client, INSIGHT_SYSTEM, f"{INSIGHT_TASK}\n合并以下分段提取，去重且保留证据：\n{json.dumps(partials, ensure_ascii=False)}")
        with SessionLocal() as db:
            insight = db.get(VideoInsight, insight_id)
            video = db.get(CreatorVideo, creator_video_id)
            if insight and video:
                insight.status = "completed"
                insight.insight_json = json.dumps(merged, ensure_ascii=False)
                insight.completed_at = _now()
                video.ingest_status = "analyzed"
                db.commit()
    except Exception as exc:
        with SessionLocal() as db:
            insight = db.get(VideoInsight, insight_id)
            video = db.get(CreatorVideo, creator_video_id)
            if insight:
                insight.status = "failed"
                insight.error_message = str(exc)[-2000:]
            if video:
                video.ingest_status = "insight_failed"
            db.commit()
    finally:
        if creator_id:
            request_auto_advance(creator_id)


PROFILE_SYSTEM = """You synthesize an evidence-backed cognitive profile from structured video insights. Return valid JSON only. Do not claim a pattern unless supplied evidence supports it. State scope and uncertainty."""
PROFILE_TASK = """Return {worldview:[{statement,scope,evidence}], first_principles:[{statement,scope,evidence}], decision_rules:[{statement,scope,frequency,evidence}], frameworks:[{name,steps,scope,evidence}], reasoning_pattern:[string], evidence_preference:[string], contrarian_patterns:[string], risk_preference:[string], communication_style:[string], boundaries_and_failure_modes:[string]}. Evidence uses source video_id and timestamp. Keep only durable, repeated, useful patterns."""


def build_creator_profile(analysis_run_id: str) -> None:
    with SessionLocal() as db:
        run = db.get(CreatorAnalysisRun, analysis_run_id)
        if not run:
            return
        run.status = "processing"
        db.commit()
        rows = list(db.execute(select(VideoInsight, CreatorVideo).join(CreatorVideo).where(
            CreatorVideo.creator_id == run.creator_id, VideoInsight.status == "completed"
        )))
        items = [{"video_id": video.id, "title": video.title, "insight": _json(insight.insight_json, {})} for insight, video in rows]
        run.input_snapshot_json = json.dumps({"video_count": len(items), "video_ids": [x["video_id"] for x in items]}, ensure_ascii=False)
        db.commit()
        config = get_llm_config(db)
    try:
        if not items:
            raise RuntimeError("尚无已完成的 Video Insight")
        if config is None:
            raise RuntimeError("尚未配置 AI API Key")
        serialized = [json.dumps(item, ensure_ascii=False) for item in items]
        groups, current, size = [], [], 0
        for item in serialized:
            if current and size + len(item) > 24000:
                groups.append(current)
                current, size = [], 0
            current.append(item)
            size += len(item)
        if current:
            groups.append(current)
        with OpenAICompatibleLLM(config) as client:
            patterns = [_complete_json(client, PROFILE_SYSTEM, f"{PROFILE_TASK}\n候选视频洞见：\n" + "\n".join(group)) for group in groups]
            profile = _complete_json(client, PROFILE_SYSTEM, f"{PROFILE_TASK}\n归并以下主题模式：\n{json.dumps(patterns, ensure_ascii=False)}")
        with SessionLocal() as db:
            run = db.get(CreatorAnalysisRun, analysis_run_id)
            if run:
                run.status = "completed"
                run.profile_json = json.dumps(profile, ensure_ascii=False)
                run.completed_at = _now()
                research_runs = list(db.scalars(select(CreatorResearchRun).where(
                    CreatorResearchRun.analysis_run_id == run.id,
                    CreatorResearchRun.status == "profiling",
                )))
                for research in research_runs:
                    build_skill(db, run)
                    research.status = "completed"
                    research.completed_at = _now()
                db.commit()
    except Exception as exc:
        with SessionLocal() as db:
            run = db.get(CreatorAnalysisRun, analysis_run_id)
            if run:
                run.status = "failed"
                run.error_message = str(exc)[-2000:]
                run.completed_at = _now()
                db.commit()


def build_skill(db: Session, analysis_run: CreatorAnalysisRun) -> CreatorSkillVersion:
    if analysis_run.status != "completed" or not analysis_run.profile_json:
        raise ValueError("必须先完成博主认知模型分析")
    profile = _json(analysis_run.profile_json, {})
    creator = db.get(Creator, analysis_run.creator_id)
    version = (db.scalar(select(func.max(CreatorSkillVersion.version)).where(CreatorSkillVersion.creator_id == analysis_run.creator_id)) or 0) + 1
    def bullets(items, key="statement"):
        return "\n".join(f"- {x.get(key, x) if isinstance(x, dict) else x}" for x in items) or "- 暂无足够证据"
    markdown = f"""# {creator.name or '创作者'}公开内容方法论\n\n> 基于公开视频内容提炼，不代表创作者本人，不应将其作为身份模仿或专业建议。\n\n## 使用方式\n\n1. 先界定真实问题与隐含假设。\n2. 仅在适用领域使用下列原则和规则。\n3. 区分事实、判断与预测，并说明不确定性。\n4. 不足以支持结论时，明确说明证据不足。\n\n## 第一性原则\n{bullets(profile.get('first_principles', []))}\n\n## 判断规则\n{bullets(profile.get('decision_rules', []))}\n\n## 常用框架\n{bullets(profile.get('frameworks', []), 'name')}\n\n## 推理与表达\n{bullets(profile.get('reasoning_pattern', []))}\n{bullets(profile.get('communication_style', []))}\n\n## 边界与反模式\n{bullets(profile.get('boundaries_and_failure_modes', []))}\n\n详细证据须在运行时从该创作者的视频洞见与文字稿中检索，不将完整视频原文写入本 Skill。\n"""
    root = get_settings().data_dir / "creators" / creator.id / "skills" / f"v{version}"
    refs = root / "references"
    refs.mkdir(parents=True, exist_ok=True)
    (root / "SKILL.md").write_text(markdown, encoding="utf-8")
    (refs / "profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    skill = CreatorSkillVersion(creator_id=creator.id, analysis_run_id=analysis_run.id, version=version, skill_markdown=markdown, artifact_dir=str(root))
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def _embed(config, inputs: list[str]) -> list[list[float]]:
    from app.services.embeddings import embed_texts
    return embed_texts(config, inputs)


def index_creator_corpus(creator_id: str) -> int:
    """Embed transcript chunks. Rebuilding is idempotent and replaces old chunks."""
    with SessionLocal() as db:
        config = get_llm_config(db)
        if config is None:
            raise RuntimeError("尚未配置 AI API Key")
        rows = list(db.scalars(select(CreatorVideo).join(Job, CreatorVideo.job_id == Job.id).where(CreatorVideo.creator_id == creator_id, Job.status == "completed")))
        chunks = []
        for video in rows:
            job = db.get(Job, video.job_id)
            segments, _ = _transcript_for_job(job)
            for group in chunk_segments(segments, 1400):
                first = segments[0]
                match = re.search(r"\[(\d\d):(\d\d)(?::(\d\d))?\]", group)
                seconds = (int(match.group(1)) * 60 + int(match.group(2)) + (int(match.group(3) or 0) * 3600)) if match else first.start
                chunks.append((video, job, seconds, group))
        if not chunks:
            raise RuntimeError("没有可用于检索的已完成文字稿")
        vectors = _embed(config, [item[3] for item in chunks])
        db.execute(text("DELETE FROM creator_corpus_chunks WHERE creator_id = :creator_id"), {"creator_id": creator_id})
        for (video, job, start, content), vector in zip(chunks, vectors):
            db.execute(text("INSERT INTO creator_corpus_chunks (id, creator_id, creator_video_id, job_id, start_seconds, end_seconds, content, embedding, created_at) VALUES (:id, :creator_id, :video_id, :job_id, :start, :end, :content, CAST(:embedding AS vector), NOW())"), {"id": str(uuid4()), "creator_id": creator_id, "video_id": video.id, "job_id": job.id, "start": start, "end": start, "content": content, "embedding": "[" + ",".join(str(float(x)) for x in vector) + "]"})
        db.commit()
        return len(chunks)


def ask_creator(creator_id: str, question: str, top_k: int) -> dict:
    with SessionLocal() as db:
        config = get_llm_config(db)
        if config is None:
            raise RuntimeError("尚未配置 AI API Key")
        vector = _embed(config, [question])[0]
        rows = db.execute(text("SELECT creator_video_id, job_id, start_seconds, content, 1 - (embedding <=> CAST(:embedding AS vector)) AS score FROM creator_corpus_chunks WHERE creator_id = :creator_id ORDER BY embedding <=> CAST(:embedding AS vector) LIMIT :limit"), {"creator_id": creator_id, "embedding": "[" + ",".join(str(float(x)) for x in vector) + "]", "limit": top_k}).mappings().all()
        if not rows:
            raise RuntimeError("尚未建立向量索引，请先执行索引构建")
        skill = db.scalar(select(CreatorSkillVersion).where(CreatorSkillVersion.creator_id == creator_id).order_by(CreatorSkillVersion.version.desc()))
        if skill is None:
            raise RuntimeError("尚未生成 Skill")
        evidence = [{"video_id": row["creator_video_id"], "job_id": row["job_id"], "timestamp": row["start_seconds"], "score": round(float(row["score"]), 4), "excerpt": row["content"][:800]} for row in rows]
        prompt = f"""基于下列方法论和历史证据回答问题。不能冒充创作者；区分事实、推断和不确定性。结尾列出所用证据的视频 ID 与时间点。\n\n方法论：\n{skill.skill_markdown}\n\n问题：{question}\n\n历史证据：\n{json.dumps(evidence, ensure_ascii=False)}"""
    with OpenAICompatibleLLM(config) as client:
        answer = client.complete("你是一个基于公开内容进行方法论分析的助手。", prompt).content
    return {"answer": answer, "evidence": evidence, "skill_version": skill.version}
