"""HTTP 路由：页面与 JSON 接口。

两个入口共用同一个 SearchEngine：
    GET /          首页
    GET /query     HTML 结果页（表单提交目标）
    GET /search    JSON 接口（供脚本或将来前端异步调用）
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify, render_template, request

from search.engine import SearchEngine

bp = Blueprint("search", __name__)

MAX_QUERY_LENGTH = 200


def _engine() -> SearchEngine | None:
    return current_app.config.get("SEARCH_ENGINE")


def _clean(text: str) -> str:
    return text.strip()[:MAX_QUERY_LENGTH]


def _run_query(text: str, k: int) -> list:
    engine = _engine()
    if engine is None or not text:
        return []
    return engine.search(text, k=k)


@bp.get("/")
def index():
    engine = _engine()
    return render_template(
        "index.html",
        error=current_app.config.get("SEARCH_ERROR", ""),
        document_count=engine.document_count if engine else 0,
    )


@bp.get("/query")
def query():
    text = _clean(request.args.get("key", ""))
    top_k = _top_k()
    results = _run_query(text, top_k)

    return render_template(
        "results.html",
        query=text,
        results=results,
        error=current_app.config.get("SEARCH_ERROR", ""),
    )


@bp.get("/search")
def search_api():
    text = _clean(request.args.get("key", ""))
    top_k = _top_k()
    results = _run_query(text, top_k)

    return jsonify(
        {
            "query": text,
            "count": len(results),
            "results": [
                {
                    "doc_id": result.doc_id,
                    "title": result.title,
                    "url": result.url,
                    "score": round(result.score, 6),
                }
                for result in results
            ],
        }
    )


def _top_k() -> int:
    default = int(current_app.config.get("DEFAULT_K", 20))
    raw = request.args.get("k", "")
    if not raw.isdigit():
        return default
    return max(1, min(int(raw), 100))
