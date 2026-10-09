"""停用词表加载。

文件格式：每行一个词；'#' 起为行内注释；空行忽略。
"""

from __future__ import annotations

from functools import cache
from pathlib import Path


class StopwordFileError(Exception):
    """停用词文件缺失或不可读。"""


@cache
def load_stopwords(path: str | Path) -> frozenset[str]:
    """读取停用词表，按绝对路径缓存，重复调用不再读盘。"""
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise StopwordFileError(f"停用词文件不存在：{resolved}")

    words = set()
    with resolved.open(encoding="utf-8") as handle:
        for line in handle:
            word = line.split("#", 1)[0].strip()
            if word:
                words.add(word)
    return frozenset(words)
