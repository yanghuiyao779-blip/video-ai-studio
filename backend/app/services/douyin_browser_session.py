"""Persistent, single-account Playwright session for authorized Douyin access.

The profile lives on the application's persistent data volume.  It is never
returned to the browser or database; yt-dlp receives only a short-lived
Netscape cookie snapshot when it needs to download an already-discovered work.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import AsyncIterator, Awaitable, Callable, TypeVar

from app.core.config import get_settings

T = TypeVar("T")
_login_guard = threading.Lock()
_login_thread: threading.Thread | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _state_path() -> Path:
    return get_settings().douyin_profile_dir / "session-status.json"


def _qr_path() -> Path:
    return get_settings().douyin_profile_dir / "login-qr.png"


def _write_state(status: str, message: str, **extra: object) -> None:
    path = _state_path()
    payload = {"status": status, "message": message, "updated_at": _now().isoformat(), **extra}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def session_status() -> dict:
    path = _state_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, json.JSONDecodeError):
        raw = {}
    qr = _qr_path()
    return {
        "status": raw.get("status", "not_connected"),
        "message": raw.get("message", "尚未连接抖音账号"),
        "last_verified_at": raw.get("last_verified_at"),
        "qr_available": qr.is_file() and raw.get("status") in {"awaiting_scan", "verification_required"},
        "qr_updated_at": datetime.fromtimestamp(qr.stat().st_mtime, timezone.utc).isoformat() if qr.is_file() else None,
    }


def qr_path() -> Path:
    return _qr_path()


async def _acquire_lock(timeout_seconds: int = 12):
    """Async-friendly advisory lock; a persistent Chromium profile is single-use."""
    import fcntl
    lock_path = get_settings().douyin_profile_dir / ".browser.lock"
    handle = lock_path.open("a+")
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except BlockingIOError:
            if asyncio.get_running_loop().time() >= deadline:
                handle.close()
                raise RuntimeError("抖音浏览器正在执行其他任务，请稍后重试")
            await asyncio.sleep(0.25)


def _legacy_netscape_cookies(path: Path) -> list[dict]:
    cookies: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        fields = line.split("\t")
        if len(fields) != 7:
            continue
        domain, _, cookie_path, secure, expires, name, value = fields
        cookies.append({
            "name": name, "value": value, "domain": domain.removeprefix("#HttpOnly_"), "path": cookie_path,
            "secure": secure.upper() == "TRUE", "expires": float(expires) if expires.isdigit() else -1,
        })
    return cookies


@asynccontextmanager
async def persistent_context(headless: bool = True) -> AsyncIterator[object]:
    """Open the one persisted Chromium profile with an inter-process lock."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise RuntimeError("未安装 Playwright 浏览器依赖") from exc
    import fcntl

    settings = get_settings()
    lock_handle = await _acquire_lock()
    playwright = None
    context = None
    try:
        playwright = await async_playwright().start()
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(settings.douyin_profile_dir),
            headless=headless,
            executable_path=settings.playwright_browser_executable or None,
            viewport={"width": 1440, "height": 1200},
            locale="zh-CN",
        )
        # Backward-compatible bootstrap: an existing administrator-managed
        # Netscape cookie file can seed the profile once. Persistent profile
        # state remains the preferred session source afterwards.
        if not _logged_in(await context.cookies("https://www.douyin.com")):
            legacy_path = Path(settings.ytdlp_cookies_file or "")
            if legacy_path.is_file():
                legacy = _legacy_netscape_cookies(legacy_path)
                if legacy:
                    await context.add_cookies(legacy)
        yield context
    finally:
        if context is not None:
            await context.close()
        if playwright is not None:
            await playwright.stop()
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
        lock_handle.close()


def _logged_in(cookies: list[dict]) -> bool:
    names = {str(item.get("name") or "") for item in cookies}
    return bool(names & {"sessionid", "sessionid_ss"})


async def _login_flow() -> None:
    settings = get_settings()
    _write_state("starting", "正在启动抖音登录页面")
    try:
        async with persistent_context(headless=True) as context:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=settings.playwright_timeout_seconds)
            deadline = asyncio.get_running_loop().time() + settings.douyin_login_timeout_seconds
            while asyncio.get_running_loop().time() < deadline:
                cookies = await context.cookies("https://www.douyin.com")
                if _logged_in(cookies):
                    _qr_path().unlink(missing_ok=True)
                    _write_state("connected", "抖音账号已连接", last_verified_at=_now().isoformat())
                    return
                temporary = _qr_path().with_suffix(".tmp.png")
                await page.screenshot(path=str(temporary), full_page=False)
                os.chmod(temporary, 0o600)
                temporary.replace(_qr_path())
                body_text = await page.locator("body").inner_text()
                if "请完成下列验证" in body_text or "滑动" in body_text and "验证" in body_text:
                    _write_state("verification_required", "抖音要求浏览器人机验证；当前截图仅供查看，不能自动绕过验证", qr_updated_at=_now().isoformat())
                elif "扫码" in body_text or "二维码" in body_text:
                    _write_state("awaiting_scan", "请使用抖音扫码登录", qr_updated_at=_now().isoformat())
                else:
                    _write_state("awaiting_scan", "请在登录画面完成抖音登录", qr_updated_at=_now().isoformat())
                await page.wait_for_timeout(1800)
        _write_state("expired", "二维码已过期，请重新发起登录")
    except Exception as exc:
        _write_state("error", f"启动登录失败：{str(exc)[:220]}")


def start_login() -> dict:
    global _login_thread
    with _login_guard:
        if _login_thread and _login_thread.is_alive():
            return session_status()
        _login_thread = threading.Thread(target=lambda: asyncio.run(_login_flow()), name="douyin-login", daemon=True)
        _login_thread.start()
    return {"status": "starting", "message": "正在打开抖音登录页面", "last_verified_at": None, "qr_available": False, "qr_updated_at": None}


async def run_with_persistent_context(operation: Callable[[object], Awaitable[T]]) -> T:
    async with persistent_context(headless=True) as context:
        result = await operation(context)
        cookies = await context.cookies("https://www.douyin.com")
        if _logged_in(cookies):
            _write_state("connected", "抖音账号已连接", last_verified_at=_now().isoformat())
        else:
            _write_state("expired", "未检测到有效抖音登录态，请重新扫码")
        return result


def run_browser_operation(operation: Callable[[object], Awaitable[T]]) -> T:
    return asyncio.run(run_with_persistent_context(operation))


async def _export_cookies(context: object) -> list[dict]:
    return await context.cookies("https://www.douyin.com")


def export_ytdlp_cookie_snapshot() -> Path | None:
    """Export a short-lived cookie jar for yt-dlp without exposing the profile."""
    try:
        cookies = run_browser_operation(_export_cookies)
    except Exception:
        return None
    if not _logged_in(cookies):
        return None
    target_dir = get_settings().data_dir / "yt-dlp-cookies"
    target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    with NamedTemporaryFile(prefix="douyin-profile-", suffix=".txt", dir=target_dir, delete=False, mode="w", encoding="utf-8") as output:
        output.write("# Netscape HTTP Cookie File\n")
        for cookie in cookies:
            domain = str(cookie.get("domain") or ".douyin.com")
            include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
            secure = "TRUE" if cookie.get("secure") else "FALSE"
            expires = int(cookie.get("expires") or 0)
            output.write("\t".join([domain, include_subdomains, str(cookie.get("path") or "/"), secure, str(max(0, expires)), str(cookie.get("name") or ""), str(cookie.get("value") or "")]) + "\n")
        path = Path(output.name)
    os.chmod(path, 0o600)
    return path
