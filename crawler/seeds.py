"""种子文件读取。

文件格式与 config.toml 里其他清单类文件保持一致：
每行一个 URL，'#' 起为行内注释，空行忽略。
"""

from __future__ import annotations

from pathlib import Path


class SeedFileError(Exception):
    """种子文件缺失或内容为空。"""


def read_seeds(path: str | Path) -> list[str]:
    """按出现顺序返回种子 URL，保持去重。"""
    resolved = Path(path).expanduser()
    if not resolved.is_file():
        raise SeedFileError(f"种子文件不存在：{resolved}")

    seeds: list[str] = []
    seen: set[str] = set()
    with resolved.open(encoding="utf-8") as handle:
        for line in handle:
            url = line.split("#", 1)[0].strip()
            if url and url not in seen:
                seen.add(url)
                seeds.append(url)

    if not seeds:
        raise SeedFileError(f"种子文件里没有任何 URL：{resolved}")
    return seeds
