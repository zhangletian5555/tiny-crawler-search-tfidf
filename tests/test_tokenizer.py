"""tokenizer 包：噪声过滤、分词、HTML 切片。

停用词表自身的检查在 test_stopwords.py。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from tokenizer.analyze import terms
from tokenizer.noise import is_noise
from tokenizer.segments import body_text, embedded_date, title_text

SAMPLE_PAGE = Path(__file__).resolve().parent / "fixtures" / "sample_page.html"


@pytest.mark.parametrize(
    "token",
    ["", "   ", "2026", "，", "——", "++", "---", "&&", "&#", "._", "x" * 25],
)
def test_noise_is_rejected(token: str) -> None:
    assert is_noise(token) is True


@pytest.mark.parametrize("token", ["人工智能", "2026年", "TF-IDF", "A"])
def test_meaningful_token_is_kept(token: str) -> None:
    assert is_noise(token) is False


def test_terms_filters_stopwords_and_noise() -> None:
    result = terms("人工智能 研究，2026 的 进展", stopwords={"的"})

    assert "的" not in result
    assert "2026" not in result
    assert "，" not in result
    assert "人工智能" in result
    assert "研究" in result


def test_terms_keeps_repeats_for_frequency() -> None:
    result = terms("检索 检索 检索")

    assert result.count("检索") == 3


def test_terms_on_empty_text() -> None:
    assert terms("") == []


def test_html_slices() -> None:
    soup = BeautifulSoup(SAMPLE_PAGE.read_text(encoding="utf-8"), "lxml")

    assert title_text(soup) == "人工智能学院 2026 年招生简章"
    body = body_text(soup)
    assert "师资队伍" in body
    assert "console.log" not in body  # script 内容已剔除


def test_embedded_date_prefers_most_specific_form() -> None:
    assert embedded_date("发布时间：2026-01-15") == "2026-01-15"
    assert embedded_date("2026年1月15日") == "2026-01-15"
    assert embedded_date("2026年1月") == "2026-01"
    assert embedded_date("1月15日") is None  # 缺年份，不作为文档日期
    assert embedded_date("没有日期的正文") is None
