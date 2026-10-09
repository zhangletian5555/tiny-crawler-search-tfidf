"""TF-IDF 检索：打分口径、排序、以及查询侧与索引侧的一致性。"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from corpus import STOPWORDS, build_index_dir

from search.engine import IndexFormatError, SearchEngine, load_index
from search.query import query_term_frequency, query_weight


def build_engine(root: Path, title_weight: float = 2.0) -> SearchEngine:
    return load_index(build_index_dir(root, title_weight), STOPWORDS)


@pytest.fixture
def engine(tmp_path: Path) -> SearchEngine:
    return build_engine(tmp_path)


def url_of(engine: SearchEngine, doc_id: str) -> str:
    return engine.documents[doc_id].url


def test_query_terms_reuse_index_side_rules() -> None:
    assert query_term_frequency("人工智能 的 检索", STOPWORDS) == {"人工智能": 1, "检索": 1}
    assert query_term_frequency("的 了", STOPWORDS) == {}


def test_query_weight_uses_log_smoothing() -> None:
    assert query_weight(1, 2.0) == pytest.approx(2.0)
    assert query_weight(2, 2.0) == pytest.approx((1 + math.log(2)) * 2.0)
    assert query_weight(0, 2.0) == 0.0
    assert query_weight(1, 0.0) == 0.0


def test_single_term_query_finds_matching_documents(engine: SearchEngine) -> None:
    results = engine.search("检索", k=10)

    urls = {url_of(engine, result.doc_id) for result in results}
    assert urls == {"https://a.example/", "https://b.example/"}
    # C 既没有标题也没有正文含「检索」
    assert "https://c.example/" not in urls


def test_results_are_sorted_by_score_descending(engine: SearchEngine) -> None:
    results = engine.search("检索", k=10)

    scores = [result.score for result in results]
    assert scores == sorted(scores, reverse=True)
    assert all(score > 0 for score in scores)


def test_title_weight_reverses_the_ranking(tmp_path: Path) -> None:
    """提高标题权重应让「检索」出现在标题里的 B 反超正文出现两次的 A。

    两者都经过文档长度归一化，临界点由实算确定：weight=0.2 时 A 在前，
    weight=0.3 时 B 反超（0 表示完全不看标题词频）。
    """

    def top_url(weight: float, name: str) -> str:
        engine = build_engine(tmp_path / name, title_weight=weight)
        return url_of(engine, engine.search("检索", k=1)[0].doc_id)

    assert top_url(0.0, "body-only") == "https://a.example/"
    assert top_url(0.2, "low") == "https://a.example/"
    assert top_url(0.3, "mid") == "https://b.example/"
    assert top_url(10.0, "high") == "https://b.example/"


def test_title_weight_changes_scores_monotonically(tmp_path: Path) -> None:
    """A 的匹配只在正文，B 的匹配在标题：提高标题权重应拉大两者差距。"""

    def margin(weight: float, name: str) -> float:
        engine = build_engine(tmp_path / name, title_weight=weight)
        scores = {url_of(engine, r.doc_id): r.score for r in engine.search("检索", k=10)}
        return scores["https://b.example/"] - scores["https://a.example/"]

    assert margin(0.0, "w0") < margin(2.0, "w2") < margin(10.0, "w10")


def test_multi_term_query_prefers_documents_containing_both(engine: SearchEngine) -> None:
    results = engine.search("人工智能 系统", k=10)

    # C 同时含「系统」（标题）与「人工智能」（正文），应排第一
    assert url_of(engine, results[0].doc_id) == "https://c.example/"


def test_unknown_term_returns_nothing(engine: SearchEngine) -> None:
    assert engine.search("量子计算", k=10) == []


def test_stopword_only_query_returns_nothing(engine: SearchEngine) -> None:
    assert engine.search("的 了", k=10) == []


def test_empty_query_returns_nothing(engine: SearchEngine) -> None:
    assert engine.search("", k=10) == []


def test_k_limits_results(engine: SearchEngine) -> None:
    assert len(engine.search("人工智能", k=1)) == 1
    assert len(engine.search("人工智能", k=10)) <= 3


def test_results_carry_title_and_url(engine: SearchEngine) -> None:
    result = engine.search("系统", k=1)[0]

    assert result.title in {"系统", "检索"}
    assert result.url.startswith("https://")


def test_scores_are_stable_across_repeated_calls(engine: SearchEngine) -> None:
    first = [(r.doc_id, r.score) for r in engine.search("人工智能 系统", k=10)]
    second = [(r.doc_id, r.score) for r in engine.search("人工智能 系统", k=10)]

    assert first == second


def test_repeated_query_term_is_dampened_not_linear(engine: SearchEngine) -> None:
    once = engine.search("检索", k=10)
    twice = engine.search("检索 检索", k=10)

    # 对数抑制：重复一次不等于分数翻倍
    assert twice[0].score < once[0].score * 2


def test_title_terms_are_counted_from_postings(engine: SearchEngine) -> None:
    """「检索」在 B 的标题里，因此 B 的权重应高于只在正文出现的情形。"""
    results = {url_of(engine, r.doc_id): r.score for r in engine.search("检索", k=10)}

    # A 正文两次、B 标题一次正文一次；title_weight=2 时 B 的加权词频更高
    assert results["https://b.example/"] > results["https://a.example/"]


def test_index_format_version_is_checked(tmp_path: Path) -> None:
    import json

    engine = build_engine(tmp_path)
    meta_path = engine.index_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["format_version"] = 999
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    with pytest.raises(IndexFormatError):
        load_index(engine.index_dir, STOPWORDS)


def test_missing_index_files_are_reported(tmp_path: Path) -> None:
    engine = build_engine(tmp_path)
    (engine.index_dir / "docs.jsonl").unlink()

    with pytest.raises(FileNotFoundError):
        load_index(engine.index_dir, STOPWORDS)


def test_engine_does_not_need_the_archive(tmp_path: Path) -> None:
    """索引产物自足：删掉抓取归档后仍能检索。"""
    import shutil

    engine = build_engine(tmp_path)
    shutil.rmtree(tmp_path / "crawl")

    reloaded = load_index(engine.index_dir, STOPWORDS)

    assert reloaded.search("检索", k=5)
