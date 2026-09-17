import logging
import time

from sqlalchemy import select

from app.db.bootstrap import bootstrap_database
from app.db.models import CreatorAnalysisRun, CreatorSyncRun, CreatorVideo, Job
from app.db.session import SessionLocal
from app.services.creator_intelligence import analyze_video_insight, build_creator_profile, mark_creator_job_transcribed, sync_creator
from app.services.pipeline import process_job, resummarize_job

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("local-worker")


def run() -> None:
    bootstrap_database()
    logger.info("Local worker started. Use one local worker process only.")
    while True:
        job_id: str | None = None
        resummarize = False
        with SessionLocal() as db:
            job = db.scalar(
                select(Job).where(Job.status == "queued").order_by(Job.created_at.asc()).limit(1)
            )
            if job is not None:
                resummarize = job.stage == "resummarize_queued"
                job.status = "processing"
                job.stage = "loading_transcript" if resummarize else "claimed"
                job.progress = max(job.progress, 1)
                job_id = job.id
                db.commit()
        if job_id:
            if resummarize:
                resummarize_job(job_id)
            else:
                process_job(job_id)
                mark_creator_job_transcribed(job_id)
        else:
            with SessionLocal() as db:
                sync_run = db.scalar(select(CreatorSyncRun).where(CreatorSyncRun.status == "queued").order_by(CreatorSyncRun.created_at).limit(1))
                profile_run = db.scalar(select(CreatorAnalysisRun).where(CreatorAnalysisRun.status == "queued").order_by(CreatorAnalysisRun.created_at).limit(1))
                video = db.scalar(select(CreatorVideo).where(CreatorVideo.ingest_status == "transcribed").order_by(CreatorVideo.updated_at).limit(1))
                sync_id = sync_run.id if sync_run else None
                profile_id = profile_run.id if profile_run else None
                video_id = video.id if video else None
            if sync_id:
                sync_creator(sync_id)
            elif video_id:
                analyze_video_insight(video_id)
            elif profile_id:
                build_creator_profile(profile_id)
            else:
                time.sleep(1.5)


if __name__ == "__main__":
    run()
