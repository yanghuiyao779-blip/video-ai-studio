"""Repair lost queue dispatches without replaying a live generation.

Run one reconciler per deployment. Re-enqueues are safe because process_run()
claims a database lease with compare-and-swap; completed runs cannot re-execute.
It never retries a failed model call without the user explicitly requesting it.
"""
import logging
import time
from datetime import timedelta
from sqlalchemy import select
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.db.assistant import ChatRun, VideoKnowledgeIndex, now
from app.services.assistant_service import enqueue_run, enqueue_index, recover_stale_runs

logger = logging.getLogger(__name__)


def reconcile_once():
    recover_stale_runs()
    cutoff = now() - timedelta(seconds=45)
    with SessionLocal() as db:
        run_ids = list(db.scalars(select(ChatRun.id).where(
            ChatRun.status.in_(["queued", "waiting"]), ChatRun.updated_at < cutoff,
            ChatRun.cancel_requested.is_(False)).order_by(ChatRun.updated_at).limit(100)))
        job_ids = list(db.scalars(select(VideoKnowledgeIndex.job_id).where(
            VideoKnowledgeIndex.status.in_(["missing", "stale"]),
            VideoKnowledgeIndex.updated_at < cutoff).limit(50)))
    for run_id in run_ids:
        enqueue_run(run_id)
    for job_id in job_ids:
        enqueue_index(job_id)
    return {"runs": len(run_ids), "indexes": len(job_ids)}


def run():
    logging.basicConfig(level=logging.INFO)
    if get_settings().queue_mode != "celery":
        raise RuntimeError("Local mode uses assistant_worker, not the reconciler")
    while True:
        try:
            reconcile_once()
        except Exception:
            logger.exception("Assistant reconciliation failed; retrying next cycle")
        time.sleep(30)


if __name__ == "__main__":
    run()
