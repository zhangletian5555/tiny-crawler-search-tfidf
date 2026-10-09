"""中文文本分词：jieba 切分 + 停用词过滤 + 噪声过滤。"""

from __future__ import annotations

from collections.abc import Collection

import jieba

from tokenizer.noise import is_noise


def terms(text: str, stopwords: Collection[str] = frozenset()) -> list[str]:
    """把一段文本切成用于索引/检索的词序列。

    保留重复词（词频是 TF-IDF 的输入），保留顺序（便于调试）。
    stopwords 用 Collection，让调用方决定传 set / frozenset / list。
    """
    if not text:
        return []

    return [
        word
        for word in jieba.lcut(text)
        if not is_noise(word) and word not in stopwords
    ]
