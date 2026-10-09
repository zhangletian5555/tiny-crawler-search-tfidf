"""爬虫入口。

目前只完成配置自检：加载配置、读取种子、按 --print-config 决定是否继续。
抓取流程在后续阶段接入。种子路径可用 --seeds 覆盖配置里的 paths.seeds_file。
"""

from __future__ import annotations

import argparse
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

from .seeds import SeedFileError, read_seeds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m crawler",
        description="抓取种子站点并归档（当前阶段：仅配置自检）",
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
    return parser


def load_settings(args: argparse.Namespace) -> Settings:
    """定位配置文件并应用 --set 覆盖。"""
    settings = Settings.from_file(config_file_from_args(args))
    for override in overrides_from_args(args):
        settings = settings.override(override.section, override.key, override.raw_value)
    return settings


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = load_settings(args)
    except ConfigError as error:
        print(f"配置错误：{error}", file=sys.stderr)
        return 2

    seed_file = Path(args.seeds) if args.seeds else Path(settings.paths.seeds_file)
    try:
        seeds = read_seeds(seed_file)
    except SeedFileError as error:
        print(f"种子错误：{error}", file=sys.stderr)
        return 2

    if args.print_config:
        print_settings(settings)
        print(f"\n[seeds]\n  file = {seed_file}\n  count = {len(seeds)}")
        return 0

    print("抓取流程尚未实现（当前阶段只完成配置加载与种子读取）。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
