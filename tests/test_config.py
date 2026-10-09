"""config 模块：默认值加载、命令行覆盖、非法取值报错。"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import ConfigError, Override, Settings, config_file_from_args, find_config_file

PROJECT_ROOT = Path(__file__).resolve().parent.parent

VALID_CONFIG = """
[paths]
data_dir = "data"
seeds_file = "resources/seeds.example.txt"
stopwords = "tokenizer/stopwords_zh.txt"

[storage]
archive_format = "zip"
manifest_name = "manifest.jsonl"

[crawl]
user_agent = "test-agent/0.1"
default_delay_seconds = 1.5
respect_robots = true
max_pages = 200
max_pages_per_host = 50
request_timeout = 10.0
max_retries = 2
retry_backoff_seconds = 2.0

[index]
title_weight = 2.0

[search]
k = 20

[web]
host = "127.0.0.1"
port = 8000
debug = false
"""


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(VALID_CONFIG, encoding="utf-8")
    return path


def test_loads_all_sections(config_file: Path) -> None:
    settings = Settings.from_file(config_file)

    assert settings.paths.data_dir == "data"
    assert settings.storage.archive_format == "zip"
    assert settings.crawl.user_agent == "test-agent/0.1"
    assert settings.crawl.default_delay_seconds == 1.5
    assert settings.crawl.respect_robots is True
    assert settings.crawl.max_pages == 200
    assert settings.search.k == 20
    assert settings.web.port == 8000
    assert settings.config_file == config_file


def test_missing_key_is_reported(config_file: Path) -> None:
    config_file.write_text('[paths]\ndata_dir = "data"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="paths.seeds_file"):
        Settings.from_file(config_file)


def test_wrong_type_is_reported(config_file: Path) -> None:
    config_file.write_text(
        VALID_CONFIG.replace('default_delay_seconds = 1.5', 'default_delay_seconds = "soon"'),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="default_delay_seconds"):
        Settings.from_file(config_file)


def test_unknown_archive_format_is_reported(config_file: Path) -> None:
    config_file.write_text(
        VALID_CONFIG.replace('archive_format = "zip"', 'archive_format = "rar"'),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="rar"):
        Settings.from_file(config_file)


def test_override_replaces_one_value(config_file: Path) -> None:
    settings = Settings.from_file(config_file).override("crawl", "max_pages", "50")

    assert settings.crawl.max_pages == 50
    assert settings.crawl.default_delay_seconds == 1.5  # 未覆盖的字段不变
    assert settings.index.title_weight == 2.0


def test_override_rejects_unknown_key(config_file: Path) -> None:
    settings = Settings.from_file(config_file)

    with pytest.raises(ConfigError, match="crawl.nonexistent"):
        settings.override("crawl", "nonexistent", "1")


def test_override_rejects_unknown_section(config_file: Path) -> None:
    settings = Settings.from_file(config_file)

    with pytest.raises(ConfigError, match="nope"):
        settings.override("nope", "k", "1")


def test_missing_config_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="配置文件不存在"):
        find_config_file(tmp_path / "absent.toml")


def test_finds_project_config_from_subdirectory() -> None:
    found = find_config_file(None, start=PROJECT_ROOT / "tokenizer")

    assert found == PROJECT_ROOT / "config.toml"


def test_override_parses_set_syntax() -> None:
    override = Override.parse("crawl.max_pages=50")

    assert (override.section, override.key, override.raw_value) == ("crawl", "max_pages", "50")


def test_override_rejects_bad_syntax() -> None:
    with pytest.raises(ConfigError):
        Override.parse("crawl.max_pages")

    with pytest.raises(ConfigError):
        Override.parse("max_pages=50")


def test_config_file_from_args() -> None:
    class Args:
        config = None

    assert config_file_from_args(Args()) is None

    Args.config = "somewhere/config.toml"
    assert config_file_from_args(Args()) == Path("somewhere/config.toml")
