"""全局配置：读取 config.toml，合并命令行覆盖，校验后交给各模块。

项目里只有本模块会打开 config.toml。其他模块一律通过函数参数接收配置对象
（依赖注入），不得自行读文件、也不得到处硬编码路径。
"""

from __future__ import annotations

import argparse
import dataclasses
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "config.toml"
_SEARCH_UPWARD_LEVELS = 3


class ConfigError(Exception):
    """配置缺失、类型不符或取值非法。"""


def find_config_file(explicit: str | Path | None = None, start: Path | None = None) -> Path:
    """返回 config.toml 的绝对路径。

    explicit 为 None 时，从 start（默认当前工作目录）逐级向上查找。
    """
    if explicit is not None:
        path = Path(explicit).expanduser().resolve()
        if not path.is_file():
            raise ConfigError(f"配置文件不存在：{path}")
        return path

    start = (start or Path.cwd()).resolve()
    for directory in [start, *start.parents[:_SEARCH_UPWARD_LEVELS]]:
        candidate = directory / CONFIG_FILENAME
        if candidate.is_file():
            return candidate

    raise ConfigError(
        f"在 {start} 及其上 {_SEARCH_UPWARD_LEVELS} 级目录中都没有找到 {CONFIG_FILENAME}；"
        "请用 --config 指定路径。"
    )


@dataclass(frozen=True)
class Paths:
    """路径配置。

    所有路径在加载时解析为绝对路径，基准是配置文件所在目录——这样续爬、换
    工作目录执行同一份配置都指向同一份数据（此前 data_dir 是相对 CWD 的字符串，
    换目录续爬会找不到归档）。`~` 会展开；用户显式传入的 --seeds 不在此列。
    """

    data_dir: str
    seeds_file: str
    stopwords: str

    @property
    def crawl_dir(self) -> Path:
        return Path(self.data_dir) / "crawl"

    @property
    def index_dir(self) -> Path:
        return Path(self.data_dir) / "index"

    @property
    def state_path(self) -> Path:
        return Path(self.data_dir) / "state" / "crawl_state.json"


@dataclass(frozen=True)
class Override:
    """一条命令行配置覆盖，形如 --set crawl.max_pages=50。"""

    section: str
    key: str
    raw_value: str

    @classmethod
    def parse(cls, text: str) -> Override:
        if "=" not in text:
            raise ConfigError(f"--set 需要 key=value 形式，收到：{text!r}")
        qualified, _, raw_value = text.partition("=")
        section, _, key = qualified.strip().partition(".")
        if not section or not key:
            raise ConfigError(f"--set 需要 section.key=value 形式，收到：{text!r}")
        return cls(section, key, raw_value)


@dataclass(frozen=True)
class StorageConfig:
    archive_format: str
    manifest_name: str


@dataclass(frozen=True)
class CrawlConfig:
    user_agent: str
    default_delay_seconds: float
    respect_robots: bool
    max_pages: int
    max_pages_per_host: int
    request_timeout: float
    max_retries: int
    retry_backoff_seconds: float
    allowed_hosts: tuple[str, ...] = ()


@dataclass(frozen=True)
class IndexConfig:
    title_weight: float


@dataclass(frozen=True)
class SearchConfig:
    k: int


@dataclass(frozen=True)
class WebConfig:
    host: str
    port: int
    debug: bool


