"""归档：文档主键、写入与回读。"""

from __future__ import annotations

import time
import zipfile
from pathlib import Path

from crawler.store import Archive, RunRecord, document_id

HTML = "<html><head><title>测试页</title></head><body>正文</body></html>"


def read_member(archive: Archive, member: str) -> str:
    """读取 zip 成员。

    归档由此处直接读 zip，而不是在 Archive 上再开一个只被测试使用的读取方法——
    真正会读归档的是 P3 的 indexing/reader.py，到时候由它承担这个职责。
    """
    with zipfile.ZipFile(archive.pages_path) as zf:
        return zf.read(member).decode("utf-8")


def make_record(url: str, member: str) -> RunRecord:
    """构造一条清单记录。member 由 archive.write_page 返回，测试不自行拼接。"""
    return RunRecord(
        doc_id=document_id(url),
        url=url,
        fetched_at="2026-01-15T10:30:02+00:00",
        status=200,
        content_type="text/html; charset=utf-8",
        title="测试页",
        embedded_date="2026-01-15",
        body_bytes=len(HTML.encode("utf-8")),
        archive_member=member,
        seed_url=url,
        depth=0,
    )


def test_document_id_is_stable_across_equivalent_urls() -> None:
    # 归一化后才哈希，因此这些写法必须得到同一个主键
    assert document_id("https://A.Example/p#frag") == document_id("https://a.example/p")
    assert document_id("https://a.example") == document_id("https://a.example/")


def test_document_id_differs_for_different_paths() -> None:
    assert document_id("https://a.example/p") != document_id("https://a.example/q")


def test_document_id_is_64_bit_hex() -> None:
    value = document_id("https://a.example/")

    assert len(value) == 16
    int(value, 16)  # 不是十六进制会抛 ValueError


def test_write_puts_page_in_zip(tmp_path: Path) -> None:
    archive = Archive.create(tmp_path, "manifest.jsonl")
    doc_id = document_id("https://a.example/")

    member = archive.write_page(doc_id, HTML)
    archive.close()  # 写入期间 zip 句柄保持打开，读取前需先关闭

    assert member == f"{doc_id}.html"
    assert read_member(archive, member) == HTML


def test_manifest_round_trip(tmp_path: Path) -> None:
    archive = Archive.create(tmp_path, "manifest.jsonl")
    url = "https://a.example/"
    member = archive.write_page(document_id(url), HTML)
    archive.append(make_record(url, member))
    archive.close()

    reopened = Archive.open(archive.run_dir, "manifest.jsonl")
    records = list(reopened.load_records())

    assert len(records) == 1
    assert records[0].archive_member == member
    assert read_member(reopened, records[0].archive_member) == HTML


def test_corrupt_manifest_line_is_skipped(tmp_path: Path) -> None:
    archive = Archive.create(tmp_path, "manifest.jsonl")
    url = "https://a.example/"
    member = archive.write_page(document_id(url), HTML)
    record = make_record(url, member)
    archive.append(record)
    with archive.manifest_path.open("a", encoding="utf-8") as handle:
        handle.write('{"doc_id": "unterminated\n')  # 模拟中断留下的半行
    archive.close()

    assert list(Archive.open(archive.run_dir, "manifest.jsonl").load_records()) == [record]


def test_run_dir_is_named_by_timestamp(tmp_path: Path) -> None:
    archive = Archive.create(tmp_path, "manifest.jsonl")

    assert archive.run_id.startswith(time.strftime("%Y%m%d"))
    assert archive.run_dir.is_dir()


def test_two_runs_in_the_same_second_do_not_collide(tmp_path: Path) -> None:
    first = Archive.create(tmp_path, "manifest.jsonl")
    second = Archive.create(tmp_path, "manifest.jsonl")

    assert first.run_dir != second.run_dir
    assert first.run_id != second.run_id


def test_open_reports_missing_run_dir(tmp_path: Path) -> None:
    try:
        Archive.open(tmp_path / "absent", "manifest.jsonl")
    except FileNotFoundError as error:
        assert "不存在" in str(error)
    else:  # pragma: no cover - 只有实现出错才会走到
        raise AssertionError("应当抛出 FileNotFoundError")
