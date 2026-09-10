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


@celery_app.task(name="video_ai.resummarize_job", autoretry_for=(), acks_late=True)
def resummarize_job_task(job_id: str) -> None:
    from app.services.pipeline import resummarize_job

    resummarize_job(job_id)
