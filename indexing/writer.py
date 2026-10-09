"""写出索引产物：data/index/<index_id>/ 下的几个文件。

    meta.json           格式版本、来源抓取运行、构建参数、语料统计
    docs.jsonl          每行一篇文档的元数据
    terms.jsonl         每行一个词的 df 与倒排表（按词排序）
    term_offsets.json   词 -> 该词在 terms.jsonl 里的字节偏移
    stats.json          idf、文档范数、平均长度

选择 JSONL 而不是 pickle：可读、可 diff、可只看头部排查。规模真的成为瓶颈时，
只需替换本模块与 reader 的对应实现，读写契约不变。

term_offsets.json 的作用：查询时按词直接 seek 到对应行，不必扫描整张倒排表。
只靠 idf（stats.json）判断词是否存在、再去 terms.jsonl 里找，会让每次查询都读一遍
全部词条——8711 篇文档时 terms.jsonl 已有 65 MB，实测每次查询要 1.7 秒。
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from pathlib import Path

from .builder import IndexStats

INDEX_FORMAT_VERSION = 2


def write_index(
    index_root: Path,
    stats: IndexStats,
    source_run: str,
    title_weight: float,
) -> Path:
    """把索引写成一个新的 <index_id> 目录，返回该目录。"""
    index_dir = _create_dir(index_root)

    _write_jsonl(
        index_dir / "docs.jsonl",
        (
            {
                "doc_id": document.doc_id,
                "url": document.url,
                "title": document.title,
                "title_len": document.title_len,
                "body_len": document.body_len,
            }
            for document in stats.documents
        ),
    )
    offsets = _write_terms(index_dir / "terms.jsonl", stats)

    stats_payload = {
        "document_count": stats.document_count,
        "avg_title_len": stats.avg_title_len,
        "avg_body_len": stats.avg_body_len,
        "idf": {term.term: round(term.idf, 6) for term in stats.terms},
        "doc_norms": {key: round(value, 6) for key, value in stats.doc_norms.items()},
    }
    (index_dir / "stats.json").write_text(
        json.dumps(stats_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (index_dir / "term_offsets.json").write_text(
        json.dumps(offsets, ensure_ascii=False), encoding="utf-8"
    )

    meta = {
        "format_version": INDEX_FORMAT_VERSION,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source_run": source_run,
        "title_weight": title_weight,
        "document_count": stats.document_count,
        "term_count": len(stats.terms),
    }
    (index_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return index_dir


def _write_terms(path: Path, stats: IndexStats) -> dict[str, int]:
    """写出倒排表，同时记录每个词条在该文件里的字节偏移。

    用二进制模式写入，且不依赖 text 模式的换行转换：Windows 上 text 模式会把
    `\\n` 写成 `\\r\\n`，偏移量就会每行差一字节，查询时 seek 到错误位置。
    偏移按实际写入的 UTF-8 字节数累加（中文一字三字节，不能用字符数）。
    """
    offsets: dict[str, int] = {}
    position = 0
    with path.open("wb") as handle:
        for term in stats.terms:
            line = (
                json.dumps(
                    {
                        "term": term.term,
                        "df": term.df,
                        "postings": [list(posting) for posting in term.postings],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            ).encode("utf-8")
            offsets[term.term] = position
            handle.write(line)
            position += len(line)
    return offsets


def load_meta(index_dir: Path) -> dict:
    """读取 meta.json，用于检查格式版本与来源。"""
    return json.loads((index_dir / "meta.json").read_text(encoding="utf-8"))


def _create_dir(index_root: Path) -> Path:
    """新建索引目录。同一秒内重复构建时追加序号。"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    index_root.mkdir(parents=True, exist_ok=True)

    index_dir = index_root / stamp
    suffix = 1
    while index_dir.exists():
        index_dir = index_root / f"{stamp}-{suffix}"
        suffix += 1
    index_dir.mkdir()
    return index_dir


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
