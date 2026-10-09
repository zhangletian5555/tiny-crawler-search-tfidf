"""检索入口的装配行为（不触网）。"""

from __future__ import annotations

from pathlib import Path

from search.__main__ import main


def test_print_config_reflects_set_overrides(run_cli) -> None:
    code, output = run_cli("--print-config", "--set", "search.k=5", entry=main)

    assert code == 0
    assert "k = 5" in output


def test_missing_index_is_reported(run_cli, tmp_path: Path) -> None:
    """索引目录不存在时给出明确提示，而不是抛栈。"""
    code, _ = run_cli("查询", "--index-dir", str(tmp_path / "absent"), entry=main)

    assert code == 2


def test_index_without_builds_is_reported(run_cli, tmp_path: Path) -> None:
    (tmp_path / "index").mkdir()

    code, _ = run_cli("查询", "--index-dir", str(tmp_path / "index"), entry=main)

    assert code == 2


def test_invalid_override_exits_with_config_error(run_cli) -> None:
    code, _ = run_cli("--print-config", "--set", "search.nope=1", entry=main)

    assert code == 2
