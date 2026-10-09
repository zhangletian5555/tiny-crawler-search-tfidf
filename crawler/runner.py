"""抓取主循环：把 frontier、robots、throttle、fetcher、archive 串起来。

一条页面记录的产生顺序：
    frontier 取 URL → robots 判定 → 限速等待 → fetch → 归档 → 记录元数据
    → 提取链接 → 入队
停止条件：待抓队列空、达到 max_pages、或调用方要求停止（Ctrl+C）。
"""

from __future__ import annotations

import time
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime

import requests

from config import CrawlConfig
from tokenizer.segments import embedded_date, parts

from .fetcher import FetchResult, create_session, fetch_page
from .frontier import Frontier, PendingPage
from .link_extract import extract_links
from .robots import RobotsCache
from .store import Archive, RunRecord, document_id
from .throttle import HostThrottle, make_throttle


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
        session: requests.Session | None = None,
        robots: RobotsCache | None = None,
    ) -> None:
        self.archive = archive
        self.frontier = frontier
        self.config = config
        self.respect_robots = respect_robots
        self.on_page = on_page
        self.on_note = on_note or (lambda *_: None)

        self.session = session or create_session(config.user_agent)
        self.robots = robots or RobotsCache(
            self.session, config.user_agent, config.request_timeout
        )
        self.throttle = make_throttle(
            HostThrottle(),
            config.default_delay_seconds,
            self.robots if respect_robots else None,
        )
        self.crawled_count = 0
        # 单 host 已抓页数：max_pages_per_host 是抓取预算，必须真正生效
        self._crawled_per_host: dict[str, int] = defaultdict(int)
        # 因单 host 预算被丢弃的待抓页面数
        self.budget_skipped = 0
        # 已写入归档的主键。zip 的 writestr 不会覆盖同名成员，重复写入会留下
        # 取不到的滞留数据，因此在写入前就按主键去重。
        self._written: set[str] = set()

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
            # 关闭会话是调用方（Crawler 的拥有者）的责任：这里只收尾归档。
            # Crawler 结束运行后不再发请求，会话是否复用由调用方决定。
            self.archive.close()
        return self.crawled_count

    # ------------------------------------------------------------------
    # 内部步骤
    # ------------------------------------------------------------------

    def _under_limit(self) -> bool:
        limit = self.config.max_pages
        return limit <= 0 or self.crawled_count < limit

    def _visit(self, page: PendingPage) -> None:
        if self._host_budget_exhausted(page.host):
            return

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
        self._crawled_per_host[page.host] += 1
        if self.on_page is not None:
            self.on_page(record)

        for link in extract_links(result.html or "", result.url):
            self.frontier.enqueue(link, page.depth + 1, page.seed_url)

    def _host_budget_exhausted(self, host: str) -> bool:
        """该 host 是否已达抓取预算；达到则把它的待抓页面整批丢掉。

        丢掉的 URL 不标记为已见，因此别的页面再链到它们时会被重新入队、再被
        本次判断丢掉——重复入队是有界的（bounded by 该 host 的出链数），换来的
        好处是不必为"已放弃的 host"维护一份额外的已见集合。
        """
        budget = self.config.max_pages_per_host
        if budget <= 0 or self._crawled_per_host.get(host, 0) < budget:
            return False

        dropped = self.frontier.drop_host(host)
        if dropped:
            self.budget_skipped += dropped
            self.on_note(
                f"{host} 已达单 host 上限 {budget} 页，"
                f"放弃其余 {dropped} 条待抓链接（如需收录请调大 max_pages_per_host）"
            )
        return True

    def _record(self, page: PendingPage, result: FetchResult) -> RunRecord | None:
        """把一次抓取结果写入归档，返回记录；非网页内容或重复页面返回 None。"""
        if not result.ok:
            self.on_note(f"抓取失败：{page.url}（{result.error}）")
            return None

        html = result.html or ""
        title, body = parts(html)
        # 主键取自重定向后的最终 URL，这样同一内容的不同入口会归并为一篇文档
        doc_id = document_id(result.final_url)
        if doc_id in self._written:
            self.on_note(f"重复页面，跳过：{result.final_url}（请求自 {page.url}）")
            return None

        member = self.archive.write_page(doc_id, html)
        self._written.add(doc_id)

        record = RunRecord(
            doc_id=doc_id,
            url=result.url,
            final_url=result.final_url,
            fetched_at=datetime.now(UTC).isoformat(timespec="seconds"),
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

    def __init__(
        self,
        frontier: Frontier,
        started: float | None = None,
        initial_count: int = 0,
    ) -> None:
        self.frontier = frontier
        self.started = started if started is not None else time.monotonic()
        self.count = initial_count

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