@dataclass(frozen=True)
class Settings:
    """合并后的最终配置。frozen：运行期不可改，避免隐式全局状态。"""

    paths: Paths
    storage: StorageConfig
    crawl: CrawlConfig
    index: IndexConfig
    search: SearchConfig
    web: WebConfig
    config_file: Path

    @classmethod
    def from_file(
        cls,
        config_file: str | Path | None = None,
        start: Path | None = None,
    ) -> Settings:
        """读取配置文件，校验后返回配置。命令行覆盖通过 override() 逐个叠加。"""
        path = find_config_file(config_file, start)
        with path.open("rb") as handle:
            raw = tomllib.load(handle)

        crawler_args = _section(raw, "crawl")
        index_args = _section(raw, "index")
        search_args = _section(raw, "search")
        web_args = _section(raw, "web")

        return cls(
            paths=Paths(
                data_dir=_resolve(
                    _value(raw, "paths", "data_dir"), path.parent, "paths.data_dir"
                ),
                seeds_file=_resolve(
                    _value(raw, "paths", "seeds_file"), path.parent, "paths.seeds_file"
                ),
                stopwords=_resolve(
                    _value(raw, "paths", "stopwords"), path.parent, "paths.stopwords"
                ),
            ),
            storage=StorageConfig(
                archive_format=_choice(
                    _value(raw, "storage", "archive_format"),
                    ("zip",),
                    "storage.archive_format",
                ),
                manifest_name=_text(
                    _value(raw, "storage", "manifest_name"), "storage.manifest_name"
                ),
            ),
            crawl=CrawlConfig(
                user_agent=_text(crawler_args.get("user_agent"), "crawl.user_agent"),
                default_delay_seconds=_number(
                    crawler_args.get("default_delay_seconds"),
                    "crawl.default_delay_seconds",
                    minimum=0.0,
                ),
                respect_robots=_flag(crawler_args.get("respect_robots"), "crawl.respect_robots"),
                max_pages=_count(crawler_args.get("max_pages"), "crawl.max_pages"),
                max_pages_per_host=_count(
                    crawler_args.get("max_pages_per_host"), "crawl.max_pages_per_host"
                ),
                request_timeout=_number(
                    crawler_args.get("request_timeout"),
                    "crawl.request_timeout",
                    minimum=0.1,
                ),
                max_retries=_count(crawler_args.get("max_retries"), "crawl.max_retries"),
                retry_backoff_seconds=_number(
                    crawler_args.get("retry_backoff_seconds"),
                    "crawl.retry_backoff_seconds",
                    minimum=0.0,
                ),
                allowed_hosts=_host_list(crawler_args.get("allowed_hosts")),
            ),
            index=IndexConfig(
                title_weight=_number(
                    index_args.get("title_weight"), "index.title_weight", minimum=0.0
                )
            ),
            search=SearchConfig(k=_count(search_args.get("k"), "search.k", minimum=1)),
            web=WebConfig(
                host=_text(web_args.get("host"), "web.host"),
                port=_count(web_args.get("port"), "web.port", minimum=1, maximum=65535),
                debug=_flag(web_args.get("debug"), "web.debug"),
            ),
            config_file=path,
        )

    def override(self, section: str, key: str, raw_value: str) -> Settings:
        """返回一份应用了单个命令行覆盖的新配置。

        只允许覆盖 crawl / index / search / web 四节。paths 与 storage 属于
        "运行前就应确定"的配置，改它们请直接编辑 config.toml。
        未知节或未知键立即报错，不静默忽略。
        """
        targets = {
            "crawl": self.crawl,
            "index": self.index,
            "search": self.search,
            "web": self.web,
        }
        if section not in targets:
            raise ConfigError(f"配置覆盖的节名无效：{section}（可选：{'/'.join(targets)}）")

        target = targets[section]
        if key not in {field.name for field in dataclasses.fields(target)}:
            raise ConfigError(
                f"配置覆盖的键名无效：{section}.{key}"
                f"（可选：{', '.join(f.name for f in dataclasses.fields(target))}）"
            )

        return dataclasses.replace(
            self,
            **{section: dataclasses.replace(target, **{key: _coerce(key, raw_value)})},
        )


def overrides_from_args(args: argparse.Namespace) -> list[Override]:
    """把 argparse 收集到的 --set 文本转成 Override 列表。"""
    return [Override.parse(text) for text in getattr(args, "set", []) or []]


def config_file_from_args(args: argparse.Namespace) -> Path | None:
    """把 argparse 收集到的 --config 转成路径（未提供时返回 None）。"""
    value = getattr(args, "config", None)
    return Path(value) if value else None


def add_common_args(parser: argparse.ArgumentParser) -> None:
    """给子命令添加统一的配置类命令行参数。"""
    parser.add_argument("--config", metavar="PATH", help="配置文件路径，默认自动向上查找")
    parser.add_argument(
        "--set",
        metavar="SECTION.KEY=VALUE",
        action="append",
        default=[],
        help="临时覆盖一项配置，可重复，例如 --set crawl.max_pages=50",
    )


