"""跨层共用的小工具：带时间戳的产物目录。

只有从抓取到检索都会被用到的通用逻辑才放这里。刻意保持极小——它不是"杂物箱"，
新增内容前先问：这件事是不是某一层自己的职责？
"""

from __future__ import annotations

import time
from pathlib import Path


def timestamped_dir(root: Path, stamp: str | None = None) -> Path:
    """在 root 下新建一个以时间戳命名的目录并返回它。

    抓取运行目录与索引目录都用这个命名约定，因此它们的时序也是字典序：
    "取最新一次"可以直接取名称最大的目录。

    同一秒内重复创建时追加 `-1`、`-2`……，因此不会覆盖已有产物。
    """
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    root.mkdir(parents=True, exist_ok=True)

    candidate = root / stamp
    suffix = 1
    while candidate.exists():
        candidate = root / f"{stamp}-{suffix}"
        suffix += 1
    candidate.mkdir()
    return candidate


def latest_subdirectory(root: Path, description: str) -> Path:
    """取 root 下名称最大（也就是最新）的子目录。

    description 用于组装"没有可用的 X"这句错误信息，让调用方不必各自拼文案。
    """
    if not root.is_dir():
        raise FileNotFoundError(f"{root} 不存在（没有可用的{description}）")

    candidates = sorted(path for path in root.iterdir() if path.is_dir())
    if not candidates:
        raise FileNotFoundError(f"{root} 下没有可用的{description}")
    return candidates[-1]
