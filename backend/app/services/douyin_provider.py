"""Provider boundary for discovering Douyin creator works.

The current yt-dlp implementation is a best-effort fallback. A Playwright
provider can be added without changing Creator, Job, or downstream pipelines.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DiscoveredDouyinVideo:
    aweme_id: str
    url: str
    title: str | None = None
    duration: int | None = None


@dataclass(frozen=True)
class DiscoveryPage:
    videos: list[DiscoveredDouyinVideo]
    next_cursor: str | None
    has_more: bool
    completion_reason: str | None = None


class DouyinCreatorProvider(Protocol):
    """A provider receives a verified sec_user_id, never /user/self."""

    def list_videos(self, sec_user_id: str, cursor: str | None = None) -> DiscoveryPage: ...