def print_settings(settings: Settings) -> None:
    """打印生效配置，用于 --print-config 排障。"""
    print(f"config_file = {settings.config_file}")
    for name in ("paths", "storage", "crawl", "index", "search", "web"):
        section = getattr(settings, name)
        print(f"\n[{name}]")
        for field in dataclasses.fields(section):
            print(f"  {field.name} = {getattr(section, field.name)!r}")


# --------------------------------------------------------------------------
# 取值与校验：缺失即报错，不猜默认值
# --------------------------------------------------------------------------

_BOOL_KEYS = {"respect_robots", "debug"}
_COUNT_KEYS = {"max_pages", "max_pages_per_host", "max_retries", "k", "port"}


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    """取一整节。节本身可以是空字典（P0 阶段部分节尚无代码使用）。"""
    section = raw.get(name, {})
    if not isinstance(section, dict):
        raise ConfigError(f"[{name}] 必须是 TOML 表，收到 {type(section).__name__}")
    return dict(section)


def _value(raw: dict[str, Any], section: str, key: str) -> Any:
    return _section(raw, section).get(key)


def _coerce(key: str, value: Any) -> Any:
    if isinstance(value, str):
        if key in _BOOL_KEYS:
            return _flag(value, key)
        if key in _COUNT_KEYS:
            return _count(value, key)
        try:
            return float(value)
        except ValueError as exc:
            raise ConfigError(f"{key} 需要数值，收到 {value!r}") from exc
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    raise ConfigError(f"{key} 的类型不支持：{type(value).__name__}")


def _text(value: Any, key: str) -> str:
    if value is None:
        raise ConfigError(f"配置缺少 {key}（字符串）")
    if not isinstance(value, str):
        raise ConfigError(f"{key} 需要字符串，收到 {type(value).__name__}")
    return value


def _resolve(value: Any, base: Path, key: str) -> str:
    """把配置里的路径解析成绝对路径字符串，基准为配置文件所在目录。"""
    return str(resolve_path(_text(value, key), base))


def resolve_path(value: str | Path, base: Path) -> Path:
    """把用户给出的路径解析为绝对路径。

    相对路径以 base 为基准（配置文件所在目录），而不是当前工作目录——这样
    换目录执行同一份配置，仍然指向同一份数据。
    """
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def _number(value: Any, key: str, minimum: float | None = None) -> float:
    if value is None:
        raise ConfigError(f"配置缺少 {key}（数值）")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{key} 需要数值，收到 {value!r}")
    number = float(value)
    if minimum is not None and number < minimum:
        raise ConfigError(f"{key} 的值 {number} 小于允许的最小值 {minimum}")
    return number


def _count(
    value: Any, key: str, minimum: int = 0, maximum: int | None = None
) -> int:
    if value is None:
        raise ConfigError(f"配置缺少 {key}（整数）")
    if isinstance(value, bool):
        raise ConfigError(f"{key} 需要整数，收到布尔值 {value!r}")
    if isinstance(value, str):
        try:
            value = int(value)
        except ValueError as exc:
            raise ConfigError(f"{key} 需要整数，收到 {value!r}") from exc
    if not isinstance(value, int):
        raise ConfigError(f"{key} 需要整数，收到 {value!r}")
    if value < minimum:
        raise ConfigError(f"{key} 的值 {value} 小于允许的最小值 {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{key} 的值 {value} 大于允许的最大值 {maximum}")
    return value


def _flag(value: Any, key: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "yes", "1", "on"):
            return True
        if normalized in ("false", "no", "0", "off"):
            return False
    raise ConfigError(f"{key} 需要布尔值 true/false，收到 {value!r}")


def _choice(value: Any, allowed: tuple[str, ...], key: str) -> str:
    if value not in allowed:
        raise ConfigError(f"{key} 必须是 {'/'.join(allowed)} 之一，收到 {value!r}")
    return value


def _host_list(value: Any) -> tuple[str, ...]:
    """抓取范围限制：允许的 host 列表。缺省或空列表表示不限。"""
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError("crawl.allowed_hosts 需要字符串数组，例如 [\"ai.ruc.edu.cn\"]")
    return tuple(item.strip().lower() for item in value if item.strip())
