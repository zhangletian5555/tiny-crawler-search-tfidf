"""检索门面：加载一个索引目录，并在其上执行查询。

索引产物是自足的——本模块只读 data/index/<index_id>/，不接触抓取归档。
倒排表按词排序，因此查询时只在需要的行上解析 JSON，不必把全部倒排表读进内存。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from indexing.builder import DocumentInfo
from indexing.writer import INDEX_FORMAT_VERSION, load_meta

from .query import query_term_frequency, query_weight
from .result import SearchResult

# 倒排表条目：(doc_id, title_tf, body_tf)
Posting = tuple[str, int, int]


class IndexFormatError(Exception):
    """索引产物的格式与当前代码不兼容。"""


class SearchEngine:
    """TF-IDF 检索。打分公式见 docs/architecture.md §4。"""

    def __init__(
        self,
        index_dir: Path,
        documents: dict[str, DocumentInfo],
        idf: dict[str, float],
        doc_norms: dict[str, float],
        postings_path: Path,
        stopwords: frozenset[str],
        title_weight: float,
    ) -> None:
        self.index_dir = index_dir
        self.documents = documents
        self.idf = idf
        self.doc_norms = doc_norms
        self.stopwords = stopwords
        self.title_weight = title_weight
        self._postings_path = postings_path

    @property
    def document_count(self) -> int:
        return len(self.documents)

    def search(self, text: str, k: int = 20) -> list[SearchResult]:
        """返回得分最高的 k 篇文档；没有命中时返回空列表。"""
        term_frequency = query_term_frequency(text, self.stopwords)
        if not term_frequency:
            return []

        wanted = {term: self.idf[term] for term in term_frequency if term in self.idf}
        if not wanted:
            return []

        scores: dict[str, float] = defaultdict(float)
        for term, postings in self._postings_for(wanted):
            idf_value = wanted[term]
            for doc_id, title_tf, body_tf in postings:
                norm = self.doc_norms.get(doc_id)
                if norm is None:
                    continue
                weight = (title_tf * self.title_weight + body_tf) * idf_value
                if weight == 0.0:
                    continue
                scores[doc_id] += weight / norm * query_weight(term_frequency[term], idf_value)

        # 分数相同的按 doc_id 排序，保证同一索引上结果稳定可复现
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return [self._as_result(doc_id, score) for doc_id, score in ranked[:k]]

    # ------------------------------------------------------------------
    # 内部步骤
    # ------------------------------------------------------------------

    def _postings_for(self, wanted: dict[str, float]):  # type: ignore[no-untyped-def]
        """流式扫描 terms.jsonl，只产出查询涉及的词条。"""
        remaining = set(wanted)
        with self._postings_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not remaining:
                    break
                entry = json.loads(line)
                term = entry["term"]
                if term not in remaining:
                    continue
                remaining.discard(term)
                yield term, (tuple(posting) for posting in entry["postings"])

    def _as_result(self, doc_id: str, score: float) -> SearchResult:
        document = self.documents.get(doc_id)
        if document is None:
            return SearchResult(doc_id=doc_id, url="", title="", score=score)
        return SearchResult(
            doc_id=doc_id, url=document.url, title=document.title, score=score
        )


def latest_index(index_root: Path) -> Path:
    """取索引根目录下最新一次构建（构建目录按时间戳命名）。"""
    if not index_root.is_dir():
        raise FileNotFoundError(f"索引根目录不存在：{index_root}")
    builds = sorted(path for path in index_root.iterdir() if path.is_dir())
    if not builds:
        raise FileNotFoundError(f"还没有构建过索引：{index_root}")
    return builds[-1]


def load_index(index_dir: Path, stopwords: frozenset[str]) -> SearchEngine:
    """加载索引目录。格式版本不符时明确报错，而不是给出错误结果。"""
    meta = load_meta(index_dir)
    if meta.get("format_version") != INDEX_FORMAT_VERSION:
        raise IndexFormatError(
            f"索引格式版本为 {meta.get('format_version')}，"
            f"当前代码期望 {INDEX_FORMAT_VERSION}：{index_dir}"
        )

    payload = json.loads((index_dir / "stats.json").read_text(encoding="utf-8"))
    documents = _load_documents(index_dir)

    return SearchEngine(
        index_dir=index_dir,
        documents=documents,
        idf=payload["idf"],
        doc_norms=payload["doc_norms"],
        postings_path=index_dir / "terms.jsonl",
        stopwords=stopwords,
        title_weight=float(meta["title_weight"]),
    )


def _load_documents(index_dir: Path) -> dict[str, DocumentInfo]:
    documents: dict[str, DocumentInfo] = {}
    with (index_dir / "docs.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            documents[row["doc_id"]] = DocumentInfo(
                doc_id=row["doc_id"],
                url=row["url"],
                title=row["title"],
                title_len=row["title_len"],
                body_len=row["body_len"],
            )
    return documents
