"""HTTP 抓取：内容类型判断、重试退避、失败结果。"""

from __future__ import annotations

from dataclasses import replace

import pytest
import requests
from corpus import crawl_config

from crawler.fetcher import create_session, fetch_page

# 抓取器测试关心的是重试与退避，因此在共用基底上开启重试并给出退避值
CONFIG = crawl_config(max_retries=2, retry_backoff_seconds=2.0)

HTML_BODY = b"<html><head><title>\xe6\xb5\x8b\xe8\xaf\x95</title></head><body></body></html>"


class FakeResponse:
    """requests.Response 的最小替身。"""

    def __init__(
        self,
        status_code: int = 200,
        content: bytes = HTML_BODY,
        content_type: str = "text/html; charset=utf-8",
        apparent_encoding: str | None = "utf-8",
        url: str = "",
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": content_type} if content_type else {}
        self.encoding = None
        self.apparent_encoding = apparent_encoding
        self.url = url

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding or self.apparent_encoding or "utf-8")

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


class FakeSession:
    """按顺序返回预设响应或抛出预设异常；记录每次请求的 URL。

    预设用尽后再被调用会直接报错——测试里多出一次请求应当暴露，而不是静默成功。
    """

    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[str] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append(url)
        if not self.outcomes:
            raise AssertionError(f"预设响应已用尽，却仍在请求：{url}")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, FakeResponse)
        return outcome


class SleepSpy:
    """记录睡眠时长，不真的等待。"""

    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def test_create_session_sets_user_agent() -> None:
    session = create_session("test-agent/0.1")

    assert session.headers["User-Agent"] == "test-agent/0.1"
    session.close()


def test_fetches_html_page() -> None:
    session = FakeSession([FakeResponse()])

    result = fetch_page("https://example.com/", CONFIG, session)  # type: ignore[arg-type]

    assert result.ok is True
    assert result.status == 200
    assert "<title>" in (result.html or "")
    assert result.encoding == "utf-8"


def test_decodes_utf8_page_without_charset_in_header() -> None:
    """站点只回 `Content-Type: text/html` 时，必须按页面内部声明解码。

    requests 在缺少 charset 时会退回 ISO-8859-1，直接取 response.text 会把
    中文页面存成乱码——这里就是那个回归用例。
    """
    body = (
        '<html><head><meta charset="UTF-8"><title>人工智能学院</title></head>'
        "<body>招生简章</body></html>"
    ).encode()
    session = FakeSession([FakeResponse(content=body, content_type="text/html")])

    result = fetch_page("https://example.com/", CONFIG, session)  # type: ignore[arg-type]

    assert result.encoding == "utf-8"
    assert "人工智能学院" in (result.html or "")
    assert "招生简章" in (result.html or "")


def test_header_charset_wins_over_meta() -> None:
    body = '<html><head><meta charset="gbk"></head><body>正文</body></html>'.encode("gbk")
    session = FakeSession(
        [FakeResponse(content=body, content_type="text/html; charset=GBK")]
    )

    result = fetch_page("https://example.com/", CONFIG, session)  # type: ignore[arg-type]

    assert result.encoding == "gbk"
    assert "正文" in (result.html or "")


def test_unknown_charset_falls_back_to_utf8() -> None:
    body = "<html><head><title>标题</title></head></html>".encode()
    session = FakeSession(
        [FakeResponse(content=body, content_type="text/html; charset=not-a-codec")]
    )

    result = fetch_page("https://example.com/", CONFIG, session)  # type: ignore[arg-type]

    assert result.encoding == "utf-8"
    assert "标题" in (result.html or "")


def test_undecodable_bytes_do_not_crash() -> None:
    body = b"<html><body>\xff\xfe\x00bad bytes</body></html>"
    session = FakeSession([FakeResponse(content=body, content_type="text/html")])

    result = fetch_page("https://example.com/", CONFIG, session)  # type: ignore[arg-type]

    assert result.ok is True
    assert "bad bytes" in (result.html or "")


def test_skips_non_html_content() -> None:
    session = FakeSession([FakeResponse(content_type="application/pdf")])

    result = fetch_page("https://example.com/a.pdf", CONFIG, session)  # type: ignore[arg-type]

    assert result.ok is False
    assert "非网页内容" in result.error
    assert len(session.calls) == 1  # 确定性的跳过不重试


def test_retries_on_server_error_then_succeeds() -> None:
    session = FakeSession([FakeResponse(status_code=503), FakeResponse()])
    sleeper = SleepSpy()

    result = fetch_page("https://example.com/", CONFIG, session, sleep=sleeper)  # type: ignore[arg-type]

    assert result.ok is True
    assert len(session.calls) == 2
    assert sleeper.waits == [2.0]  # 第 1 次重试等待 1 * backoff


def test_retries_are_bounded_and_backoff_grows() -> None:
    session = FakeSession([FakeResponse(status_code=500)] * 3)
    sleeper = SleepSpy()

    result = fetch_page("https://example.com/", CONFIG, session, sleep=sleeper)  # type: ignore[arg-type]

    assert result.ok is False
    assert result.status == 500
    assert len(session.calls) == 3  # 首次 + max_retries 次重试
    assert sleeper.waits == [2.0, 4.0]  # 最后一次失败后不再等待


def test_retries_network_errors() -> None:
    session = FakeSession(
        [requests.ConnectionError("boom"), requests.Timeout("slow"), FakeResponse()]
    )
    sleeper = SleepSpy()

    result = fetch_page("https://example.com/", CONFIG, session, sleep=sleeper)  # type: ignore[arg-type]

    assert result.ok is True
    assert len(session.calls) == 3


def test_does_not_retry_client_errors() -> None:
    session = FakeSession([FakeResponse(status_code=404)])
    sleeper = SleepSpy()

    result = fetch_page("https://example.com/missing", CONFIG, session, sleep=sleeper)  # type: ignore[arg-type]

    assert result.ok is False
    assert result.status == 404
    assert len(session.calls) == 1
    assert sleeper.waits == []


def test_reports_network_failure() -> None:
    session = FakeSession([requests.ConnectionError("boom")] * 3)

    result = fetch_page(
        "https://example.com/", CONFIG, session, sleep=SleepSpy()  # type: ignore[arg-type]
    )

    assert result.ok is False
    assert result.status is None
    assert "ConnectionError" in result.error


def test_no_retry_when_retries_disabled() -> None:
    session = FakeSession([FakeResponse(status_code=503)])
    config = replace(CONFIG, max_retries=0)

    result = fetch_page("https://example.com/", config, session)  # type: ignore[arg-type]

    assert result.ok is False
    assert len(session.calls) == 1


def test_throttle_is_called_for_each_attempt_with_normalized_url() -> None:
    session = FakeSession([FakeResponse(status_code=503), FakeResponse()])
    seen: list[str] = []

    fetch_page(
        "HTTPS://Example.COM/Path#frag",
        CONFIG,
        session,  # type: ignore[arg-type]
        throttle=seen.append,
        sleep=SleepSpy(),
    )

    assert seen == ["https://example.com/Path", "https://example.com/Path"]


@pytest.mark.parametrize("status", [429, 500, 502, 503])
def test_retryable_statuses(status: int) -> None:
    session = FakeSession([FakeResponse(status_code=status), FakeResponse()])

    result = fetch_page(
        "https://example.com/", CONFIG, session, sleep=SleepSpy()  # type: ignore[arg-type]
    )

    assert result.ok is True
    assert len(session.calls) == 2
