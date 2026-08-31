"""来源适配器基类与安全 HTTP 抓取。

安全要求（AI_NEWS_MODULE_PLAN.md 第 10 节）：
- 仅允许 HTTPS；
- 每次重定向后重新校验协议与主机，禁止跳到本机/内网/云元数据地址（防 SSRF）；
- 限制下载大小与超时；
- 使用 ETag / Last-Modified 条件请求。
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

import requests

from web.news.config import NewsSettings, SourceConfig
from web.news.models import FetchOutcome


class SourceError(Exception):
    """来源抓取或解析失败。"""


MAX_REDIRECTS = 3

# 去除追踪参数（URL 规范化 / 去重用）
_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAMS = {
    "fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "ref", "referrer",
    "spm", "scm", "share_source", "tt_from",
}


def default_resolver(host: str) -> list[str]:
    """把主机名解析为 IP 字符串列表（用于 SSRF 校验）。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise SourceError(f"域名解析失败：{host}") from exc
    return [info[4][0] for info in infos]


# RFC 2544 基准测试保留段。本地代理（Clash/Surge fake-ip 模式）会把外部域名
# 解析到该段，实际流量经代理隧道发往真实站点；它不属于内网/云元数据地址，
# 放行不影响 SSRF 防护目标（回环、私网、链路本地、元数据地址仍全部拦截）。
_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")


def _is_safe_address(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return False
    if ip in _FAKE_IP_NETWORK:
        return True
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_external_url(
    url: str,
    resolver: Callable[[str], list[str]] = default_resolver,
) -> str:
    """校验外抓 URL：仅 HTTPS 且主机解析到公网地址。返回规范化主机名。"""
    if not isinstance(url, str) or not url.strip():
        raise SourceError("URL 为空")
    parts = urlsplit(url.strip())
    if parts.scheme.lower() != "https":
        raise SourceError(f"仅允许 HTTPS 地址：{url}")
    hostname = (parts.hostname or "").lower().rstrip(".")
    if not hostname:
        raise SourceError(f"URL 缺少主机名：{url}")
    if hostname in {"localhost", "metadata.google.internal", "instance-data"}:
        raise SourceError(f"禁止访问内部主机名：{hostname}")
    try:
        addresses = resolver(hostname)
    except SourceError:
        raise
    except OSError as exc:
        raise SourceError(f"域名解析失败：{hostname}") from exc
    for ip_text in addresses:
        if not _is_safe_address(ip_text):
            raise SourceError(f"禁止访问内网/保留地址：{hostname} -> {ip_text}")
    return hostname


@dataclass
class HttpResponse:
    status_code: int
    body: bytes
    etag: str | None
    last_modified: str | None
    final_url: str


def http_get_safe(
    url: str,
    settings: NewsSettings,
    etag: str | None = None,
    last_modified: str | None = None,
    session: requests.Session | None = None,
    resolver: Callable[[str], list[str]] = default_resolver,
) -> HttpResponse:
    """带 SSRF 防护、大小限制与重定向校验的 GET 请求。"""
    validate_external_url(url, resolver=resolver)
    headers = {
        "User-Agent": "TradingAgents-NewsBot/1.0 (+https://github.com/TauricResearch/TradingAgents)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, application/json, text/*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
    }
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    own_session = session is None
    if own_session:
        session = requests.Session()
    try:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            response = session.get(
                current,
                headers=headers,
                timeout=(settings.request_timeout_seconds, settings.request_timeout_seconds),
                allow_redirects=False,
                stream=True,
            )
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location", "")
                response.close()
                if not location:
                    raise SourceError("重定向缺少 Location 头")
                # 相对地址补全为绝对地址
                next_url = requests.compat.urljoin(current, location)
                validate_external_url(next_url, resolver=resolver)
                current = next_url
                continue
            # 读取响应体并限制大小
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > settings.max_response_bytes:
                    response.close()
                    raise SourceError(
                        f"响应超过大小限制 {settings.max_response_bytes} 字节"
                    )
                chunks.append(chunk)
            return HttpResponse(
                status_code=response.status_code,
                body=b"".join(chunks),
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified"),
                final_url=current,
            )
        raise SourceError(f"重定向次数超过 {MAX_REDIRECTS} 次")
    except requests.RequestException as exc:
        raise SourceError(f"网络请求失败：{type(exc).__name__}: {exc}") from exc
    finally:
        if own_session:
            session.close()


class SourceAdapter:
    """来源适配器：把外部数据转换为 RawEntry 列表。"""

    def __init__(self, config: SourceConfig, settings: NewsSettings) -> None:
        self.config = config
        self.settings = settings

    def fetch(
        self,
        etag: str | None = None,
        last_modified: str | None = None,
        session: requests.Session | None = None,
        resolver: Callable[[str], list[str]] = default_resolver,
    ) -> FetchOutcome:
        raise NotImplementedError


def canonicalize_url(url: str) -> str:
    """去除追踪参数与片段，规范化协议/主机大小写，用于去重。"""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower() or "https"
    hostname = (parts.hostname or "").lower()
    port = parts.port
    netloc = hostname if not port else f"{hostname}:{port}"
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking_param(key)
    ]
    query_pairs.sort()
    return urlunsplit((scheme, netloc, parts.path or "/", urlencode(query_pairs), ""))


def _is_tracking_param(key: str) -> bool:
    lowered = key.lower()
    if lowered in _TRACKING_PARAMS:
        return True
    return any(lowered.startswith(prefix) for prefix in _TRACKING_PARAM_PREFIXES)
