"""断点状态：保存、读取与恢复队列。"""

from __future__ import annotations

from pathlib import Path

from crawler.frontier import Frontier, PendingPage
from crawler.state import CrawlState, load_state, rebuild_frontier, save_state

PAGE = PendingPage(url="https://a.example/", host="a.example", depth=0, seed_url="https://a.example/")


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "state" / "crawl_state.json"
    state = CrawlState(run_dir="/tmp/run-1", crawled_count=7, pending=(PAGE,))

    save_state(path, state)

    assert load_state(path) == state


def test_missing_state_returns_none(tmp_path: Path) -> None:
    assert load_state(tmp_path / "absent.json") is None


def test_corrupt_state_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "crawl_state.json"
    path.write_text("{ 这不是 JSON", encoding="utf-8")

    assert load_state(path) is None


def test_incomplete_state_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "crawl_state.json"
    path.write_text('{"run_dir": "/tmp/x"}', encoding="utf-8")

    assert load_state(path) is None


def test_save_is_atomic(tmp_path: Path) -> None:
    path = tmp_path / "crawl_state.json"
    save_state(path, CrawlState("/tmp/run-1", 1, (PAGE,)))
    save_state(path, CrawlState("/tmp/run-1", 2, ()))

    assert load_state(path).crawled_count == 2  # type: ignore[union-attr]
    assert not path.with_suffix(path.suffix + ".tmp").exists()


def test_rebuild_frontier_restores_pending() -> None:
    frontier = Frontier()
    pending = (
        PAGE,
        PendingPage(url="https://a.example/2", host="a.example", depth=1, seed_url="https://a.example/"),
    )

    restored = rebuild_frontier(frontier, pending)

    assert restored == 2
    assert frontier.pending_count == 2


def test_rebuild_frontier_exceeds_bucket_limit_on_purpose() -> None:
    # 断点里已有的页面不应因为单 host 上限被丢掉
    frontier = Frontier(bucket_limit=1)
    pending = (
        PAGE,
        PendingPage(url="https://a.example/2", host="a.example", depth=1, seed_url="https://a.example/"),
    )

    assert rebuild_frontier(frontier, pending) == 2
