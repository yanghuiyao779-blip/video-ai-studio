from __future__ import annotations

import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "backend" / ".env"


def token(size: int = 48) -> str:
    return secrets.token_urlsafe(size)


def main() -> None:
    if TARGET.exists():
        raise SystemExit("backend/.env already exists; refusing to overwrite it")
    admin_password = token(18)
    content = f"""APP_ENV=development
APP_SECRET_KEY={token(48)}
APP_ENCRYPTION_KEY={token(48)}
ADMIN_USERNAME=admin
ADMIN_PASSWORD={admin_password}
DATABASE_URL=sqlite:///./video_ai.db
DATA_DIR=./data
QUEUE_MODE=local
ASR_MODEL=small
ASR_DEVICE=cpu
ASR_COMPUTE_TYPE=int8
DOWNLOAD_MAX_HEIGHT=1080
MAX_VIDEO_DURATION_SECONDS=14400
MAX_DOWNLOAD_BYTES=8589934592
KEEP_SOURCE_MEDIA=false
YTDLP_COOKIES_FILE=
CORS_ORIGINS=http://localhost:5173,http://localhost:8080
"""
    TARGET.write_text(content, encoding="utf-8")
    print(f"Created {TARGET}")
    print("Initial admin username: admin")
    print(f"Initial admin password: {admin_password}")


if __name__ == "__main__":
    main()
