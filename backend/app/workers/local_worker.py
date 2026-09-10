import logging
import time

from sqlalchemy import select

from app.db.bootstrap import bootstrap_database
from app.db.models import Job
from app.db.session import SessionLocal
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
        else:
            time.sleep(1.5)


if __name__ == "__main__":
    run()
