"""索引构建入口的装配行为（不触网）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from indexing.__main__ import main

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    def run(*argv: str) -> tuple[int, str]:
        monkeypatch.chdir(PROJECT_ROOT)
        code = main(list(argv))
        return code, capsys.readouterr().out

    return run


def test_print_config_reflects_set_overrides(cli) -> None:
    code, output = cli("--print-config", "--set", "index.title_weight=3.5")

    assert code == 0
    assert "title_weight = 3.5" in output


def test_paths_cannot_be_overridden_from_cli(cli) -> None:
    """paths 属于"运行前应确定"的配置（见 config.Settings.override 的说明）。"""
    code, _ = cli("--print-config", "--set", "paths.data_dir=/tmp/elsewhere")

    assert code == 2


def test_invalid_override_exits_with_config_error(cli) -> None:
    code, _ = cli("--print-config", "--set", "index.nope=1")

    assert code == 2
