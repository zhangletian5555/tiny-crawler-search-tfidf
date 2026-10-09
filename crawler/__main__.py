"""爬虫入口。

P1 提供单页探测，用于验证抓取链路：
    python -m crawler fetch https://example.com/
P2 提供分桶抓取与归档：
    python -m crawler run                 # 按配置里的种子开一次新抓取
    python -m crawler run --resume        # 从上次中断处继续
"""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from config import (
    ConfigError,
    Settings,
    add_common_args,
    config_file_from_args,
    overrides_from_args,
    print_settings,
)

from .fetcher import create_session, fetch_page
from .frontier import Frontier
from .link_extract import extract_links
from .robots import RobotsCache
from .runner import Crawler, Progress
from .seeds import SeedFileError, read_seeds
from .state import CrawlState, load_state, rebuild_frontier, save_state
from .store import Archive
from .throttle import HostThrottle, delay_for
from tokenizer.segments import parts

DEFAULT_BUCKET_LIMIT = 200
STATE_FILENAME = "crawl_state.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m crawler",
        description="抓取种子站点并归档",
    )
    add_common_args(parser)
    parser.add_argument("--seeds", metavar="PATH", help="种子文件路径，覆盖配置里的 paths.seeds_file")
    parser.add_argument(
        "--print-config", action="store_true", help="打印生效配置与种子数量后退出"
    )

    subparsers = parser.add_subparsers(dest="command")

    fetch_parser = subparsers.add_parser("fetch", help="抓取单个 URL 并打印结果，用于验证链路")
    fetch_parser.add_argument("url", help="要抓取的 URL")

    run_parser = subparsers.add_parser("run", help="按种子抓取并归档")
    run_parser.add_argument("--resume", action="store_true", help="从上次断点继续")
    run_parser.add_argument("--run-dir", metavar="PATH", help="续爬时指定运行目录")
    return parser


def load_settings(args: argparse.Namespace) -> Settings:
    """定位配置文件并应用 --set 覆盖。"""
    settings = Settings.from_file(config_file_from_args(args))
    for override in overrides_from_args(args):
        settings = settings.override(override.section, override.key, override.raw_value)
    return settings


# ----------------------------------------------------------------------
# fetch：单页探测
# ----------------------------------------------------------------------


def run_fetch(settings: Settings, url: str) -> int:
    session = create_session(settings.crawl.user_agent)
    robots = RobotsCache(session, settings.crawl.user_agent, settings.crawl.request_timeout)
    throttle = HostThrottle()

    if settings.crawl.respect_robots:
        rules = robots.rules_for(url)
        if not rules.allows(url, settings.crawl.user_agent):
            print(f"robots.txt 不允许抓取该地址：{url} {rules.note}".strip())
            return 3

    throttle.wait(url, delay_for(url, settings.crawl.default_delay_seconds, robots))
    result = fetch_page(url, settings.crawl, session)

    print(f"URL      : {result.url}")
    print(f"状态     : {result.status if result.status is not None else '未取得响应'}")
    if not result.ok:
        print(f"错误     : {result.error}")
        return 1

    links = extract_links(result.html or "", result.url)
    title, _ = parts(result.html or "")
    print(f"类型     : {result.content_type}")
    print(f"编码     : {result.encoding}")
    print(f"HTML 大小: {len(result.html or '')} 字符")
    print(f"标题     : {title or '（无）'}")
    print(f"可抓链接 : {len(links)}")
    for link in links[:10]:
        print(f"  - {link}")
    if len(links) > 10:
        print(f"  …… 另有 {len(links) - 10} 条")
    return 0


# ----------------------------------------------------------------------
# run：分桶抓取并归档
# ----------------------------------------------------------------------


def _state_path(settings: Settings) -> Path:
    return Path(settings.paths.data_dir) / "state" / STATE_FILENAME


def _bucket_limit(settings: Settings) -> int:
    per_host = settings.crawl.max_pages_per_host
    return per_host if per_host > 0 else DEFAULT_BUCKET_LIMIT


def _start_run(settings: Settings) -> tuple[Archive, Frontier]:
    archive = Archive.create(Path(settings.paths.data_dir) / "crawl", settings.storage.manifest_name)
    frontier = Frontier(bucket_limit=_bucket_limit(settings))
    return archive, frontier


