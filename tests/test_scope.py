"""allowed_hosts 范围限制：匹配规则 + 在抓取循环里真正生效。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from config import ConfigError, Settings
from crawler.link_extract import canonical_host, host_is_allowed, url_host

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


def test_canonical_host_unifies_scheme_and_www() -> None:
    """同一站点的不同写法必须归一到同一个键。

    这是真实抓取暴露的问题：`https://ai.ruc.edu.cn` 与 `http://ai.ruc.edu.cn`
    在 url_host 下是两个键，导致单站预算被同一个站点花了两遍。
    """
    forms = [
        "https://ai.ruc.edu.cn/",
        "http://ai.ruc.edu.cn/index.htm",
        "https://www.ai.ruc.edu.cn/x",
        "https://ai.ruc.edu.cn:443/x",
    ]
    assert {canonical_host(url) for url in forms} == {"ai.ruc.edu.cn"}

    # url_host 仍按"服务器"归组（端口不同视为不同服务），两者用途不同
    assert url_host("https://ai.ruc.edu.cn/") == "ai.ruc.edu.cn"
    assert url_host("https://ai.ruc.edu.cn:8443/") == "ai.ruc.edu.cn:8443"


def test_canonical_host_rejects_unparsable_url() -> None:
    assert canonical_host("/relative/path") is None


def test_budget_is_shared_across_scheme_variants(tmp_path: Path) -> None:
    """http/https/www 写法共用一份单站预算（回归：同一站点曾花掉两份预算）。"""
    from test_runner import CONFIG, FakeResponse, build

    https_home = "https://dual.example/"
    http_home = "http://dual.example/"
    pages = {
        https_home: (
            '<html><head><title>HTTPS 首页</title></head><body>'
            '<a href="https://dual.example/a">a</a>'
            '<a href="https://dual.example/b">b</a></body></html>'
        ),
        http_home: (
            '<html><head><title>HTTP 首页</title></head><body>'
            '<a href="http://dual.example/c">c</a></body></html>'
        ),
        "https://dual.example/a": "<html><head><title>a</title></head><body>a</body></html>",
        "https://dual.example/b": "<html><head><title>b</title></head><body>b</body></html>",
        "http://dual.example/c": "<html><head><title>c</title></head><body>c</body></html>",
    }

    class DualSession:
        def get(self, url: str, **kwargs: object) -> FakeResponse:
            if url not in pages:
                return FakeResponse(status_code=404, url=url)
            return FakeResponse(text=pages[url], url=url)

        def close(self) -> None:
            return None

    crawler, archive, frontier, _ = build(
        tmp_path, replace(CONFIG, max_pages_per_host=1, allowed_hosts=("dual.example",))
    )
    crawler.session = DualSession()  # type: ignore[assignment]
    frontier.enqueue(http_home, depth=0, seed_url=http_home)

    crawler.run()

    dual_pages = [
        record for record in archive.load_records() if "dual.example" in record.url
    ]
    assert len(dual_pages) == 1, "同一主机名的 http/https 变体应共用单站预算"
