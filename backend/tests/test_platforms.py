import socket

import pytest

from app.services.platforms import UnsafeURLError, detect_platform, normalize_video_url, validate_public_url
from app.services.text_normalizer import normalize_simplified_chinese


def test_detect_platforms():
    assert detect_platform("https://www.bilibili.com/video/BV123") == "bilibili"
    assert detect_platform("https://b23.tv/example") == "bilibili"
    assert detect_platform("https://www.douyin.com/video/123") == "douyin"
    assert detect_platform("https://v.douyin.com/example") == "douyin"
    assert detect_platform("https://youtu.be/example") == "youtube"
    assert detect_platform("https://example.com/video") == "generic"
    assert detect_platform("https://notbilibili.com/video") == "generic"


def test_normalizes_douyin_jingxuan_modal_url_to_video_url():
    url = "https://www.douyin.com/jingxuan?modal_id=7684991727148551487&utm_source=share"

    assert normalize_video_url(url) == "https://www.douyin.com/video/7684991727148551487"


@pytest.mark.parametrize(
    "url",
    [
        "https://www.douyin.com/video/7684991727148551487",
        "https://www.douyin.com/jingxuan?modal_id=not-a-video-id",
        "https://www.douyin.com/jingxuan?modal_id=7684991727148551487&modal_id=7684991727148551488",
        "https://notdouyin.com/jingxuan?modal_id=7684991727148551487",
    ],
)
def test_only_normalizes_valid_douyin_jingxuan_modal_url(url):
    assert normalize_video_url(url) == url


def _resolved_addresses(*ips: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]


def test_allows_proxy_fake_ip_for_supported_platform(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _resolved_addresses("198.18.0.15"),
    )

    validate_public_url("https://www.bilibili.com/video/BV123")


def test_rejects_proxy_fake_ip_for_untrusted_host(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _resolved_addresses("198.18.0.15"),
    )

    with pytest.raises(UnsafeURLError):
        validate_public_url("https://example.com/video")


def test_still_rejects_private_ip_for_supported_platform(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: _resolved_addresses("10.0.0.1"),
    )

    with pytest.raises(UnsafeURLError):
        validate_public_url("https://www.bilibili.com/video/BV123")


def test_normalizes_chinese_transcript_to_simplified():
    assert normalize_simplified_chinese("簡歷裡寫著微調與資料", "zh") == "简历里写着微调与数据"
    assert normalize_simplified_chinese("怎幺清洗？什幺项目？", "zh") == "怎么清洗？什么项目？"
    assert normalize_simplified_chinese("麻将里的幺鸡", "zh") == "麻将里的幺鸡"
    assert normalize_simplified_chinese("Traditional text", "en") == "Traditional text"
