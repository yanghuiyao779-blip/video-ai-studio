"""Local-mode assistant process. Run alongside the original local media worker."""
import logging
import time
from sqlalchemy import select
from app.db.bootstrap import bootstrap_database
from app.db.assistant import ChatRun, VideoKnowledgeIndex
from app.db.session import SessionLocal
from app.services.assistant_runner import process_run
from app.services.assistant_service import recover_stale_runs
from app.services.video_knowledge import index_video


def run():
    logging.basicConfig(level=logging.INFO)
    bootstrap_database()
    last_recovery = 0.0
    while True:
        if time.monotonic() - last_recovery > 30:
            recover_stale_runs()
            last_recovery = time.monotonic()
        with SessionLocal() as db:
            run_id = db.scalar(select(ChatRun.id).where(ChatRun.status.in_(["queued", "waiting"]))
                .order_by(ChatRun.updated_at).limit(1))
            job_id = db.scalar(select(VideoKnowledgeIndex.job_id).where(VideoKnowledgeIndex.status.in_(["missing", "stale"]))
                .order_by(VideoKnowledgeIndex.updated_at).limit(1))
        if run_id:
            process_run(run_id)
        elif job_id:
            index_video(job_id)
        time.sleep(0.75)


if __name__ == "__main__":
    run()
