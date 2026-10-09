"""检索入口的装配行为（不触网）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from search.__main__ import main

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    def run(*argv: str) -> tuple[int, str]:
        monkeypatch.chdir(PROJECT_ROOT)
        code = main(list(argv))
        return code, capsys.readouterr().out

    return run


def test_print_config_reflects_set_overrides(cli) -> None:
    code, output = cli("--print-config", "--set", "search.k=5")

    assert code == 0
    assert "k = 5" in output


def test_missing_index_is_reported(cli, tmp_path: Path) -> None:
    """索引目录不存在时给出明确提示，而不是抛栈。"""
    code, _ = cli("查询", "--index-dir", str(tmp_path / "absent"))

    assert code == 2


def test_index_without_builds_is_reported(cli, tmp_path: Path) -> None:
    (tmp_path / "index").mkdir()

    code, _ = cli("查询", "--index-dir", str(tmp_path / "index"))

    assert code == 2


def test_invalid_override_exits_with_config_error(cli) -> None:
    code, _ = cli("--print-config", "--set", "search.nope=1")

    assert code == 2
