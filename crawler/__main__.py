"""爬虫入口。

P1 提供单页探测，用于验证抓取链路：
    python -m crawler fetch https://example.com/
P2 将在此基础上接入按 host 限速、robots.txt、归档与断点续爬。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bs4 import BeautifulSoup

from config import (
    ConfigError,
    Settings,
    add_common_args,
    config_file_from_args,
    overrides_from_args,
    print_settings,
)

from .fetcher import create_session, fetch_page
from .link_extract import extract_links
from .seeds import SeedFileError, read_seeds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m crawler",
        description="抓取种子站点并归档（P1：单页探测）",
    )
    add_common_args(parser)
    parser.add_argument(
        "--seeds",
        metavar="PATH",
        help="种子文件路径，默认取配置里的 paths.seeds_file",
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="打印生效配置与种子数量后退出，不执行抓取",
    )

    subparsers = parser.add_subparsers(dest="command")
    fetch_parser = subparsers.add_parser("fetch", help="抓取单个 URL 并打印结果，用于验证链路")
    fetch_parser.add_argument("url", help="要抓取的 URL")
    return parser


def load_settings(args: argparse.Namespace) -> Settings:
    """定位配置文件并应用 --set 覆盖。"""
    settings = Settings.from_file(config_file_from_args(args))
    for override in overrides_from_args(args):
        settings = settings.override(override.section, override.key, override.raw_value)
    return settings


def run_fetch(settings: Settings, url: str) -> int:
    """抓取一个 URL 并打印结果。"""
    session = create_session(settings.crawl.user_agent)
    result = fetch_page(url, settings.crawl, session)

    print(f"URL      : {result.url}")
    print(f"状态     : {result.status if result.status is not None else '未取得响应'}")

    if not result.ok:
        print(f"错误     : {result.error}")
        return 1

    links = extract_links(result.html or "", result.url)
    title = BeautifulSoup(result.html or "", "lxml").title
    print(f"类型     : {result.content_type}")
    print(f"编码     : {result.encoding}")
    print(f"HTML 大小: {len(result.html or '')} 字符")
    print(f"标题     : {title.get_text(strip=True) if title else '（无）'}")
    print(f"可抓链接 : {len(links)}")
    for link in links[:10]:
        print(f"  - {link}")
    if len(links) > 10:
        print(f"  …… 另有 {len(links) - 10} 条")
    return 0


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

    print("多页抓取尚未实现（P2 接入限速、robots.txt 与归档）。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
