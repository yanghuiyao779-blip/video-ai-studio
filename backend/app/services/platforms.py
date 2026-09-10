import ipaddress
import socket
from urllib.parse import urlparse

PROXY_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")


class UnsafeURLError(ValueError):
    pass


def _matches_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def _is_supported_platform_host(host: str) -> bool:
    """Return whether a host belongs to a platform the downloader supports.

    This deliberately uses domain-label boundaries.  For example,
    ``notbilibili.com`` must not be treated as a Bilibili domain.
    """
    return (
        host == "b23.tv"
        or _matches_domain(host, "bilibili.com")
        or _matches_domain(host, "douyin.com")
        or _matches_domain(host, "youtube.com")
        or host == "youtu.be"
    )


def detect_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host == "b23.tv" or _matches_domain(host, "bilibili.com"):
        return "bilibili"
    if host == "v.douyin.com" or _matches_domain(host, "douyin.com"):
        return "douyin"
    if _matches_domain(host, "youtube.com") or host == "youtu.be":
        return "youtube"
    return "generic"


def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeURLError("Only public HTTP/HTTPS URLs are allowed")
    host = parsed.hostname.lower()
    if host in {"localhost", "localhost.localdomain"}:
        raise UnsafeURLError("Local addresses are not allowed")
    try:
        addresses = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeURLError("Source host cannot be resolved") from exc
    for item in addresses:
        ip = ipaddress.ip_address(item[4][0])
        # Clash and compatible TUN/DNS proxy modes map public domains to this
        # benchmarking range (Fake-IP).  It is not a real destination and is
        # normally rejected below, but allowing it for our small, fixed set of
        # video platforms lets the proxy route the request as intended.  Do not
        # allow the range for arbitrary user-controlled hosts: that would weaken
        # the SSRF boundary.
        if ip in PROXY_FAKE_IP_NETWORK and _is_supported_platform_host(host):
            continue
        if any(
            (
                ip.is_private,
                ip.is_loopback,
                ip.is_link_local,
                ip.is_multicast,
                ip.is_reserved,
                ip.is_unspecified,
            )
        ):
            raise UnsafeURLError("Private or non-public source addresses are not allowed")
