"""HTTP 抓取。

职责边界：只负责"发出一个请求并拿回可用的 HTML 或一个明确的错误结果"。
限速由 throttle 注入（P2 接入），链接提取由 link_extract 负责。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

import requests

from config import CrawlConfig

from .link_extract import normalize_url

# 只抓网页。其余类型（PDF、图片、压缩包等）在提取阶段已被丢弃，
# 这里是服务端重定向或 Content-Type 撒谎时的兜底。
HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")

ACCEPT_LANGUAGE = "zh-CN,zh;q=0.9,en;q=0.8"


@dataclass(frozen=True)
class FetchResult:
    """一次抓取的结果。html 为 None 时 error 必然非空。"""

    url: str
    status: int | None = None
    html: str | None = None
    content_type: str = ""
    encoding: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.html is not None


def create_session(user_agent: str) -> requests.Session:
    """创建带默认请求头的会话。

    会话复用 TCP 连接，比每次请求都新建连接更省时也更礼貌。
    """
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": ACCEPT_LANGUAGE,
        }
    )
    return session


def fetch_page(
    url: str,
    config: CrawlConfig,
    session: requests.Session,
    throttle: Callable[[str], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> FetchResult:
    """抓取一个页面并返回 HTML。

    throttle 是一个"按 host 等待到允许发请求"的回调，由调用方决定限速策略；
    sleep 可注入，便于测试退避逻辑而不真的等待。
    """
    target = normalize_url(url)
    timeout = config.request_timeout

    result = FetchResult(url=target, error="未发出请求")
    for attempt in range(1 + config.max_retries):
        if throttle is not None:
            throttle(target)

        result = _attempt(target, session, timeout)
        if result.ok or not _is_retryable(result.status):
            break

        has_retry_left = attempt < config.max_retries
        if has_retry_left and config.retry_backoff_seconds > 0:
            sleep(config.retry_backoff_seconds * (attempt + 1))

    return result


def _attempt(url: str, session: requests.Session, timeout: float) -> FetchResult:
    """发出一次请求并判断结果是否可用。"""
    try:
        response = session.get(url, timeout=timeout, allow_redirects=True)
    except requests.RequestException as error:
        return FetchResult(url=url, error=f"{type(error).__name__}: {error}")

    with response:
        content_type = response.headers.get("Content-Type", "")
        if not _is_html(content_type):
            return FetchResult(
                url=url,
                status=response.status_code,
                content_type=content_type,
                error=f"非网页内容：{content_type or '未知类型'}",
            )

        if not response.ok:
            return FetchResult(
                url=url,
                status=response.status_code,
                content_type=content_type,
                error=f"HTTP {response.status_code}",
            )

        encoding = response.encoding or response.apparent_encoding or "utf-8"
        return FetchResult(
            url=url,
            status=response.status_code,
            html=response.text,
            content_type=content_type,
            encoding=encoding,
        )


def _is_html(content_type: str) -> bool:
    text = content_type.lower()
    return any(kind in text for kind in HTML_CONTENT_TYPES)


def _is_retryable(status: int | None) -> bool:
    """网络层错误（status 为 None）与限流/服务端错误可重试。

    4xx（404、403 等）是确定性失败，重试没有意义。
    """
    if status is None:
        return True
    return status == 429 or 500 <= status < 600
