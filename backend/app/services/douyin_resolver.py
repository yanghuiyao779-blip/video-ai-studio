"""Resolve any supported Douyin input into a stable creator `sec_user_id`."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

from app.services.douyin_browser_session import run_browser_operation
from app.services.platforms import detect_platform, normalize_video_url, validate_public_url


@dataclass(frozen=True)
class CreatorIdentity:
    platform: str
    source_url: str
    canonical_url: str
    sec_user_id: str
    uid: str | None
    nickname: str | None
    resolution_method: str
    source_video_id: str | None = None


def _video_id(url: str) -> str | None:
    path = urlparse(url).path.rstrip("/")
    if path.startswith("/video/"):
        candidate = path.split("/video/", 1)[1]
        return candidate if candidate.isdigit() else None
    return None


def _author_from_payload(value: object, video_id: str | None) -> dict | None:
    """Find an author only from video-detail shaped network payloads."""
    if isinstance(value, dict):
        detail = value.get("aweme_detail") or value.get("awemeDetail")
        if isinstance(detail, dict):
            candidate_id = str(detail.get("aweme_id") or detail.get("awemeId") or "")
            author = detail.get("author")
            if isinstance(author, dict) and (video_id is None or candidate_id == video_id):
                return author
        for nested in value.values():
            found = _author_from_payload(nested, video_id)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _author_from_payload(nested, video_id)
            if found:
                return found
    return None


async def _resolve_in_browser(context, url: str, source_url: str, method: str, video_id: str | None) -> CreatorIdentity:
    page = context.pages[0] if context.pages else await context.new_page()
    author: dict | None = None

    async def response_listener(response):
        nonlocal author
        # The official page creates signed requests. We only read video detail.
        if author is not None or "/aweme/" not in response.url:
            return
        try:
            found = _author_from_payload(await response.json(), video_id)
            if found:
                author = found
        except Exception:
            return

    page.on("response", response_listener)
    await page.goto(url, wait_until="domcontentloaded", timeout=90000)
    for _ in range(12):
        if author:
            break
        await page.wait_for_timeout(500)

    if author is None:
        # DOM is a constrained fallback, never an arbitrary first regex match.
        links = await page.locator('a[href*="/user/"]').evaluate_all("""
            nodes => nodes.map(node => ({href: node.href, text: (node.innerText || '').trim()}))
        """)
        identifiers = {
            item["href"].split("/user/", 1)[1].split("?", 1)[0].split("/", 1)[0]
            for item in links
            if "/user/" in item["href"] and item["href"].split("/user/", 1)[1].split("?", 1)[0].split("/", 1)[0] not in {"", "self"}
        }
        if len(identifiers) != 1:
            raise ValueError("未能从抖音页面确认视频作者；请先在设置中连接抖音账号后重试")
        sec_uid = identifiers.pop()
        return CreatorIdentity("douyin", source_url, f"https://www.douyin.com/user/{sec_uid}", sec_uid, None, None, f"{method}_dom", video_id)

    sec_uid = str(author.get("sec_uid") or author.get("secUid") or "").strip()
    if not sec_uid or sec_uid == "self":
        raise ValueError("抖音页面未返回作者 sec_user_id；请重新连接抖音账号后重试")
    return CreatorIdentity("douyin", source_url, f"https://www.douyin.com/user/{sec_uid}", sec_uid,
                           str(author.get("uid") or author.get("id") or "") or None,
                           str(author.get("nickname") or author.get("nickName") or "") or None,
                           f"{method}_network", video_id)


def resolve_douyin_creator(source_url: str) -> CreatorIdentity:
    validate_public_url(source_url)
    if detect_platform(source_url) != "douyin":
        raise ValueError("当前仅支持抖音 URL")
    normalized = normalize_video_url(source_url)
    parsed = urlparse(normalized)
    path = parsed.path.rstrip("/")
    query = parse_qs(parsed.query)
    if path.startswith("/user/"):
        identifier = path.split("/user/", 1)[1]
        if identifier and identifier != "self":
            return CreatorIdentity("douyin", source_url, f"https://www.douyin.com/user/{identifier}", identifier, None, None, "canonical_profile")
        modal_id = (query.get("modal_id") or [None])[0]
        if not modal_id or not modal_id.isdigit():
            raise ValueError("/user/self 不是目标作者主页；请提供 modal_id、任意作品链接或作者主页分享链接")
        normalized = f"https://www.douyin.com/video/{modal_id}"
        return run_browser_operation(lambda context: _resolve_in_browser(context, normalized, source_url, "self_modal_video", modal_id))
    video_id = _video_id(normalized)
    return run_browser_operation(lambda context: _resolve_in_browser(context, normalized, source_url, "video_url" if video_id else "share_url", video_id))
