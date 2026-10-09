"""检索入口。

    python -m search 人工智能              # 单次查询
    python -m search                        # 交互式反复查询（便于对比排序）
    python -m search --print-config
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cli import CliError, load_settings, print_config_if_requested, report_error
from config import Settings, add_common_args
from tokenizer.stopwords import StopwordFileError, load_stopwords

from .engine import IndexFormatError, SearchEngine, latest_index, load_index


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m search",
        description="在已构建的索引上做 TF-IDF 检索",
    )
    add_common_args(parser)
    parser.add_argument("query", nargs="*", help="查询词；不提供则进入交互模式")
    parser.add_argument("--index-dir", metavar="PATH", help="索引目录，默认取最新一次构建")
    parser.add_argument("-k", "--top-k", type=int, metavar="N", help="返回条数，默认取配置里的 search.k")
    parser.add_argument("--print-config", action="store_true", help="打印生效配置后退出")
    return parser


def run_search(settings: Settings, args: argparse.Namespace) -> int:
    try:
        index_dir = Path(args.index_dir) if args.index_dir else latest_index(settings.paths.index_dir)
    except FileNotFoundError as error:
        print(f"无法检索：{error}", file=sys.stderr)
        return 2

    try:
        stopwords = load_stopwords(settings.paths.stopwords)
    except StopwordFileError as error:
        print(f"停用词错误：{error}", file=sys.stderr)
        return 2

    try:
        engine = load_index(index_dir, stopwords)
    except (IndexFormatError, FileNotFoundError, KeyError) as error:
        print(f"索引无法加载：{error}", file=sys.stderr)
        return 2

    top_k = args.top_k or settings.search.k
    print(f"索引：{index_dir}（{engine.document_count} 篇文档，title_weight={engine.title_weight}）")

    if args.query:
        _report(engine, " ".join(args.query), top_k)
        return 0

    return _interactive(engine, top_k)


def _interactive(engine: SearchEngine, top_k: int) -> int:
    print("输入查询词后回车；空行或 Ctrl+C 退出。")
    while True:
        try:
            text = input("query> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not text:
            return 0
        _report(engine, text, top_k)


def _report(engine: SearchEngine, text: str, top_k: int) -> None:
    results = engine.search(text, k=top_k)
    if not results:
        print(f"「{text}」没有命中任何文档。")
        return

    print(f"\n「{text}」命中 {len(results)} 条：")
    for rank, result in enumerate(results, start=1):
        print(f"  {rank:>3}. {result.score:.5f}  {result.title or '(无标题)'}")
        print(f"       {result.url}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = load_settings(args)
        if print_config_if_requested(args, settings):
            return 0
    except CliError as error:
        return report_error(error)

    return run_search(settings, args)


if __name__ == "__main__":
    raise SystemExit(main())
