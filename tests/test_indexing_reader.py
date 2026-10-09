"""读取归档：只认清单，按 manifest 顺序产出文档。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crawler.store import Archive, RunRecord, document_id
from indexing.reader import read_documents

HTML = "<html><head><title>标题</title></head><body>正文内容</body></html>"


def make_archive(root: Path) -> Archive:
    archive = Archive.create(root, "manifest.jsonl")
    for index, url in enumerate(("https://a.example/1", "https://a.example/2")):
        doc_id = document_id(url)
        member = archive.write_page(doc_id, HTML)
        archive.append(
            RunRecord(
                doc_id=doc_id,
                url=url,
                final_url=url,
                fetched_at="2026-01-15T10:30:02+00:00",
                status=200,
                content_type="text/html",
                title=f"标题{index}",
                embedded_date="2026-01-15",
                body_bytes=len(HTML.encode("utf-8")),
                archive_member=member,
                seed_url=url,
                depth=0,
            )
        )
    archive.close()
    return archive


def test_reads_documents_in_manifest_order(tmp_path: Path) -> None:
    archive = make_archive(tmp_path)

    documents = list(read_documents(archive.run_dir))

    assert [document.doc_id for document in documents] == [
        document_id("https://a.example/1"),
        document_id("https://a.example/2"),
    ]
    assert documents[0].title == "标题0"
    assert documents[0].url == "https://a.example/1"
    assert "正文内容" in documents[0].html


def test_member_without_manifest_record_is_not_indexed(tmp_path: Path) -> None:
    """zip 里可能残留没有清单记录的页面，索引只承认清单。"""
    archive = make_archive(tmp_path)
    archive.write_page("orphan", "<html><body>孤儿页</body></html>")
    archive.close()

    documents = list(read_documents(archive.run_dir))

    assert len(documents) == 2
    assert all("孤儿页" not in document.html for document in documents)


def test_manifest_record_without_member_is_skipped(tmp_path: Path) -> None:
    """清单指向不存在的成员时跳过，而不是抛异常中断整轮索引。"""
    archive = make_archive(tmp_path)
    with archive.manifest_path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "doc_id": "missing0000000000",
                    "url": "https://a.example/gone",
                    "fetched_at": "2026-01-15T10:30:02+00:00",
                    "status": 200,
                    "content_type": "text/html",
                    "title": "缺失",
                    "embedded_date": None,
                    "body_bytes": 0,
                    "archive_member": "missing0000000000.html",
                    "seed_url": "https://a.example/gone",
                    "depth": 0,
                    "version": 1,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    archive.close()

    documents = list(read_documents(archive.run_dir))

    assert len(documents) == 2


def test_empty_archive_yields_nothing(tmp_path: Path) -> None:
    archive = Archive.create(tmp_path, "manifest.jsonl")
    archive.close()

    assert list(read_documents(archive.run_dir)) == []


def test_truncated_zip_yields_nothing_instead_of_raising(tmp_path: Path) -> None:
    """被强杀的运行会让 zip 缺少中央目录，整体不可读——应返回空而不是抛异常。"""
    archive = make_archive(tmp_path)
    archive.close()
    # 截掉尾部（中央目录所在处），模拟进程被强杀
    raw = archive.pages_path.read_bytes()
    archive.pages_path.write_bytes(raw[: len(raw) // 2])

    assert list(read_documents(archive.run_dir)) == []


def test_missing_run_dir_is_reported(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        list(read_documents(tmp_path / "absent"))
