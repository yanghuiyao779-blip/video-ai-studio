import shutil
import subprocess
from pathlib import Path

from app.core.config import get_settings


def binary_available(name: str) -> bool:
    return shutil.which(name) is not None


def extract_audio(video_path: Path, audio_path: Path) -> Path:
    settings = get_settings()
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        settings.ffmpeg_binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(audio_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = (result.stderr or "ffmpeg failed").strip()[-1500:]
        raise RuntimeError(f"Audio extraction failed: {message}")
    return audio_path
