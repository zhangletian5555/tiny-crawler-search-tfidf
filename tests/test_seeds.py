"""种子文件读取。"""

from __future__ import annotations

from pathlib import Path

import pytest

from crawler.seeds import SeedFileError, read_seeds

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_reads_unique_urls_in_order(tmp_path: Path) -> None:
    path = tmp_path / "seeds.txt"
    path.write_text(
        "# 注释行\nhttps://a.example/\n\nhttps://b.example/  # 行内注释\nhttps://a.example/\n",
        encoding="utf-8",
    )

    assert read_seeds(path) == ["https://a.example/", "https://b.example/"]


def test_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(SeedFileError, match="不存在"):
        read_seeds(tmp_path / "absent.txt")


def test_empty_file_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "seeds.txt"
    path.write_text("# 只有注释\n\n", encoding="utf-8")

    with pytest.raises(SeedFileError, match="没有任何 URL"):
        read_seeds(path)


def test_sample_seed_file_is_readable() -> None:
    seeds = read_seeds(PROJECT_ROOT / "resources" / "seeds.example.txt")

    assert len(seeds) == 15
    assert seeds[0] == "http://pd.ruc.edu.cn/"
