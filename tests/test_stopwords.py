"""停用词表：加载行为与文件自身的一致性。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tokenizer.stopwords import StopwordFileError, load_stopwords

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STOPWORDS_FILE = PROJECT_ROOT / "tokenizer" / "stopwords_zh.txt"
SECTION_MARKER = "# ---"
EXPECTED_SECTIONS = (
    "通用停用词（来自基础词表，已清洗）",
    "单字虚词",
    "网页/模板噪声词",
)


def read_sections(path: Path) -> dict[str, list[str]]:
    """按 '# --- 节名 ---' 切分词表，返回 {节名: 词列表}。"""
    sections: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith(SECTION_MARKER) and stripped.endswith("---"):
            sections[stripped.strip("# -")] = []
            continue
        word = line.split("#", 1)[0].strip()
        if word and sections:
            sections[next(reversed(sections))].append(word)
    return sections


def test_load_skips_comments_and_blank_lines(tmp_path: Path) -> None:
    path = tmp_path / "stopwords.txt"
    path.write_text("# 注释行\n的\n\n了  # 行内注释\n", encoding="utf-8")

    assert load_stopwords(path) == frozenset({"的", "了"})


def test_load_reports_missing_file(tmp_path: Path) -> None:
    with pytest.raises(StopwordFileError):
        load_stopwords(tmp_path / "absent.txt")


def test_project_file_has_expected_sections() -> None:
    assert tuple(read_sections(STOPWORDS_FILE)) == EXPECTED_SECTIONS


def test_project_file_contains_function_words() -> None:
    words = load_stopwords(STOPWORDS_FILE)

    # 参考代码缺的正是这一层：单字虚词
    for word in ("的", "了", "是", "在", "和", "就", "都", "而"):
        assert word in words


def test_project_file_contains_web_template_noise() -> None:
    words = load_stopwords(STOPWORDS_FILE)

    for word in ("首页", "下一页", "版权所有", "当前位置"):
        assert word in words


def test_general_section_is_chinese_only() -> None:
    # 基础词表里混着整张英文停用词表（含 OCR 残词），整理时已按"含汉字"筛选。
    sections = read_sections(STOPWORDS_FILE)
    general = sections["通用停用词（来自基础词表，已清洗）"]

    pure_latin = [w for w in general if w.isascii()]
    assert pure_latin == [], f"通用节混入纯 ASCII 条目：{pure_latin[:10]}"

    # 网页噪声节允许保留极少数本身就是拉丁字母的通用模板词
    noise = sections["网页/模板噪声词"]
    assert [w for w in noise if w.isascii()] == ["RSS"]


def test_project_file_has_no_duplicates_or_placeholder_chars() -> None:
    sections = read_sections(STOPWORDS_FILE)
    words = [word for words in sections.values() for word in words]

    assert len(words) == len(set(words)), "词表存在跨节或节内重复"
    assert "\ufffd" not in "".join(words)
    assert len(words) > 1000
