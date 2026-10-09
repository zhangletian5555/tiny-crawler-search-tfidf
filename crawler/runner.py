"""抓取主循环：把 frontier、robots、throttle、fetcher、archive 串起来。

一条页面记录的产生顺序：
    frontier 取 URL → robots 判定 → 限速等待 → fetch → 归档 → 记录元数据
    → 提取链接 → 入队
停止条件：待抓队列空、达到 max_pages、或调用方要求停止（Ctrl+C）。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone

from config import CrawlConfig

from .fetcher import FetchResult, create_session, fetch_page
from .frontier import Frontier
from .link_extract import extract_links
from .robots import RobotsCache
from .store import Archive, RunRecord, document_id
from .throttle import HostThrottle, make_throttle
from tokenizer.segments import embedded_date, parts


class Crawler:
    """一次运行的抓取执行者。"""

    def __init__(
        self,
        archive: Archive,
        frontier: Frontier,
        config: CrawlConfig,
        respect_robots: bool = True,
        on_page: Callable[[RunRecord], None] | None = None,
        on_note: Callable[[str], None] | None = None,
    ) -> None:
        self.archive = archive
        self.frontier = frontier
        self.config = config
        self.respect_robots = respect_robots
        self.on_page = on_page
        self.on_note = on_note or (lambda note: None)

        self.session = create_session(config.user_agent)
        self.robots = RobotsCache(self.session, config.user_agent, config.request_timeout)
        self.throttle = make_throttle(
            HostThrottle(),
            config.default_delay_seconds,
            self.robots if respect_robots else None,
        )
        self.crawled_count = 0

    def run(self, should_stop: Callable[[], bool] | None = None) -> int:
        """执行抓取，返回本次新抓取的页面数。"""
        stop = should_stop or (lambda: False)
        try:
            while not stop() and self._under_limit():
                page = self.frontier.next_url()
                if page is None:
                    break
                self._visit(page)
        finally:
            self.archive.close()
            self.session.close()
        return self.crawled_count

    # ------------------------------------------------------------------
    # 内部步骤
    # ------------------------------------------------------------------

    def _under_limit(self) -> bool:
        limit = self.config.max_pages
        return limit <= 0 or self.crawled_count < limit

    def _visit(self, page) -> None:  # type: ignore[no-untyped-def]
        if self.respect_robots:
            rules = self.robots.rules_for(page.url)
            if not rules.allows(page.url, self.config.user_agent):
                self.on_note(f"robots.txt 不允许，跳过：{page.url} {rules.note}".strip())
                return

        result = fetch_page(page.url, self.config, self.session, throttle=self.throttle)
        record = self._record(page, result)
        if record is None:
            return

        self.crawled_count += 1
        if self.on_page is not None:
            self.on_page(record)

        for link in extract_links(result.html or "", result.url):
            self.frontier.enqueue(link, page.depth + 1, page.seed_url)

    def _record(self, page, result: FetchResult):  # type: ignore[no-untyped-def]
        """把一次抓取结果写入归档，返回记录；非网页内容不写入。"""
        if not result.ok:
            self.on_note(f"抓取失败：{page.url}（{result.error}）")
            return None

        title, body = parts(result.html or "")
        doc_id = document_id(result.url)
        html = result.html or ""
        member = self.archive.write_page(doc_id, html)

        record = RunRecord(
            doc_id=doc_id,
            url=result.url,
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            status=result.status,
            content_type=result.content_type,
            title=title,
            embedded_date=embedded_date(body),
            body_bytes=len(html.encode("utf-8")),
            archive_member=member,
            seed_url=page.seed_url,
            depth=page.depth,
        )
        self.archive.append(record)
        return record


class Progress:
    """把抓取进度打印到标准输出。"""

    def __init__(self, frontier: Frontier, started: float | None = None) -> None:
        self.frontier = frontier
        self.started = started if started is not None else time.monotonic()
        self.count = 0

    def page(self, record: RunRecord) -> None:
        self.count += 1
        elapsed = time.monotonic() - self.started
        self._write(
            f"[{self.count:>4}] {record.status} {record.title[:40] or '(无标题)'} "
            f"| {record.url} | 待抓 {self.frontier.pending_count} | {elapsed:.0f}s"
        )

    def note(self, message: str) -> None:
        self._write(f"       {message}")

    def _write(self, line: str) -> None:
        print(line, flush=True)
