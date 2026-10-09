"""断点续爬状态：data/state/crawl_state.json。

只保存"还能继续"所需的最小信息：当前运行目录与待抓队列。
已抓页面不必记录——archive 里的 manifest.jsonl 本身就是权威清单。
写入采用"写临时文件 + 原子替换"，避免中断时留下半截文件。
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .frontier import Frontier, PendingPage


@dataclass(frozen=True)
class CrawlState:
    """一次爬取的断点。"""

    run_dir: str
    crawled_count: int
    pending: tuple[PendingPage, ...]


def save_state(path: Path, state: CrawlState) -> None:
    """原子写入检查点。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "run_dir": state.run_dir,
        "crawled_count": state.crawled_count,
        "pending": [asdict(page) for page in state.pending],
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def load_state(path: Path) -> CrawlState | None:
    """读取检查点；文件不存在或已损坏时返回 None。"""
    if not path.is_file():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pending = tuple(PendingPage(**item) for item in data["pending"])
        return CrawlState(
            run_dir=data["run_dir"],
            crawled_count=int(data["crawled_count"]),
            pending=pending,
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def rebuild_frontier(frontier: Frontier, pending: tuple[PendingPage, ...]) -> int:
    """把检查点里的待抓页面放回队列，返回恢复条数。

    用 force 入队：这些页面中断前本就在队列里，不应因为单 host 上限被丢弃。
    """
    restored = 0
    for page in pending:
        if frontier.enqueue(page.url, page.depth, page.seed_url, force=True):
            restored += 1
    return restored
