"""索引构建入口的装配行为（不触网）。"""

from __future__ import annotations

from indexing.__main__ import main


def test_print_config_reflects_set_overrides(run_cli) -> None:
    code, output = run_cli("--print-config", "--set", "index.title_weight=3.5", entry=main)

    assert code == 0
    assert "title_weight = 3.5" in output


def test_paths_cannot_be_overridden_from_cli(run_cli) -> None:
    """paths 属于"运行前应确定"的配置（见 config.Settings.override 的说明）。"""
    code, _ = run_cli("--print-config", "--set", "paths.data_dir=/tmp/elsewhere", entry=main)

    assert code == 2


def test_invalid_override_exits_with_config_error(run_cli) -> None:
    code, _ = run_cli("--print-config", "--set", "index.nope=1", entry=main)

    assert code == 2
