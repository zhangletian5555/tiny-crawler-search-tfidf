"""allowed_hosts 范围限制：匹配规则 + 在抓取循环里真正生效。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from config import ConfigError, Settings
from crawler.link_extract import host_is_allowed

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_TEMPLATE_PATH = PROJECT_ROOT / "config.toml"

RUC_AI = "https://ai.ruc.edu.cn/"
RUC_PHYS = "http://www.phys.ruc.edu.cn/"
OUTSIDE = "https://mp.weixin.qq.com/s/abc"


def test_empty_list_allows_everything() -> None:
    assert host_is_allowed(OUTSIDE, ()) is True
    assert host_is_allowed(RUC_AI, ()) is True


def test_exact_host_matches() -> None:
    assert host_is_allowed(RUC_AI, ("ai.ruc.edu.cn",)) is True
    assert host_is_allowed(OUTSIDE, ("ai.ruc.edu.cn",)) is False


def test_domain_suffix_matches_subdomains() -> None:
    allowed = ("ruc.edu.cn",)

    assert host_is_allowed(RUC_AI, allowed) is True
    assert host_is_allowed(RUC_PHYS, allowed) is True
    assert host_is_allowed("https://news.ruc.edu.cn/", allowed) is True
    assert host_is_allowed("https://ruc.edu.cn/", allowed) is True
    assert host_is_allowed(OUTSIDE, allowed) is False


def test_suffix_match_does_not_leak_to_lookalike_domain() -> None:
    """后缀相近的域名不应被放行。"""
    assert host_is_allowed("https://notruc.edu.cn/", ("ruc.edu.cn",)) is False
    assert host_is_allowed("https://ruc.edu.cn.evil.com/", ("ruc.edu.cn",)) is False


def test_port_is_ignored_when_matching() -> None:
    assert host_is_allowed("http://ai.ruc.edu.cn:8080/x", ("ai.ruc.edu.cn",)) is True


def test_host_without_scheme_is_rejected() -> None:
    assert host_is_allowed("/relative/path", ("ruc.edu.cn",)) is False


def write_config(tmp_path: Path, raw_value: str) -> Path:
    """把 allowed_hosts 插进一份真配置的 [crawl] 段。"""
    template = CONFIG_TEMPLATE_PATH.read_text(encoding="utf-8")
    config = tmp_path / "config.toml"
    config.write_text(
        template.replace(
            'retry_backoff_seconds = 2.0',
            f'retry_backoff_seconds = 2.0\nallowed_hosts = {raw_value}',
        ),
        encoding="utf-8",
    )
    return config


def test_allowed_hosts_is_lowercased_and_trimmed(tmp_path: Path) -> None:
    config = write_config(tmp_path, '["  AI.RUC.EDU.CN  ", ""]')

    assert Settings.from_file(config).crawl.allowed_hosts == ("ai.ruc.edu.cn",)


@pytest.mark.parametrize("raw_value", ['"ai.ruc.edu.cn"', "[1, 2]", "true"])
def test_invalid_allowed_hosts_is_reported(tmp_path: Path, raw_value: str) -> None:
    config = write_config(tmp_path, raw_value)

    with pytest.raises(ConfigError, match="allowed_hosts"):
        Settings.from_file(config)


def test_default_is_unrestricted(tmp_path: Path) -> None:
    config = write_config(tmp_path, '[]')

    assert Settings.from_file(config).crawl.allowed_hosts == ()


def test_crawler_skips_out_of_scope_links(tmp_path: Path) -> None:
    """抓取循环里范围外链接不入队，且计数可见。"""
    from test_runner import CONFIG, build

    crawler, _, frontier, _ = build(
        tmp_path, replace(CONFIG, allowed_hosts=("site.example",))
    )

    crawler.run()

    # 语料里 other.example 是唯一的外站，应被挡下
    assert crawler.out_of_scope >= 1
    assert frontier.pending_in_host("other.example") == 0
