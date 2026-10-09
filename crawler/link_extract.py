"""从 HTML 中提取可用链接，并把 URL 归一化统一到一处。

抓取与索引都需要"同一个页面只有一个标识"，因此归一化规则（去 fragment、
小写主机名、补全路径、编码非 ASCII 字符）只在本模块实现一次。
"""

from __future__ import annotations

from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from url_normalize import url_normalize

# 这些后缀指向大体量或不可索引的资源，提取阶段直接丢弃，省下一次请求
MEDIA_EXTENSIONS = (
    # 视频
    ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm", ".mkv",
    # 音频
    ".mp3", ".wav", ".flac", ".m4a",
    # 图片
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".bmp",
    # 文档与压缩包
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".rar", ".7z", ".gz",
)

# 非网络协议或页面内定位，不是可抓取的页面
SKIP_PREFIXES = (
    "#", "javascript:", "mailto:", "tel:", "data:", "about:", "ftp:", "file:",
)

_ALLOWED_SCHEMES = ("http", "https")


def normalize_url(url: str) -> str:
    """归一化一个绝对 URL。

    依次做四件事：url_normalize 纠正常见写法；去掉 fragment；小写主机名；
    编码路径与查询里的非 ASCII 字符（中文路径若不编码，requests 会直接报错）。
    """
    text = url_normalize(url.strip())
    split = urlsplit(text)

    scheme = split.scheme.lower()
    netloc = split.netloc.lower()
    path = quote(split.path, safe="/%:@!$&'()*+,;=~-._")
    query = quote(split.query, safe="=&%:@!$'()*+,;/?~-._")
    if not path:
        path = "/"

    return urlunsplit((scheme, netloc, path, query, ""))


def url_host(url: str) -> str | None:
    """返回小写 host:port；无法解析时返回 None。

    限速与分桶都按"站点"归组，统一走这里，避免各处自己 urlsplit 出不同粒度。
    """
    return urlsplit(url).netloc.lower() or None


def url_origin(url: str) -> str | None:
    """返回 scheme://host:port；无法解析时返回 None。

    robots.txt 是按 origin 生效的（同一 host 的 http 与 https 各有一份），
    因此 robots 缓存以它为键。
    """
    split = urlsplit(url)
    if split.scheme not in ("http", "https") or not split.netloc:
        return None
    return f"{split.scheme}://{split.netloc.lower()}"


def extract_links(html: str, base_url: str) -> list[str]:
    """返回 html 中所有归一化后的站外可达链接。

    结果去重且已排序，保证同一页面每次提取的顺序一致。
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    links: set[str] = set()
    for anchor in soup.find_all("a"):
        href = (anchor.get("href") or "").strip()
        if not href or href.lower().startswith(SKIP_PREFIXES):
            continue

        candidate = normalize_url(urljoin(base_url, href))
        split = urlsplit(candidate)
        if split.scheme not in _ALLOWED_SCHEMES or not split.netloc:
            continue
        if split.path.lower().endswith(MEDIA_EXTENSIONS):
            continue

        links.add(candidate)

    return sorted(links)
