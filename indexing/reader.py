"""读取抓取归档：data/crawl/<run_id>/ 下的 manifest.jsonl 与 pages.zip。

这是归档的唯一消费者入口。索引器只通过本模块接触归档，因此它不知道文件名约定、
不需要解压到临时目录、也不会绕过 manifest 去找页面。
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from crawler.store import Archive


@dataclass(frozen=True)
class IndexedDocument:
    """一篇待索引文档：清单元数据 + 原始 HTML。"""

    doc_id: str
    url: str
    title: str
    html: str
    embedded_date: str | None
    depth: int


def read_documents(
    crawl_dir: Path, manifest_name: str = "manifest.jsonl"
) -> Iterator[IndexedDocument]:
    """按 manifest 顺序逐篇产出文档。

    清单是文档集合的权威来源：zip 里可能存在没有清单记录的成员（例如中途
    中断），它们不会被索引——索引只承认清单。

    一次都没抓到页面时 pages.zip 不存在（zip 句柄是在写入第一页时才建立的），
    这属于正常的空归档，返回空序列而不是报错。
    """
    archive = Archive.open(crawl_dir, manifest_name)
    if not archive.pages_path.is_file():
        return

    # 每次迭代开一次 zip：manifest 有几千行时，没必要为整轮读取长期占用句柄
    with zipfile.ZipFile(archive.pages_path) as pages:
        members = set(pages.namelist())
        for record in archive.load_records():
            if record.archive_member not in members:
                continue
            html = pages.read(record.archive_member).decode("utf-8", errors="replace")
            yield IndexedDocument(
                doc_id=record.doc_id,
                url=record.final_url,
                title=record.title,
                html=html,
                embedded_date=record.embedded_date,
                depth=record.depth,
            )
