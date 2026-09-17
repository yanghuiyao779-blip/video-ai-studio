"""Creator work discovery through the same persisted Douyin browser profile."""
from __future__ import annotations

from app.services.douyin_browser_session import run_browser_operation
from app.services.douyin_provider import DiscoveryPage, DiscoveredDouyinVideo


async def _collect_in_context(context, sec_user_id: str) -> DiscoveryPage:
    found: dict[str, DiscoveredDouyinVideo] = {}
    has_more = True
    last_cursor: str | None = None
    page = context.pages[0] if context.pages else await context.new_page()

    async def response_listener(response):
        nonlocal has_more, last_cursor
        if "/aweme/v1/web/aweme/post/" not in response.url:
            return
        try:
            payload = await response.json()
            for item in payload.get("aweme_list") or []:
                aweme_id = str(item.get("aweme_id") or "")
                author = item.get("author") or {}
                if aweme_id and str(author.get("sec_uid") or author.get("secUid") or "") == sec_user_id:
                    found[aweme_id] = DiscoveredDouyinVideo(
                        aweme_id, f"https://www.douyin.com/video/{aweme_id}", item.get("desc") or None,
                        int((item.get("video") or {}).get("duration") or 0) // 1000 or None,
                    )
            has_more = bool(payload.get("has_more"))
            last_cursor = str(payload.get("max_cursor")) if payload.get("max_cursor") is not None else None
        except Exception:
            return

    page.on("response", response_listener)
    await page.goto(f"https://www.douyin.com/user/{sec_user_id}", wait_until="domcontentloaded", timeout=90000)
    stagnant = 0
    previous = 0
    while has_more and stagnant < 4:
        await page.mouse.wheel(0, 7000)
        await page.wait_for_timeout(1800)
        if len(found) == previous:
            stagnant += 1
        else:
            stagnant = 0
            previous = len(found)
    reason = "completed_all_accessible" if not has_more else "stopped_no_new_items"
    return DiscoveryPage(list(found.values()), last_cursor, has_more, reason)


def collect_creator_videos(sec_user_id: str) -> DiscoveryPage:
    return run_browser_operation(lambda context: _collect_in_context(context, sec_user_id))
