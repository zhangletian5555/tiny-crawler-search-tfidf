"""查询侧处理：把用户输入变成可打分的词频。

分词与过滤复用 tokenizer，保证查询侧与索引侧用同一套规则——两侧规则不一致是
"查不到明明存在的文档"的常见原因。
"""

from __future__ import annotations

import math
from collections import Counter

from tokenizer.analyze import terms


def query_term_frequency(text: str, stopwords: frozenset[str]) -> Counter[str]:
    """返回查询词频。全部被停用词/噪声规则过滤掉时返回空 Counter。"""
    return Counter(terms(text, stopwords))


def query_weight(tf: int, idf: float) -> float:
    """查询词的权重。

    与文档侧同口径：w = (1 + ln tf) * idf。对数抑制避免同一词重复输入时权重
    线性放大。文档侧的 w_tf 还要叠加标题词频（见 indexing/builder.py）。
    """
    if tf <= 0 or idf <= 0:
        return 0.0
    return (1.0 + math.log(tf)) * idf
