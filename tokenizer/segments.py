"""HTML 切片：从一页 HTML 中取出检索需要的几个片段。

只做"取用得到的部分"，不做正文抽取算法的尝试——那是另一个课题。
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

# 中文语境里常见的日期写法，按"从具体到笼统"的顺序尝试
_DATE_PATTERNS = (
    re.compile(r"(?P<year>\d{4})\s*[-/.年]\s*(?P<month>\d{1,2})\s*[-/.月]\s*(?P<day>\d{1,2})\s*[日号]?"),
    re.compile(r"(?P<year>\d{4})\s*[-/.年]\s*(?P<month>\d{1,2})\s*月?"),
    re.compile(r"(?P<month>\d{1,2})\s*[-/.月]\s*(?P<day>\d{1,2})\s*[日号]"),
)


def title_text(soup: BeautifulSoup) -> str:
    """<title> 的文本，没有则返回空串。"""
    tag = soup.find("title")
    return tag.get_text(strip=True) if tag else ""


def body_text(soup: BeautifulSoup) -> str:
    """<body> 的可见文本。

    先剔除 script/style/noscript：它们的文本是代码而不是页面内容。
    注意只取 string 会漏掉部分导航栏，网页模板噪声交由停用词表处理。
    """
    body = soup.find("body")
    if body is None:
        return ""
    for tag in body.find_all(("script", "style", "noscript")):
        tag.decompose()
    return body.get_text(separator=" ", strip=True)


def embedded_date(text: str) -> str | None:
    """从一段文本里提取第一个日期，返回 ISO 形式（YYYY-MM-DD 或 YYYY-MM）。

    没有日期时返回 None。只作元数据记录，不参与打分。
    """
    if not text:
        return None

    for pattern in _DATE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        groups = match.groupdict()
        year = groups.get("year")
        month = groups.get("month")
        day = groups.get("day")
        if year and month and day:
            return f"{year}-{int(month):02d}-{int(day):02d}"
        if year and month:
            return f"{year}-{int(month):02d}"
    return None
