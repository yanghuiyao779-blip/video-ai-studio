"""Recognize media candidates without visiting arbitrary URLs or starting jobs."""
import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

VIDEO_HOSTS = {"bilibili.com", "b23.tv", "douyin.com", "iesdouyin.com", "youtube.com", "youtu.be"}
MEDIA_SUFFIXES = (".mp4", ".mov", ".webm", ".mkv", ".mp3", ".wav", ".m4a", ".flac", ".ogg")
TRAILING = ".,;!?。，；！？）】》)\"]}"


def extract_urls(text: str) -> list[str]:
    return list(dict.fromkeys(x.rstrip(TRAILING) for x in re.findall(r"https?://[^\s<>]+", text)))


def is_video_candidate(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            return False
        if host == "youtube.com" or host.endswith(".youtube.com"):
            return parsed.path.startswith(("/watch", "/shorts/", "/live/", "/embed/"))
        if host == "bilibili.com" or host.endswith(".bilibili.com"):
            return parsed.path.startswith("/video/")
        if host == "douyin.com" or host.endswith(".douyin.com"):
            return not parsed.path.startswith("/user/") and (
                host.startswith("v.") or "/video/" in parsed.path or "modal_id=" in parsed.query)
        return any(host == h or host.endswith("." + h) for h in {"b23.tv", "iesdouyin.com", "youtu.be"}) or parsed.path.lower().endswith(MEDIA_SUFFIXES)
    except ValueError:
        return False


def canonical_url(url: str) -> str:
    p = urlparse(url)
    # Only discard tracking keys, never signed CDN or platform authentication keys.
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k not in {"spm_id_from", "vd_source"}]
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path, p.params, urlencode(query), ""))
