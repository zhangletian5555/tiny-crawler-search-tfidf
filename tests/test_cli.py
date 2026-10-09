"""命令行入口的装配行为（不触网）。

抓取逻辑本身由 test_runner / test_fetcher 覆盖，这里只验证参数与配置的接线，
特别是 --print-config 必须反映 --set 之后的值。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from crawler.__main__ import main

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEEDS = PROJECT_ROOT / "resources" / "seeds.example.txt"


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    """以项目配置运行 CLI，返回 (退出码, 标准输出)。"""

    def run(*argv: str) -> tuple[int, str]:
        monkeypatch.chdir(PROJECT_ROOT)
        code = main(list(argv))
        return code, capsys.readouterr().out

    return run


def test_print_config_reflects_set_overrides(cli) -> None:
    code, output = cli(
        "--print-config", "--seeds", str(SEEDS), "--set", "crawl.max_pages=7"
    )

    assert code == 0
    assert "max_pages = 7" in output


def test_print_config_reports_seed_count(cli) -> None:
    code, output = cli("--print-config", "--seeds", str(SEEDS))

    assert code == 0
    assert "count = 15" in output


def test_print_config_without_set_uses_file_value(cli) -> None:
    code, output = cli("--print-config", "--seeds", str(SEEDS))

    assert code == 0
    assert "max_pages = 200" in output


def test_invalid_override_exits_with_config_error(cli) -> None:
    code, _ = cli("--print-config", "--set", "crawl.nope=1")

    assert code == 2


def test_missing_seed_file_exits_with_error(cli, tmp_path: Path) -> None:
    code, _ = cli("--print-config", "--seeds", str(tmp_path / "absent.txt"))

    assert code == 2


def test_seeds_relative_path_is_resolved_against_config_dir(cli) -> None:
    """--seeds 相对路径与配置里的路径同规则：基准是配置文件所在目录。

    这里用仓库自带的真配置，只把 --seeds 换成相对路径；若按 CWD 解析会指向
    不存在的位置，从而报错退出。
    """
    code, output = cli(
        "--print-config", "--config", str(PROJECT_ROOT / "config.toml"),
        "--seeds", "resources/seeds.example.txt",
    )

    assert code == 0
    assert "count = 15" in output


def test_bare_invocation_prints_help(cli) -> None:
    code, output = cli()

    assert code == 1
    assert "usage" in output.lower()
