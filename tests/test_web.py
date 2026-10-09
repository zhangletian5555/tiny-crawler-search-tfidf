"""Web 层：页面渲染与 JSON 接口。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from corpus import build_index_dir

from config import Settings
from web.app import create_app

CONFIG_TEMPLATE = """
[paths]
data_dir = "{data_dir}"
seeds_file = "{seeds}"
stopwords = "{stopwords}"

[storage]
archive_format = "zip"
manifest_name = "manifest.jsonl"

[crawl]
user_agent = "test/0.1"
default_delay_seconds = 1.0
respect_robots = true
max_pages = 10
max_pages_per_host = 10
request_timeout = 5.0
max_retries = 0
retry_backoff_seconds = 0.0

[index]
title_weight = 2.0

[search]
k = 20

[web]
host = "127.0.0.1"
port = 8000
debug = false
"""

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def client(tmp_path: Path):
    index_dir = build_index_dir(tmp_path)
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        CONFIG_TEMPLATE.format(
            data_dir=(tmp_path).as_posix(),
            seeds=PROJECT_ROOT.joinpath("resources/seeds.example.txt").as_posix(),
            stopwords=PROJECT_ROOT.joinpath("tokenizer/stopwords_zh.txt").as_posix(),
        ),
        encoding="utf-8",
    )
    settings = Settings.from_file(config_path)
    app = create_app(settings, index_dir)
    app.config.update(TESTING=True)
    return app.test_client()


def test_index_page_renders(client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "小型搜索引擎" in body
    assert "3" in body  # 文档数


def test_query_page_lists_hits(client) -> None:
    response = client.get("/query?key=检索")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "命中 2 条" in body
    assert "https://a.example/" in body
    assert "https://b.example/" in body


def test_query_page_without_hits(client) -> None:
    response = client.get("/query?key=量子计算")

    body = response.get_data(as_text=True)
    assert "没有命中任何文档" in body


def test_query_page_with_empty_key(client) -> None:
    response = client.get("/query?key=")

    body = response.get_data(as_text=True)
    assert "请输入关键词" in body


def test_query_page_escapes_html(client) -> None:
    response = client.get("/query?key=<script>alert(1)</script>")

    body = response.get_data(as_text=True)
    assert "<script>alert(1)</script>" not in body


def test_json_api_shape(client) -> None:
    response = client.get("/search?key=检索")

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/json")
    payload = response.get_json()

    assert payload["query"] == "检索"
    assert payload["count"] == len(payload["results"]) == 2
    first = payload["results"][0]
    assert set(first) == {"doc_id", "title", "url", "score"}
    assert isinstance(first["score"], float)
    scores = [item["score"] for item in payload["results"]]
    assert scores == sorted(scores, reverse=True)


def test_json_api_respects_k(client) -> None:
    payload = client.get("/search?key=人工智能&k=1").get_json()

    assert payload["count"] == 1


def test_json_api_clamps_absurd_k(client) -> None:
    payload = client.get("/search?key=人工智能&k=99999").get_json()

    assert payload["count"] <= 3  # 语料只有 3 篇，且 k 被夹到上限内


def test_json_api_ignores_non_numeric_k(client) -> None:
    payload = client.get("/search?key=人工智能&k=abc").get_json()

    assert payload["count"] >= 1


def test_json_api_empty_query(client) -> None:
    payload = client.get("/search?key=").get_json()

    assert payload == {"query": "", "count": 0, "results": []}


def test_overlong_query_is_truncated_not_rejected(client) -> None:
    response = client.get("/search", query_string={"key": "人工智能" * 200})

    assert response.status_code == 200


def test_index_page_works_from_another_cwd(client) -> None:
    """静态资源与模板路径不应依赖当前工作目录。"""
    import os

    previous = os.getcwd()
    os.chdir(PROJECT_ROOT.parent)
    try:
        response = client.get("/static/main.css")
    finally:
        os.chdir(previous)

    assert response.status_code == 200


def test_missing_index_shows_friendly_notice(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        CONFIG_TEMPLATE.format(
            data_dir=tmp_path.as_posix(),
            seeds=PROJECT_ROOT.joinpath("resources/seeds.example.txt").as_posix(),
            stopwords=PROJECT_ROOT.joinpath("tokenizer/stopwords_zh.txt").as_posix(),
        ),
        encoding="utf-8",
    )
    settings = Settings.from_file(config_path)
    app = create_app(settings, tmp_path / "absent")
    app.config.update(TESTING=True)
    client = app.test_client()

    response = client.get("/")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "索引不可用" in body

    # 接口在无索引时返回空结果而不是 500
    payload = client.get("/search?key=检索").get_json()
    assert payload["count"] == 0


def test_api_payload_is_json_serializable(client) -> None:
    payload = client.get("/search?key=人工智能").get_json()

    json.dumps(payload)  # 不应抛异常
