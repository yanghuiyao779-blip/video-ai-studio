from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yt_dlp

from app.core.config import get_settings

ProgressCallback = Callable[[int, str], None]


@dataclass
class DownloadResult:
    file_path: Path
    title: str
    metadata: dict


@dataclass
class PreviewResult:
    title: str
    metadata: dict


class VideoDownloader:
    def __init__(self, progress: ProgressCallback | None = None):
        self.settings = get_settings()
        self.progress = progress

    def _common_options(self) -> dict:
        options: dict = {
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 3,
            "fragment_retries": 3,
            "socket_timeout": 30,
        }
        cookie_file = self.settings.ytdlp_cookies_file
        if cookie_file and Path(cookie_file).is_file():
            options["cookiefile"] = cookie_file
        return options

    def _check_limits(self, info: dict) -> None:
        duration = int(info.get("duration") or 0)
        if duration and duration > self.settings.max_video_duration_seconds:
            raise RuntimeError(
                f"Video duration {duration}s exceeds configured limit "
                f"{self.settings.max_video_duration_seconds}s"
            )
        estimated = int(info.get("filesize") or info.get("filesize_approx") or 0)
        if estimated and estimated > self.settings.max_download_bytes:
            raise RuntimeError("Estimated download size exceeds configured limit")

    @staticmethod
    def _metadata(info: dict, url: str) -> dict:
        title = str(info.get("title") or info.get("id") or "未命名视频")
        return {
            "id": info.get("id"),
            "title": title,
            "uploader": info.get("uploader") or info.get("channel"),
            "duration": info.get("duration"),
            "webpage_url": info.get("webpage_url") or url,
            "extractor": info.get("extractor_key") or info.get("extractor"),
            "thumbnail": info.get("thumbnail"),
        }

    def preview(self, url: str) -> PreviewResult:
        options = self._common_options()
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
        self._check_limits(info)
        metadata = self._metadata(info, url)
        return PreviewResult(title=metadata["title"], metadata=metadata)

    def _hook(self, data: dict) -> None:
        if not self.progress:
            return
        status = data.get("status")
        if status == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            downloaded = data.get("downloaded_bytes") or 0
            percent = int((downloaded / total) * 100) if total else 0
            mapped = min(30, 10 + int(percent * 0.20))
            self.progress(mapped, "downloading")
        elif status == "finished":
            self.progress(31, "downloaded")

    def download(self, url: str, work_dir: Path) -> DownloadResult:
        work_dir.mkdir(parents=True, exist_ok=True)
        height = self.settings.download_max_height
        options = self._common_options()
        options.update(
            {
                "outtmpl": str(work_dir / "source.%(ext)s"),
                "format": f"bv*[height<={height}]+ba/b[height<={height}]/best",
                "merge_output_format": "mp4",
                "progress_hooks": [self._hook],
                "overwrites": True,
            }
        )

        with yt_dlp.YoutubeDL(options) as ydl:
            preflight = ydl.extract_info(url, download=False)
            self._check_limits(preflight)
            info = ydl.extract_info(url, download=True)

        candidates = [
            path
            for path in work_dir.glob("source.*")
            if path.is_file() and path.suffix.lower() not in {".part", ".ytdl", ".json"}
        ]
        if not candidates:
            raise RuntimeError("Downloader finished but no media file was produced")
        media_path = max(candidates, key=lambda path: path.stat().st_size)
        if media_path.stat().st_size > self.settings.max_download_bytes:
            media_path.unlink(missing_ok=True)
            raise RuntimeError("Downloaded media exceeds configured size limit")
        metadata = self._metadata(info, url)
        return DownloadResult(file_path=media_path, title=metadata["title"], metadata=metadata)
