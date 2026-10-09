"""检索门面：加载一个索引目录，并在其上执行查询。

索引产物是自足的——本模块只读 data/index/<index_id>/，不接触抓取归档。
倒排表按词排序，因此查询时只在需要的行上解析 JSON，不必把全部倒排表读进内存。
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import jieba

from indexing.builder import DocumentInfo
from indexing.writer import INDEX_FORMAT_VERSION, load_meta
from runtime import latest_subdirectory

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
        term_offsets: dict[str, int],
        terms_path: Path,
        stopwords: frozenset[str],
        title_weight: float,
    ) -> None:
        self.index_dir = index_dir
        self.documents = documents
        self._idf = idf
        self.doc_norms = doc_norms
        self.stopwords = stopwords
        self.title_weight = title_weight
        self._term_offsets = term_offsets
        self._terms_path = terms_path

    @property
    def document_count(self) -> int:
        return len(self.documents)

    @property
    def idf(self) -> dict[str, float]:
        """词 -> idf。只读用途（排查、统计），打分内部走 `_idf`。"""
        return dict(self._idf)

    def _known_terms(self, term_frequency: Counter[str]) -> set[str]:
        """查询词里"索引中存在"的那些——只有它们才有倒排表可读。"""
        return {term for term in term_frequency if term in self.idf}

    def search(self, text: str, k: int = 20) -> list[SearchResult]:
        """返回得分最高的 k 篇文档；没有命中时返回空列表。"""
        term_frequency = query_term_frequency(text, self.stopwords)
        if not term_frequency:
            return []

        wanted = self._known_terms(term_frequency)
        if not wanted:
            return []

        scores: dict[str, float] = defaultdict(float)
        for term, postings in self._postings_for(wanted):
            idf_value = self._idf[term]
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

    def _postings_for(self, wanted: set[str]):  # type: ignore[no-untyped-def]
        """按 term_offsets.json 里的偏移直接 seek 读取涉及的行。

        只读查询涉及的几个词，不扫描整张倒排表——这是查询耗时的关键：
        terms.jsonl 在 8711 篇文档时已有 65 MB，全表扫描约 1.7 秒/次。

        以二进制模式 seek + readline：偏移量是文件里的真实字节位置，
        与写入端（binary 模式）严格对应。
        """
        with self._terms_path.open("rb") as handle:
            for term in wanted:
                offset = self._term_offsets.get(term)
                if offset is None:
                    continue
                handle.seek(offset)
                entry = json.loads(handle.readline().decode("utf-8"))
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
    return latest_subdirectory(index_root, "索引")


def load_index(index_dir: Path, stopwords: frozenset[str]) -> SearchEngine:
    """加载索引目录。格式版本不符时明确报错，而不是给出错误结果。"""
    meta = load_meta(index_dir)
    if meta.get("format_version") != INDEX_FORMAT_VERSION:
        raise IndexFormatError(
            f"索引格式版本为 {meta.get('format_version')}，"
            f"当前代码期望 {INDEX_FORMAT_VERSION}：{index_dir}"
        )

    payload = json.loads((index_dir / "stats.json").read_text(encoding="utf-8"))
    offsets = json.loads((index_dir / "term_offsets.json").read_text(encoding="utf-8"))
    documents = _load_documents(index_dir)

    # 预热分词器：jieba 的词典是首次调用时才构建的，约 0.8 秒。若留到第一次查询，
    # 用户会看到首屏明显变慢；放在加载阶段，这次开销就并进了启动时间。
    jieba.initialize()

    return SearchEngine(
        index_dir=index_dir,
        documents=documents,
        idf=payload["idf"],
        doc_norms=payload["doc_norms"],
        term_offsets=offsets,
        terms_path=index_dir / "terms.jsonl",
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
