"""待抓队列：按 host 分桶、去重、限制单站扩张。

参考代码用"每个种子一个 queue.Queue"，并在选择下一个 URL 时遍历所有种子做
优先级排序；这里去掉那层复杂度，只保留必要的三件事：同一 URL 只入队一次、
按 host 分桶、单 host 待抓数有上限（否则一次运行会把上万个 URL 写进检查点）。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .link_extract import canonical_host


@dataclass(frozen=True)
class PendingPage:
    """一个待抓页面及其来源信息。"""

    url: str
    host: str
    depth: int
    seed_url: str


class Frontier:
    """按 host 分桶的 FIFO 待抓队列。

    bucket_limit 是"单 host 待抓队列的水位"，不是"单 host 抓取页数上限"——后者
    是 crawl.max_pages_per_host，属于抓取预算。两者混用会导致列表页一多就把链接
    永久丢掉（丢弃的 URL 既不在队列里，也不在检查点里，续爬也补不回来）。
    """

    def __init__(self, bucket_limit: int = 200) -> None:
        self._buckets: dict[str, deque[PendingPage]] = {}
        self._order: deque[str] = deque()
        self._seen: set[str] = set()
        self._bucket_limit = bucket_limit
        self._dropped = 0

    @property
    def seen_count(self) -> int:
        return len(self._seen)

    @property
    def pending_count(self) -> int:
        return sum(len(bucket) for bucket in self._buckets.values())

    @property
    def dropped_count(self) -> int:
        """因单 host 队列水位被拒的 URL 数（已计入 seen，不会再被入队）。"""
        return self._dropped

    def mark_seen(self, url: str) -> None:
        """标记为已处理，之后不再入队。"""
        self._seen.add(url)

    def enqueue(self, url: str, depth: int, seed_url: str, force: bool = False) -> bool:
        """入队一个 URL；已见过、已入队或该 host 桶已满时返回 False。

        force=True 时忽略桶上限，供断点续爬放回原有队列使用。
        """
        if url in self._seen:
            return False
        host = canonical_host(url)
        if host is None:
            return False

        bucket = self._buckets.setdefault(host, deque())
        if not force and len(bucket) >= self._bucket_limit:
            self._dropped += 1
            return False

        if not bucket:
            self._order.append(host)
        bucket.append(PendingPage(url=url, host=host, depth=depth, seed_url=seed_url))
        self._seen.add(url)
        return True

    def next_url(self) -> PendingPage | None:
        """取出下一个待抓页面；队列为空时返回 None。"""
        while self._order:
            host = self._order[0]
            bucket = self._buckets.get(host)
            if not bucket:
                self._buckets.pop(host, None)
                self._order.popleft()
                continue
            page = bucket.popleft()
            if not bucket:
                self._buckets.pop(host, None)
                self._order.popleft()
            return page
        return None

    def pending_in_host(self, host: str) -> int:
        bucket = self._buckets.get(host)
        return len(bucket) if bucket else 0

    def drop_host(self, host: str) -> int:
        """丢弃某个 host 的全部待抓页面，返回条数。

        用于该 host 已达抓取预算的情况：若只是逐条跳过，穷尽型站点会用几千条
        待抓页面把总预算耗光（每次出队都要走一遍 fetch 前的判断）。
        """
        bucket = self._buckets.pop(host, None)
        if not bucket:
            return 0
        if host in self._order:
            self._order.remove(host)
        return len(bucket)

    def as_list(self) -> list[PendingPage]:
        """导出全部待抓页面，用于写检查点。"""
        pages: list[PendingPage] = []
        for host in self._order:
            pages.extend(self._buckets.get(host, ()))
        return pages
