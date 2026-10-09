"""索引构建与写出：统计口径、产物结构与往返一致性。"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from crawler.store import Archive, RunRecord, document_id
from indexing.builder import build_index
from indexing.writer import INDEX_FORMAT_VERSION, load_meta, write_index

STOPWORDS = frozenset({"的", "了"})

# 三篇小语料，词频与 df 可手算：
#   A: 标题「人工智能」 正文「人工智能 检索 检索」
#   B: 标题「检索」     正文「检索 系统」
#   C: 标题「系统」     正文「系统 人工智能」
CORPUS = {
    "https://a.example/": ("人工智能", "人工智能 检索 检索"),
    "https://b.example/": ("检索", "检索 系统"),
    "https://c.example/": ("系统", "系统 人工智能"),
}


def build_corpus(root: Path, corpus: dict[str, tuple[str, str]] | None = None) -> Archive:
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


@pytest.fixture
def stats(tmp_path: Path):
    archive = build_corpus(tmp_path)
    return build_index(archive.run_dir, STOPWORDS, title_weight=2.0)


def term_of(stats, name: str):  # type: ignore[no-untyped-def]
    return next((term for term in stats.terms if term.term == name), None)


def test_document_count_and_terms(stats) -> None:
    assert stats.document_count == 3
    assert {"人工智能", "检索", "系统"} <= {term.term for term in stats.terms}


def test_document_frequency_counts_documents_not_occurrences(stats) -> None:
    # 「检索」出现在 A(正文两次) 与 B(标题+正文)，df 应为 2 而不是 3
    retrieval = term_of(stats, "检索")

    assert retrieval is not None
    assert retrieval.df == 2
    assert len(retrieval.postings) == 2


def test_postings_carry_title_and_body_frequency(stats) -> None:
    retrieval = term_of(stats, "检索")
    postings = {doc_id: (title_tf, body_tf) for doc_id, title_tf, body_tf in retrieval.postings}

    a = document_id("https://a.example/")
    b = document_id("https://b.example/")
    assert postings[a] == (0, 2)  # 只在正文出现两次
    assert postings[b] == (1, 1)  # 标题一次、正文一次


def test_idf_matches_formula(stats) -> None:
    retrieval = term_of(stats, "检索")

    assert retrieval is not None
    assert retrieval.idf == pytest.approx(math.log(3 / 2))


def test_document_lengths_are_token_counts(stats) -> None:
    by_url = {document.url: document for document in stats.documents}

    assert by_url["https://a.example/"].title_len == 1
    # A 的正文：人工智能 + 检索 + 检索（jieba 切出的空格由噪声规则丢弃）
    assert by_url["https://a.example/"].body_len == 3
    assert stats.avg_body_len == pytest.approx((3 + 2 + 2) / 3)


def test_stopwords_are_not_indexed(tmp_path: Path) -> None:
    archive = build_corpus(
        tmp_path,
        {"https://a.example/": ("标题", "的 的 检索")},
    )

    result = build_index(archive.run_dir, STOPWORDS, title_weight=2.0)

    assert term_of(result, "的") is None
    assert term_of(result, "检索") is not None


def test_duplicate_doc_ids_are_indexed_once(tmp_path: Path) -> None:
    """清单里同一主键出现多次时只索引第一条。

    真实场景：续爬写入新运行目录，而新运行并不知道旧运行写过哪些主键，于是同一
    URL 会在归档里留下两条记录。若不在这里去重，检索结果会出现同分同标题的重复
    条目（实测出现过）。
    """
    archive = build_corpus(tmp_path)
    first_line = archive.manifest_path.read_text(encoding="utf-8").splitlines()[0]
    with archive.manifest_path.open("a", encoding="utf-8") as handle:
        handle.write(first_line + "\n")

    result = build_index(archive.run_dir, STOPWORDS, title_weight=2.0)

    assert result.document_count == 3  # 语料本有 3 篇，重复行不应变成 4
    assert len({document.doc_id for document in result.documents}) == 3


def test_identical_content_from_two_urls_is_indexed_once(tmp_path: Path) -> None:
    """同一内容的不同入口（http/https）只应索引一篇。

    真实语料里 27% 的记录是这种成对重复：站点在 http 与 https 上提供相同页面
    且不做重定向，两个 URL 得到不同主键，于是同一结果会在检索里出现两次。
    """
    archive = build_corpus(tmp_path)
    url = "https://a.example/"
    record = next(r for r in archive.load_records() if r.url == url)
    twin = replace(record, doc_id="twin000000000000", url="http://a.example/", final_url="http://a.example/")
    archive.append(twin)

    result = build_index(archive.run_dir, STOPWORDS, title_weight=2.0)

    assert result.document_count == 3
    assert result.duplicates_skipped == 1


def test_content_dedupe_can_be_disabled(tmp_path: Path) -> None:
    archive = build_corpus(tmp_path)
    record = next(r for r in archive.load_records() if r.url == "https://a.example/")
    twin = replace(record, doc_id="twin000000000000", url="http://a.example/", final_url="http://a.example/")
    archive.append(twin)

    result = build_index(archive.run_dir, STOPWORDS, title_weight=2.0, dedupe_content=False)

    assert result.document_count == 4  # 保留全部记录
    assert result.duplicates_skipped == 0


def test_empty_corpus_produces_empty_stats(tmp_path: Path) -> None:
    archive = Archive.create(tmp_path, "manifest.jsonl")
    archive.close()

    result = build_index(archive.run_dir, STOPWORDS, title_weight=2.0)

    assert result.document_count == 0
    assert result.terms == ()
    assert result.avg_body_len == 0.0


def test_doc_norms_are_positive_and_finite(stats) -> None:
    assert len(stats.doc_norms) == 3
    assert all(value > 0 for value in stats.doc_norms.values())
    assert all(math.isfinite(value) for value in stats.doc_norms.values())


def test_title_weight_scales_document_norms(tmp_path: Path) -> None:
    archive = build_corpus(tmp_path)

    low = build_index(archive.run_dir, STOPWORDS, title_weight=1.0)
    high = build_index(archive.run_dir, STOPWORDS, title_weight=5.0)

    a = document_id("https://a.example/")
    # 标题里含「人工智能」，提高标题权重应让该文档的范数变大
    assert high.doc_norms[a] > low.doc_norms[a]


def test_write_index_produces_expected_artifacts(tmp_path: Path, stats) -> None:
    index_dir = write_index(tmp_path / "index", stats, source_run="20260115-103000", title_weight=2.0)

    names = {path.name for path in index_dir.iterdir()}
    assert names == {"meta.json", "docs.jsonl", "terms.jsonl", "term_offsets.json", "stats.json"}


def test_term_offsets_point_at_the_right_rows(tmp_path: Path, stats) -> None:
    """偏移量必须能定位到自己那一行——写入与读取的字节口径要一致。

    这是真实踩过的坑：Windows 上 text 模式把 \\n 写成 \\r\\n，偏移每行差一字节，
    seek 后读到的是半行 JSON。
    """
    index_dir = write_index(tmp_path / "index", stats, source_run="run-1", title_weight=2.0)
    offsets = json.loads((index_dir / "term_offsets.json").read_text("utf-8"))

    with (index_dir / "terms.jsonl").open("rb") as handle:
        for term, offset in offsets.items():
            handle.seek(offset)
            row = json.loads(handle.readline().decode("utf-8"))
            assert row["term"] == term


def test_written_artifacts_are_readable_json(tmp_path: Path, stats) -> None:
    index_dir = write_index(tmp_path / "index", stats, source_run="run-1", title_weight=2.0)

    meta = load_meta(index_dir)
    assert meta["format_version"] == INDEX_FORMAT_VERSION
    assert meta["source_run"] == "run-1"
    assert meta["title_weight"] == 2.0
    assert meta["document_count"] == 3
    assert meta["term_count"] == len(stats.terms)

    docs = [json.loads(line) for line in (index_dir / "docs.jsonl").read_text("utf-8").splitlines()]
    terms = [json.loads(line) for line in (index_dir / "terms.jsonl").read_text("utf-8").splitlines()]
    payload = json.loads((index_dir / "stats.json").read_text("utf-8"))

    assert len(docs) == 3
    assert len(terms) == len(stats.terms)
    assert payload["document_count"] == 3
    assert payload["idf"]["检索"] == pytest.approx(round(math.log(3 / 2), 6))
    assert set(payload["doc_norms"]) == set(stats.doc_norms)


def test_terms_file_is_sorted_by_term(tmp_path: Path, stats) -> None:
    index_dir = write_index(tmp_path / "index", stats, source_run="run-1", title_weight=2.0)

    terms = [json.loads(line)["term"] for line in (index_dir / "terms.jsonl").read_text("utf-8").splitlines()]
    assert terms == sorted(terms)


def test_rebuild_is_deterministic(tmp_path: Path) -> None:
    archive = build_corpus(tmp_path)

    first = build_index(archive.run_dir, STOPWORDS, title_weight=2.0)
    second = build_index(archive.run_dir, STOPWORDS, title_weight=2.0)

    assert first.documents == second.documents
    assert first.terms == second.terms
    assert first.doc_norms == second.doc_norms


def test_two_indexes_in_the_same_second_do_not_collide(tmp_path: Path, stats) -> None:
    first = write_index(tmp_path / "index", stats, source_run="run-1", title_weight=2.0)
    second = write_index(tmp_path / "index", stats, source_run="run-1", title_weight=2.0)

    assert first != second
