"""Web 入口。

    python -m web                     # 用配置里的 host/port 启动
    python -m web --port 8080
    python -m web --index-dir data/index/20260101-000000
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

from .app import create_app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m web", description="启动本地检索页面")
    add_common_args(parser)
    parser.add_argument("--index-dir", metavar="PATH", help="索引目录，默认取最新一次构建")
    parser.add_argument("--host", help="监听地址，默认取配置里的 web.host")
    parser.add_argument("--port", type=int, help="监听端口，默认取配置里的 web.port")
    parser.add_argument("--print-config", action="store_true", help="打印生效配置后退出")
    return parser


def load_settings(args: argparse.Namespace) -> Settings:
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

    if args.print_config:
        print_settings(settings)
        return 0

    app = create_app(settings, Path(args.index_dir) if args.index_dir else None)
    engine = app.config.get("SEARCH_ENGINE")
    if engine is None:
        print(f"提示：索引不可用（{app.config.get('SEARCH_ERROR')}），页面会给出提示。", file=sys.stderr)
    else:
        print(f"索引已加载：{engine.document_count} 篇文档")

    host = args.host or settings.web.host
    port = args.port or settings.web.port
    print(f"服务地址：http://{host}:{port}/")
    app.run(host=host, port=port, debug=settings.web.debug, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
