"""一句话判断一个 token 是否应当丢弃。

只保留高置信度、跨语料通用的噪声规则；更激进的规则（例如丢弃单个 ASCII
字母）等有评测数据后再加，避免过早引入拟合性逻辑。
"""

from __future__ import annotations

import re

# 至少含一个拉丁字母或汉字才算"词"。这样 '', '，', '++', '---', '&&', '&#',
# '._' 这类纯符号组合会被挡住，而 'TF-IDF'、'2026年'、'A' 会保留。
_HAS_WORD_CHARACTER = re.compile(r"[a-zA-Z\u4e00-\u9fff]")

# 单个 token 的长度上限：超过它的多半是 PDF 转换或模板拼接产生的乱码串
MAX_TOKEN_LENGTH = 24


def is_noise(token: str) -> bool:
    """token 为空、不含任何词字符、或过长时返回 True。"""
    if not token or token.isspace():
        return True
    if len(token) > MAX_TOKEN_LENGTH:
        return True
    return _HAS_WORD_CHARACTER.search(token) is None
