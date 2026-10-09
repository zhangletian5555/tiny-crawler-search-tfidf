"""robots.txt 抓取、缓存与判定。

参考代码 import 了 `RobotFileParser` 却从未调用——这里是它真正落地的地方。
抓取 robots.txt 复用同一个 requests 会话，从而共享超时与请求头。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests

# loaded: 成功取得并按规则判定
# missing: 站点没有 robots.txt（404 等），视为无限制
# unavailable: 明确拒绝提供（401/403）或取不到，按不允许处理
Verdict = Literal["loaded", "missing", "unavailable"]


@dataclass(frozen=True)
class RobotsRules:
    """一个 host 的 robots.txt 判定结果，由 RobotsCache 按 host 缓存。"""

    verdict: Verdict
    parser: RobotFileParser | None = None
    crawl_delay: float | None = None
    note: str = ""

    def allows(self, url: str, user_agent: str) -> bool:
        if self.verdict == "missing":
            return True
        if self.verdict == "unavailable" or self.parser is None:
            return False
        return self.parser.can_fetch(user_agent, url)


class RobotsCache:
    """按 host 抓取并缓存 robots.txt。"""

    def __init__(
        self,
        session: requests.Session,
        user_agent: str,
        timeout: float = 10.0,
    ) -> None:
        self.session = session
        self.user_agent = user_agent
        self.timeout = timeout
        self._rules: dict[str, RobotsRules] = {}

    def rules_for(self, url: str) -> RobotsRules:
        origin = _origin(url)
        if origin is None:
            return RobotsRules(
                verdict="unavailable", note="URL 不含主机名，无法定位 robots.txt"
            )

        host_key = urlsplit(origin).netloc
        if host_key not in self._rules:
            self._rules[host_key] = self._load(origin)
        return self._rules[host_key]

    def crawl_delay_for(self, url: str) -> float | None:
        return self.rules_for(url).crawl_delay

    def _load(self, origin: str) -> RobotsRules:
        robots_url = f"{origin}/robots.txt"
        try:
            response = self.session.get(robots_url, timeout=self.timeout)
        except Exception as error:
            # 任何取不到 robots.txt 的原因（网络异常、代理错误、解码问题）都按
            # 不允许处理。这里刻意拦得宽：抓取循环不应因 robots.txt 的意外异常
            # 而中断，而"取不到就不抓"是安全的一侧。
            return RobotsRules(
                verdict="unavailable",
                note=f"robots.txt 获取失败（{type(error).__name__}），按不允许处理",
            )

        with response:
            if response.status_code in (401, 403):
                return RobotsRules(
                    verdict="unavailable",
                    note=f"robots.txt 返回 {response.status_code}，按不允许处理",
                )
            if not response.ok:
                return RobotsRules(
                    verdict="missing",
                    note=f"robots.txt 返回 {response.status_code}，视为无限制",
                )

            text = response.text
            parser = RobotFileParser()
            parser.set_url(robots_url)  # host 决定 Allow/Disallow 的匹配范围
            parser.parse(text.splitlines())

        return RobotsRules(verdict="loaded", parser=parser, crawl_delay=_crawl_delay(parser))


def _origin(url: str) -> str | None:
    """返回 URL 的站点根（scheme + netloc），用于定位 robots.txt。"""
    split = urlsplit(url)
    if not split.scheme or not split.netloc:
        return None
    return urlunsplit((split.scheme, split.netloc, "", "", ""))


def _crawl_delay(parser: RobotFileParser) -> float | None:
    """取 Crawl-delay。

    RobotFileParser 只为"一个" UA 提供 crawl_delay()，且没有公开属性暴露它当前
    用的是哪个 UA（3.14 上连 useragent 属性都不存在）。查 "*" 时它会退回默认
    条目，因此这里直接按通配查询。
    """
    delay = parser.crawl_delay("*")
    if delay is None or delay < 0:
        return None
    return float(delay)
