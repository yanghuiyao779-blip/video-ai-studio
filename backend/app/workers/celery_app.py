from celery import Celery

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery(
    "video_ai_studio",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)
celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
)


@celery_app.task(name="video_ai.process_job", autoretry_for=(), acks_late=True)
def process_job_task(job_id: str) -> None:
    from app.services.pipeline import process_job
    process_job(job_id)
    from app.services.creator_intelligence import mark_creator_job_transcribed

    creator_video_ids = mark_creator_job_transcribed(job_id)
    for creator_video_id in creator_video_ids:
        analyze_video_insight_task.delay(creator_video_id)
    if creator_video_ids:
        from app.services.creator_intelligence import request_auto_advance
        from app.db.session import SessionLocal
        from app.db.models import CreatorVideo
        with SessionLocal() as db:
            creator_ids = {video.creator_id for video in (db.get(CreatorVideo, item) for item in creator_video_ids) if video}
        for creator_id in creator_ids:
            request_auto_advance(creator_id)


@celery_app.task(name="video_ai.resummarize_job", autoretry_for=(), acks_late=True)
def resummarize_job_task(job_id: str) -> None:
    from app.services.pipeline import resummarize_job

    resummarize_job(job_id)


@celery_app.task(name="video_ai.sync_creator", autoretry_for=(), acks_late=True)
def sync_creator_task(sync_run_id: str) -> None:
    from app.services.creator_intelligence import sync_creator
    sync_creator(sync_run_id)


@celery_app.task(name="video_ai.dispatch_creator_jobs", autoretry_for=(), acks_late=True)
def dispatch_creator_jobs_task(creator_id: str, limit: int = 3) -> None:
    from app.services.creator_intelligence import dispatch_creator_jobs
    dispatch_creator_jobs(creator_id, limit)


@celery_app.task(name="video_ai.analyze_video_insight", autoretry_for=(), acks_late=True)
def analyze_video_insight_task(creator_video_id: str) -> None:
    from app.services.creator_intelligence import analyze_video_insight
    analyze_video_insight(creator_video_id)


@celery_app.task(name="video_ai.build_creator_profile", autoretry_for=(), acks_late=True)
def build_creator_profile_task(analysis_run_id: str) -> None:
    from app.services.creator_intelligence import build_creator_profile
    build_creator_profile(analysis_run_id)


@celery_app.task(name="video_ai.index_creator_corpus", autoretry_for=(), acks_late=True)
def index_creator_corpus_task(creator_id: str) -> None:
    from app.services.creator_intelligence import index_creator_corpus
    index_creator_corpus(creator_id)


@celery_app.task(name="video_ai.start_creator_research", autoretry_for=(), acks_late=True)
def start_creator_research_task(research_run_id: str) -> None:
    from app.services.creator_intelligence import start_creator_research
    start_creator_research(research_run_id)


@celery_app.task(name="video_ai.advance_creator_research", autoretry_for=(), acks_late=True)
def advance_creator_research_task(research_run_id: str) -> None:
    from app.services.creator_intelligence import advance_creator_research
    advance_creator_research(research_run_id)
