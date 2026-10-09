"""索引构建入口。

    python -m indexing                      # 索引 data/crawl 下最新的运行
    python -m indexing --run-dir data/crawl/20260101-000000
    python -m indexing --print-config       # 只打印生效配置
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cli import CliError, load_settings, print_config_if_requested, report_error
from config import Settings, add_common_args
from runtime import latest_subdirectory
from tokenizer.stopwords import StopwordFileError, load_stopwords

from .builder import IndexStats, build_index
from .writer import write_index


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m indexing",
        description="读取抓取归档并构建 TF-IDF 索引",
    )
    add_common_args(parser)
    parser.add_argument("--run-dir", metavar="PATH", help="要索引的抓取运行目录，默认取最新一次")
    parser.add_argument("--print-config", action="store_true", help="打印生效配置后退出")
    return parser


def latest_run(crawl_dir: Path) -> Path:
    """取目录名最大的一次运行（运行目录按时间戳命名）。"""
    return latest_subdirectory(crawl_dir, "抓取运行")


def run_indexing(settings: Settings, run_dir: Path | None) -> int:
    crawl_root = settings.paths.crawl_dir
    try:
        source = run_dir or latest_run(crawl_root)
    except FileNotFoundError as error:
        print(f"无法索引：{error}", file=sys.stderr)
        return 2

    try:
        stopwords = load_stopwords(settings.paths.stopwords)
    except StopwordFileError as error:
        print(f"停用词错误：{error}", file=sys.stderr)
        return 2

    print(f"源归档  ：{source}")
    print(f"标题权重：{settings.index.title_weight}")

    stats: IndexStats = build_index(
        source,
        stopwords=stopwords,
        title_weight=settings.index.title_weight,
        manifest_name=settings.storage.manifest_name,
    )
    if not stats.documents:
        print("归档里没有可索引的文档。", file=sys.stderr)
        return 1

    index_dir = write_index(
        settings.paths.index_dir,
        stats,
        source_run=source.name,
        title_weight=settings.index.title_weight,
    )

    print(f"文档数  ：{stats.document_count}")
    if stats.duplicates_skipped:
        print(f"去重跳过：{stats.duplicates_skipped} 篇（同一内容的不同入口，如 http/https）")
    print(f"词条数  ：{len(stats.terms)}")
    print(f"平均长度：标题 {stats.avg_title_len:.1f} / 正文 {stats.avg_body_len:.1f}")
    print(f"索引目录：{index_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = load_settings(args)
        if print_config_if_requested(args, settings):
            return 0
    except CliError as error:
        return report_error(error)

    return run_indexing(settings, Path(args.run_dir) if args.run_dir else None)


if __name__ == "__main__":
    raise SystemExit(main())
