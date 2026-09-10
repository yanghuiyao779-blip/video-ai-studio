import importlib.util
from pathlib import Path

from fastapi import APIRouter
from sqlalchemy import text

from app.api.schemas import HealthResponse
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.media import binary_available

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    database = False
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            database = True
    except Exception:
        database = False

    data_dir_writable = False
    try:
        probe = Path(settings.data_dir) / ".healthcheck"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        data_dir_writable = True
    except OSError:
        data_dir_writable = False

    queue = settings.queue_mode != "celery"
    if settings.queue_mode == "celery":
        try:
            import redis

            client = redis.Redis.from_url(settings.celery_broker_url, socket_timeout=1.5)
            queue = bool(client.ping())
            client.close()
        except Exception:
            queue = False

    ffmpeg = binary_available(settings.ffmpeg_binary)
    ffprobe = binary_available(settings.ffprobe_binary)
    ytdlp = importlib.util.find_spec("yt_dlp") is not None
    overall = "ok" if database and data_dir_writable and ffmpeg and ffprobe and ytdlp and queue else "degraded"
    return HealthResponse(
        status=overall,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        ytdlp=ytdlp,
        database=database,
        data_dir_writable=data_dir_writable,
        queue_mode=settings.queue_mode,
        queue=queue,
    )