def _resume_run(settings: Settings, state: CrawlState, run_dir: Path | None) -> tuple[Archive, Frontier]:
    """恢复归档与待抓队列。"""
    directory = run_dir or Path(state.run_dir)
    archive = Archive.open(directory, settings.storage.manifest_name)
    frontier = Frontier(bucket_limit=_bucket_limit(settings))

    seen = 0
    for record in archive.load_records():
        frontier.mark_seen(record.url)
        seen += 1
    restored = rebuild_frontier(frontier, state.pending)

    print(f"续爬：归档 {directory}，已抓 {seen} 页，恢复待抓 {restored} 条")
    return archive, frontier


def run_crawl(settings: Settings, args: argparse.Namespace) -> int:
    state_path = _state_path(settings)

    if args.resume:
        state = load_state(state_path)
        if state is None:
            print(f"没有可用的断点：{state_path}", file=sys.stderr)
            return 2
        archive, frontier = _resume_run(
            settings, state, Path(args.run_dir) if args.run_dir else None
        )
        crawled_count = state.crawled_count
    else:
        archive, frontier = _start_run(settings)
        crawled_count = 0
        seed_file = Path(args.seeds) if args.seeds else Path(settings.paths.seeds_file)
        try:
            seeds = read_seeds(seed_file)
        except SeedFileError as error:
            print(f"种子错误：{error}", file=sys.stderr)
            return 2
        for seed in seeds:
            frontier.enqueue(seed, depth=0, seed_url=seed)

    print(f"运行目录：{archive.run_dir}")
    print(f"种子数  ：{len(frontier.as_list())}，单 host 上限 {settings.crawl.max_pages_per_host}，"
          f"总页数上限 {settings.crawl.max_pages or '不限'}，间隔 {settings.crawl.default_delay_seconds}s")

    stop = _StopFlag()
    progress = Progress(frontier)
    progress.count = crawled_count

    crawler = Crawler(
        archive=archive,
        frontier=frontier,
        config=settings.crawl,
        respect_robots=settings.crawl.respect_robots,
        on_page=progress.page,
        on_note=progress.note,
    )

    with stop:
        added = crawler.run(should_stop=stop.requested)

    save_state(
        state_path,
        CrawlState(
            run_dir=str(archive.run_dir),
            crawled_count=crawled_count + added,
            pending=tuple(frontier.as_list()),
        ),
    )

    print(f"\n完成：本次新增 {added} 页，累计 {crawled_count + added} 页，"
          f"待抓 {frontier.pending_count} 条，已见 {frontier.seen_count} 条")
    print(f"归档：{archive.pages_path}")
    print(f"清单：{archive.manifest_path}")
    return 0


class _StopFlag:
    """Ctrl+C 只置位、不抛异常，让主循环在安全点收尾并保存断点。"""

    def __init__(self) -> None:
        self._requested = False
        self._previous: dict[int, object] = {}

    def requested(self) -> bool:
        return self._requested

    def __enter__(self) -> _StopFlag:
        for signum in (signal.SIGINT, signal.SIGTERM):
            self._previous[signum] = signal.getsignal(signum)
            signal.signal(signum, self._handle)
        return self

    def __exit__(self, *exc_info: object) -> None:
        for signum, handler in self._previous.items():
            signal.signal(signum, handler)  # type: ignore[arg-type]

    def _handle(self, signum: int, frame: object) -> None:
        if not self._requested:
            self._requested = True
            print("\n收到中断信号，正在收尾并保存断点（再按一次立即退出）……", flush=True)
            return
        raise KeyboardInterrupt


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = load_settings(args)
    except ConfigError as error:
        print(f"配置错误：{error}", file=sys.stderr)
        return 2

    if args.print_config:
        seed_file = Path(args.seeds) if args.seeds else Path(settings.paths.seeds_file)
        try:
            seeds = read_seeds(seed_file)
        except SeedFileError as error:
            print(f"种子错误：{error}", file=sys.stderr)
            return 2
        print_settings(settings)
        print(f"\n[seeds]\n  file = {seed_file}\n  count = {len(seeds)}")
        return 0

    if args.command == "fetch":
        return run_fetch(settings, args.url)
    if args.command == "run":
        return run_crawl(settings, args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
