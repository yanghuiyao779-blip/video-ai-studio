import app.services.douyin_resolver as resolver
import socket
import pytest


@pytest.fixture(autouse=True)
def public_dns_for_resolver_unit_tests(monkeypatch):
    # URL safety has its own tests. Identity parsing must not depend on live DNS.
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))
    ])




def test_canonical_profile_never_treats_sec_uid_as_self():
    identity = resolver.resolve_douyin_creator("https://www.douyin.com/user/MS4wLjABAAAAreal")
    assert identity.sec_user_id == "MS4wLjABAAAAreal"
    assert identity.canonical_url.endswith("MS4wLjABAAAAreal")


def test_self_modal_resolves_video_author(monkeypatch):
    monkeypatch.setattr(resolver, "run_browser_operation", lambda operation: resolver.CreatorIdentity("douyin", "https://www.douyin.com/user/self?modal_id=7685350578280626545", "https://www.douyin.com/user/MS4-author", "MS4-author", "42", "小沐", "self_modal_video_network", "7685350578280626545"))
    identity = resolver.resolve_douyin_creator("https://www.douyin.com/user/self?modal_id=7685350578280626545")
    assert identity.sec_user_id == "MS4-author"
    assert identity.source_video_id == "7685350578280626545"


def test_self_without_modal_is_rejected():
    try:
        resolver.resolve_douyin_creator("https://www.douyin.com/user/self")
    except ValueError as exc:
        assert "不是目标作者主页" in str(exc)
    else:
        raise AssertionError("/user/self must not become a creator")


def test_jingxuan_modal_is_normalized_before_browser_resolution(monkeypatch):
    captured = {}

    async def fake_resolve(context, url, source_url, method, video_id):
        captured.update(url=url, source_url=source_url, method=method, video_id=video_id)
        return resolver.CreatorIdentity("douyin", source_url, "https://www.douyin.com/user/MS4-author", "MS4-author", None, "小沐", "video_url_network", video_id)

    def fake_browser(operation):
        import asyncio
        return asyncio.run(operation(None))

    monkeypatch.setattr(resolver, "_resolve_in_browser", fake_resolve)
    monkeypatch.setattr(resolver, "run_browser_operation", fake_browser)
    identity = resolver.resolve_douyin_creator("https://www.douyin.com/jingxuan?modal_id=7684991727148551487")
    assert captured["url"] == "https://www.douyin.com/video/7684991727148551487"
    assert captured["video_id"] == "7684991727148551487"
    assert identity.sec_user_id == "MS4-author"
