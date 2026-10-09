"""测试共用的小语料与基础配置。

- `build_archive` / `build_index_dir`：三篇文档、词频与 df 可手算，断言可以直接
  对着手算值写。被 indexing / search / web 三组测试共用。
- `CRAWL_CONFIG`：测试用的抓取配置基底（不触网、不等待）。各测试用
  `dataclasses.replace` 只改自己关心的字段，避免每处各写一份完整配置。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from config import CrawlConfig
from crawler.store import Archive, RunRecord, document_id
from indexing.builder import build_index
from indexing.writer import write_index

STOPWORDS = frozenset({"的", "了"})

CRAWL_CONFIG = CrawlConfig(
    user_agent="test-agent/0.1",
    default_delay_seconds=0.0,
    respect_robots=False,
    max_pages=0,
    max_pages_per_host=100,
    request_timeout=5.0,
    max_retries=0,
    retry_backoff_seconds=0.0,
)

#   A: 标题「人工智能」 正文「人工智能 检索 检索」
#   B: 标题「检索」     正文「检索 系统」
#   C: 标题「系统」     正文「系统 人工智能」
CORPUS = {
    "https://a.example/": ("人工智能", "人工智能 检索 检索"),
    "https://b.example/": ("检索", "检索 系统"),
    "https://c.example/": ("系统", "系统 人工智能"),
}


def crawl_config(**changes) -> CrawlConfig:  # type: ignore[no-untyped-def]
    """在测试基底上改几个字段，省得每处都写完整配置。"""
    return replace(CRAWL_CONFIG, **changes)


def build_archive(root: Path, corpus: dict[str, tuple[str, str]] | None = None) -> Archive:
    """把语料写成一个抓取归档。"""
    archive = Archive.create(root, "manifest.jsonl")
    for url, (title, body) in (corpus or CORPUS).items():
        html = f"<html><head><title>{title}</title></head><body>{body}</body></html>"
        doc_id = document_id(url)
        member = archive.write_page(doc_id, html)
        archive.append(
            RunRecord(
                doc_id=doc_id,
                url=url,
                final_url=url,
                fetched_at="2026-01-15T10:30:02+00:00",
                status=200,
                content_type="text/html",
                title=title,
                embedded_date=None,
                body_bytes=len(html.encode("utf-8")),
                archive_member=member,
                seed_url=url,
                depth=0,
            )
        )
    archive.close()
    return archive


def build_index_dir(root: Path, title_weight: float = 2.0) -> Path:
    """构建归档 + 索引，返回索引目录。"""
    archive = build_archive(root / "crawl")
    stats = build_index(archive.run_dir, STOPWORDS, title_weight=title_weight)
    return write_index(
        root / "index", stats, source_run=archive.run_id, title_weight=title_weight
    )
