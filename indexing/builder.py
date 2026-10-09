"""从归档构建索引统计。

产出三样东西：
- 词典与倒排表（每个词的文档频率，以及每篇文档里的标题/正文词频）
- 文档长度与平均长度
- 文档元数据（标题、URL）

打分公式见 docs/architecture.md §4；本模块只统计，不做打分。
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from tokenizer.analyze import terms
from tokenizer.segments import parts

from .reader import read_documents


@dataclass(frozen=True)
class DocumentInfo:
    """一篇文档在索引里的元数据。"""

    doc_id: str
    url: str
    title: str
    title_len: int
    body_len: int


@dataclass(frozen=True)
class TermStats:
    """一个词的统计：文档频率、idf 与倒排表。"""

    term: str
    df: int
    idf: float
    postings: tuple[tuple[str, int, int], ...]  # (doc_id, title_tf, body_tf)


@dataclass(frozen=True)
class IndexStats:
    """一次索引构建的完整结果。"""

    documents: tuple[DocumentInfo, ...]
    terms: tuple[TermStats, ...]
    doc_norms: dict[str, float]
    avg_title_len: float
    avg_body_len: float

    @property
    def document_count(self) -> int:
        return len(self.documents)


def build_index(
    crawl_dir: Path,
    stopwords: frozenset[str],
    title_weight: float,
    manifest_name: str = "manifest.jsonl",
) -> IndexStats:
    """扫描归档并统计索引。

    当前实现把倒排表放在内存里累积（本项目的语料规模下足够）。若将来要处理
    十万级文档，需要改成按词外排归并，届时替换本函数即可，读写的对外契约不变。
    """
    documents: list[DocumentInfo] = []
    # term -> doc_id -> 词频；用两个 dict 分别存标题与正文
    title_counts: dict[str, dict[str, int]] = defaultdict(dict)
    body_counts: dict[str, dict[str, int]] = defaultdict(dict)
    df: Counter[str] = Counter()

    for document in read_documents(crawl_dir, manifest_name):
        title, body = parts(document.html)
        title_tf = Counter(terms(title, stopwords))
        body_tf = Counter(terms(body, stopwords))

        for term in title_tf.keys() | body_tf.keys():
            if title_tf.get(term):
                title_counts[term][document.doc_id] = title_tf[term]
            if body_tf.get(term):
                body_counts[term][document.doc_id] = body_tf[term]
            df[term] += 1

        documents.append(
            DocumentInfo(
                doc_id=document.doc_id,
                url=document.url,
                title=document.title or title,
                title_len=sum(title_tf.values()),
                body_len=sum(body_tf.values()),
            )
        )

    document_count = len(documents)
    idf = {
        term: math.log(document_count / count) if count else 0.0
        for term, count in df.items()
    }

    doc_norms = _document_norms(documents, title_counts, body_counts, idf, title_weight)
    term_stats = tuple(
        TermStats(
            term=term,
            df=df[term],
            idf=idf[term],
            postings=tuple(
                (doc_id, title_counts[term].get(doc_id, 0), body_counts[term].get(doc_id, 0))
                for doc_id in sorted(title_counts[term].keys() | body_counts[term].keys())
            ),
        )
        for term in sorted(df)
    )

    return IndexStats(
        documents=tuple(documents),
        terms=term_stats,
        doc_norms=doc_norms,
        avg_title_len=_average(document.title_len for document in documents),
        avg_body_len=_average(document.body_len for document in documents),
    )


def _document_norms(
    documents: list[DocumentInfo],
    title_counts: dict[str, dict[str, int]],
    body_counts: dict[str, dict[str, int]],
    idf: dict[str, float],
    title_weight: float,
) -> dict[str, float]:
    """每篇文档的 L2 范数，供余弦相似度做长度归一化。

    权重按 w = w_tf * idf 计算，其中 w_tf = title_tf * title_weight + body_tf。
    同一篇文档可能同时出现在 title_counts 与 body_counts 里，因此两轮各自累加平方。
    """
    squares: dict[str, float] = defaultdict(float)
    for counts, factor in ((title_counts, title_weight), (body_counts, 1.0)):
        for term, per_document in counts.items():
            idf_value = idf.get(term, 0.0)
            if idf_value == 0.0:
                continue
            for doc_id, tf in per_document.items():
                value = tf * factor * idf_value
                squares[doc_id] += value * value

    return {
        document.doc_id: math.sqrt(squares.get(document.doc_id, 0.0)) or 1.0
        for document in documents
    }


def _average(values: Iterable[int]) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0
