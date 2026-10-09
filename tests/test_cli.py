"""爬虫入口的装配行为（不触网）。

各入口共用的"切到项目根 + 捕获输出"由 conftest 的 run_cli 夹具提供。
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SEEDS = PROJECT_ROOT / "resources" / "seeds.example.txt"


def test_print_config_reflects_set_overrides(run_cli) -> None:
    code, output = run_cli(
        "--print-config", "--seeds", str(SEEDS), "--set", "crawl.max_pages=7"
    )

    assert code == 0
    assert "max_pages = 7" in output


def test_print_config_reports_seed_count(run_cli) -> None:
    code, output = run_cli("--print-config", "--seeds", str(SEEDS))

    assert code == 0
    assert "count = 15" in output


def test_print_config_without_set_uses_file_value(run_cli) -> None:
    code, output = run_cli("--print-config", "--seeds", str(SEEDS))

    assert code == 0
    assert "max_pages = 200" in output


def test_invalid_override_exits_with_config_error(run_cli) -> None:
    code, _ = run_cli("--print-config", "--set", "crawl.nope=1")

    assert code == 2


def test_missing_seed_file_exits_with_error(run_cli, tmp_path: Path) -> None:
    code, _ = run_cli("--print-config", "--seeds", str(tmp_path / "absent.txt"))

    assert code == 2


def test_seeds_relative_path_is_resolved_against_config_dir(run_cli) -> None:
    """--seeds 相对路径与配置里的路径同规则：基准是配置文件所在目录。

    这里用仓库自带的真配置，只把 --seeds 换成相对路径；若按 CWD 解析会指向
    不存在的位置，从而报错退出。
    """
    code, output = run_cli(
        "--print-config", "--config", str(PROJECT_ROOT / "config.toml"),
        "--seeds", "resources/seeds.example.txt",
    )

    assert code == 0
    assert "count = 15" in output


def test_bare_invocation_prints_help(run_cli) -> None:
    code, output = run_cli()

    assert code == 1
    assert "usage" in output.lower()
