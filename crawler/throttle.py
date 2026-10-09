"""按 host 限速。

参考代码的延迟是"按种子"的，且默认值被 `fixed_delay=0.01` 覆盖——等于不限速。
这里改为按 host 记录上次请求时刻：同一 host 两次请求之间至少等待 delay 秒，
不同 host 之间互不影响。

自己声明了 Crawl-delay 的站点，其 delay 由 robots.py 提供；两者取较大值。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from urllib.parse import urlsplit

from .robots import RobotsCache


class HostThrottle:
    """记录每个 host 的上次请求时刻，并给出应等待的秒数。"""

    def __init__(self) -> None:
        self._last_request: dict[str, float] = {}

    def wait_seconds(self, url: str, delay: float, now: float | None = None) -> float:
        """返回还需等待的秒数；不需要等待时返回 0。"""
        host = _host(url)
        if host is None or delay <= 0:
            return 0.0

        moment = time.monotonic() if now is None else now
        last = self._last_request.get(host)
        if last is None:
            return 0.0
        return max(0.0, delay - (moment - last))

    def record(self, url: str, now: float | None = None) -> None:
        """记录一次请求发生的时刻。"""
        host = _host(url)
        if host is not None:
            self._last_request[host] = time.monotonic() if now is None else now

    def wait(self, url: str, delay: float) -> None:
        """等待到该 host 允许再次请求，并记录本次时刻。"""
        remaining = self.wait_seconds(url, delay)
        if remaining > 0:
            time.sleep(remaining)
        self.record(url)


def make_throttle(
    throttle: HostThrottle,
    default_delay: float,
    robots: RobotsCache | None = None,
) -> Callable[[str], None]:
    """生成传给 fetcher.fetch_page 的限速回调。

    按 host 等待到允许发请求为止；robots.txt 里更大的 Crawl-delay 优先。
    调用方应当先做 robots 判定、再让 fetcher 调用本回调——否则抓取 robots.txt
    自身会被记成一次页面请求。
    """
    return lambda url: throttle.wait(url, delay_for(url, default_delay, robots))


def delay_for(url: str, default_delay: float, robots: RobotsCache | None) -> float:
    """确定某个 URL 适用的最小请求间隔。"""
    if robots is None:
        return default_delay
    declared = robots.crawl_delay_for(url)
    if declared is None:
        return default_delay
    return max(default_delay, declared)


def _host(url: str) -> str | None:
    return urlsplit(url).netloc.lower() or None
