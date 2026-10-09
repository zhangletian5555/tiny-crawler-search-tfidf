"""pytest 共享夹具。

- 把项目根目录加入导入路径（项目以可编辑方式安装，但这样对直接跑源码也成立）；
- `run_cli` 夹具：三个入口的 `--print-config` 测试原先各抄了一份同样的
  "切到项目根 + 捕获输出"，统一到这里。
"""

import sys
from collections.abc import Callable
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def run_cli(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Callable[..., tuple[int, str]]:
    """返回一个 (argv...) -> (退出码, 标准输出) 的调用函数。

    在项目根目录下调用 entry（默认 `crawler.__main__.main`），因此可以使用仓库
    自带的 config.toml 与种子文件，而不必每个测试各写一份配置。
    """
    from crawler.__main__ import main as crawler_main

    def run(*argv: str, entry: Callable[[list[str]], int] | None = None) -> tuple[int, str]:
        monkeypatch.chdir(PROJECT_ROOT)
        code = (entry or crawler_main)(list(argv))
        return code, capsys.readouterr().out

    return run
