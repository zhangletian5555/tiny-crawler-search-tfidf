"""Web 层：Flask 应用工厂。

索引在应用启动时加载一次并常驻——参考代码也是这个做法（main.py 在模块级构建
全局索引）。不同之处是这里把路径与参数都来自配置，并且加载失败时降级为
"友好提示"而不是启动即崩。
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask

from config import Settings
from search.engine import IndexFormatError, SearchEngine, latest_index, load_index
from tokenizer.stopwords import StopwordFileError, load_stopwords

from .routes import bp


def create_app(settings: Settings, index_dir: Path | None = None) -> Flask:
    """构建应用。index_dir 为 None 时取索引目录下最新一次构建。"""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 64

    engine, error = _load_engine(settings, index_dir)
    app.config["SEARCH_ENGINE"] = engine
    app.config["SEARCH_ERROR"] = error
    app.config["DEFAULT_K"] = settings.search.k

    app.register_blueprint(bp)
    return app


def _load_engine(settings: Settings, index_dir: Path | None) -> tuple[SearchEngine | None, str]:
    """加载索引，返回 (引擎, 错误说明)。任一环节失败都给出可读的原因。"""
    try:
        target = index_dir or latest_index(settings.paths.index_dir)
        stopwords = load_stopwords(settings.paths.stopwords)
        return load_index(target, stopwords), ""
    except (FileNotFoundError, IndexFormatError, StopwordFileError, KeyError) as error:
        return None, str(error)
