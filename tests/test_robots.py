"""robots.txt 抓取、缓存与 Crawl-delay 解析。"""

from __future__ import annotations

from crawler.robots import RobotsCache

ROBOTS = """User-agent: *
Disallow: /private/
Crawl-delay: 5
"""


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "") -> None:
        self.status_code = status_code
        self.text = text
        self.headers: dict[str, str] = {}

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


class FakeSession:
    def __init__(self, outcomes: dict[str, object]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append(url)
        outcome = self.outcomes.get(url, FakeResponse(status_code=404))
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, FakeResponse)
        return outcome


def cache_for(outcomes: dict[str, object]) -> tuple[RobotsCache, FakeSession]:
    session = FakeSession(outcomes)
    return RobotsCache(session, "tiny-crawler-search-tfidf", timeout=5.0), session  # type: ignore[arg-type]


def test_robots_is_fetched_once_per_host() -> None:
    cache, session = cache_for({"https://a.example/robots.txt": FakeResponse(text=ROBOTS)})

    cache.rules_for("https://a.example/one")
    cache.rules_for("https://a.example/two")

    assert session.calls == ["https://a.example/robots.txt"]


def test_disallow_rule_blocks_path() -> None:
    cache, _ = cache_for({"https://a.example/robots.txt": FakeResponse(text=ROBOTS)})
    rules = cache.rules_for("https://a.example/")

    assert rules.allows("https://a.example/public/page", "tiny-crawler-search-tfidf") is True
    assert rules.allows("https://a.example/private/page", "tiny-crawler-search-tfidf") is False


def test_crawl_delay_is_parsed() -> None:
    cache, _ = cache_for({"https://a.example/robots.txt": FakeResponse(text=ROBOTS)})

    assert cache.crawl_delay_for("https://a.example/") == 5.0


def test_missing_robots_means_no_restriction() -> None:
    cache, _ = cache_for({})  # 默认 404

    rules = cache.rules_for("https://a.example/")

    assert rules.verdict == "missing"
    assert rules.allows("https://a.example/anything", "tiny-crawler-search-tfidf") is True
    assert rules.crawl_delay is None
    assert "404" in rules.note


def test_forbidden_robots_blocks_everything() -> None:
    cache, _ = cache_for({"https://a.example/robots.txt": FakeResponse(status_code=403)})

    rules = cache.rules_for("https://a.example/")

    assert rules.verdict == "unavailable"
    assert rules.allows("https://a.example/", "tiny-crawler-search-tfidf") is False
    assert "403" in rules.note


def test_group_for_our_agent_overrides_wildcard() -> None:
    """同时存在 * 与具名分组时，Python 的 RobotFileParser 会合并两条规则。"""
    text = (
        "User-agent: *\n"
        "Disallow: /wildcard-only/\n"
        "\n"
        "User-agent: tiny-crawler-search-tfidf\n"
        "Disallow: /named-only/\n"
    )
    cache, _ = cache_for({"https://a.example/robots.txt": FakeResponse(text=text)})
    rules = cache.rules_for("https://a.example/")

    assert rules.verdict == "loaded"
    assert rules.allows("https://a.example/named-only/x", "tiny-crawler-search-tfidf") is False
    assert rules.allows("https://a.example/other/x", "tiny-crawler-search-tfidf") is True


def test_unreachable_robots_blocks_everything() -> None:
    cache, _ = cache_for({"https://a.example/robots.txt": ConnectionError("down")})

    rules = cache.rules_for("https://a.example/")

    assert rules.allows("https://a.example/", "tiny-crawler-search-tfidf") is False
    assert "获取失败" in rules.note


def test_url_without_host_is_not_allowed() -> None:
    cache, _ = cache_for({})

    rules = cache.rules_for("/relative/path")

    assert rules.verdict == "unavailable"
    assert rules.allows("/relative/path", "tiny-crawler-search-tfidf") is False
