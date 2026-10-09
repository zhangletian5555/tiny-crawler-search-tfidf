"""一次检索的结果条目。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchResult:
    """命中的一篇文档。score 已做过文档长度归一化。"""

    doc_id: str
    url: str
    title: str
    score: float
