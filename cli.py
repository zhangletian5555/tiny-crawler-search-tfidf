"""命令行入口的共用部分。

四个入口（crawler / indexing / search / web）原先各自抄了一遍
"解析 --config 与 --set → 读配置 → 处理配置错误 → 处理 --print-config"。
行为一致的部分收在这里，各入口特有的参数与业务分支留在自己的 __main__.py。

选异常而不是"返回可能为 None 的配置"：调用方写
`settings = load_settings(args)` 就能拿到非空配置，出错路径单独 except，
不必在每个入口里判空或写 type: ignore。
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from config import (
    ConfigError,
    Settings,
    config_file_from_args,
    overrides_from_args,
    print_settings,
)


class CliError(Exception):
    """入口层的可预期失败（配置有误等）。调用方转为退出码 2。"""


def load_settings(args: argparse.Namespace) -> Settings:
    """读取配置并应用 --set 覆盖。"""
    try:
        settings = Settings.from_file(config_file_from_args(args))
        for override in overrides_from_args(args):
            settings = settings.override(override.section, override.key, override.raw_value)
    except ConfigError as error:
        raise CliError(f"配置错误：{error}") from error
    return settings


def print_config_if_requested(
    args: argparse.Namespace,
    settings: Settings,
    extra: Callable[[], None] | None = None,
) -> bool:
    """带 --print-config 时打印生效配置并返回 True，否则返回 False。

    extra 用于追加各入口特有的信息（例如种子文件与条数）。
    """
    if not getattr(args, "print_config", False):
        return False

    print_settings(settings)
    if extra is not None:
        extra()
    return True


def report_error(error: Exception) -> int:
    """把入口层的可预期失败打印成一行，返回约定退出码 2。"""
    print(error, file=sys.stderr)
    return 2
