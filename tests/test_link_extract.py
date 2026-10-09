"""链接提取与 URL 归一化。"""

from __future__ import annotations

import pytest

from crawler.link_extract import extract_links, normalize_url

BASE = "https://ai.ruc.edu.cn/"


def page(*hrefs: str) -> str:
    anchors = "".join(f'<a href="{href}"></a>' for href in hrefs)
    return f"<html><body>{anchors}</body></html>"


def test_normalize_strips_fragment_and_lowercases_host() -> None:
    assert normalize_url("HTTPS://AI.RUC.EDU.CN/News#part2") == "https://ai.ruc.edu.cn/News"


def test_normalize_adds_root_path() -> None:
    assert normalize_url("https://ai.ruc.edu.cn") == "https://ai.ruc.edu.cn/"


def test_normalize_encodes_non_ascii_path() -> None:
    assert normalize_url("https://ai.ruc.edu.cn/新闻/简章") == (
        "https://ai.ruc.edu.cn/%E6%96%B0%E9%97%BB/%E7%AE%80%E7%AB%A0"
    )


def test_extract_resolves_relative_links() -> None:
    # '../up' 在根路径下不会退到域名之外，仍是同域链接
    links = extract_links(page("news/", "/about", "../up"), BASE)

    assert links == [
        "https://ai.ruc.edu.cn/about",
        "https://ai.ruc.edu.cn/news/",
        "https://ai.ruc.edu.cn/up",
    ]


def test_extract_keeps_only_absolute_http_links() -> None:
    links = extract_links(
        page("http://other.example/x", "//cdn.example/y", "https://ai.ruc.edu.cn/z"),
        BASE,
    )

    assert links == [
        "http://other.example/x",
        "https://ai.ruc.edu.cn/z",
        "https://cdn.example/y",
    ]
@pytest.mark.parametrize(
    "href",
    [
        "#top",
        "javascript:void(0)",
        "mailto:someone@example.com",
        "tel:010-12345678",
        "data:text/html,hi",
        "ftp://files.example/x",
    ],
)
def test_extract_skips_non_page_hrefs(href: str) -> None:
    assert extract_links(page(href), BASE) == []


@pytest.mark.parametrize(
    "href",
    [
        "video/lecture.mp4",
        "img/banner.PNG",
        "files/report.pdf",
        "files/data.zip",
        "audio/song.mp3",
    ],
)
def test_extract_skips_media_and_documents(href: str) -> None:
    assert extract_links(page(href), BASE) == []


def test_extract_deduplicates_and_sorts() -> None:
    links = extract_links(page("b", "a", "b", "a#frag"), BASE)

    assert links == ["https://ai.ruc.edu.cn/a", "https://ai.ruc.edu.cn/b"]


def test_extract_ignores_anchors_without_href() -> None:
    html = '<html><body><a name="x">文本</a><a href="">空</a><a href="  ">空白</a></body></html>'

    assert extract_links(html, BASE) == []


def test_extract_on_empty_html() -> None:
    assert extract_links("", BASE) == []
