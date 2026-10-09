"""抓取主循环：把 frontier / fetcher / archive 串起来跑一个微型站点。"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from config import CrawlConfig
from crawler.fetcher import FetchResult
from crawler.frontier import Frontier
from crawler.runner import Crawler
from crawler.store import Archive

HOME = "https://site.example/"
ABOUT = "https://site.example/about"
DEEP = "https://site.example/about/team"
OTHER = "https://other.example/"

PAGES = {
    HOME: '<html><head><title>首页</title></head><body>2026-01-15'
    '<a href="/about">关于</a><a href="https://other.example/">外站</a></body></html>',
    ABOUT: '<html><head><title>关于</title></head><body><a href="/about/team">团队</a></body></html>',
    DEEP: "<html><head><title>团队</title></head><body>成员</body></html>",
    OTHER: '<html><head><title>外站</title></head><body><a href="/">回首页</a></body></html>',
}

CONFIG = CrawlConfig(
    user_agent="test-agent/0.1",
    default_delay_seconds=0.0,
    respect_robots=False,
    max_pages=0,
    max_pages_per_host=100,
    request_timeout=5.0,
    max_retries=0,
    retry_backoff_seconds=0.0,
)


class SiteSession:
    """按 URL 返回固定页面的假会话。"""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append(url)
        if url not in self.pages:
            return FakeResponse(status_code=404)
        return FakeResponse(text=self.pages[url])

    def close(self) -> None:
        return None


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "", content_type: str = "text/html") -> None:
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None


def build(tmp_path: Path, config: CrawlConfig | None = None) -> tuple[Crawler, Archive, Frontier, SiteSession]:
    archive = Archive.create(tmp_path / "crawl", "manifest.jsonl")
    frontier = Frontier()
    frontier.enqueue(HOME, depth=0, seed_url=HOME)
    crawler = Crawler(
        archive=archive,
        frontier=frontier,
        config=config or CONFIG,
        respect_robots=False,
    )
    session = SiteSession(PAGES)
    crawler.session = session  # type: ignore[assignment]
    return crawler, archive, frontier, session


def test_crawls_whole_small_site(tmp_path: Path) -> None:
    crawler, archive, frontier, _ = build(tmp_path)

    crawled = crawler.run()

    assert crawled == 4
    names = [record.title for record in archive.load_records()]
    assert set(names) == {"首页", "关于", "团队", "外站"}


def test_archive_holds_every_page(tmp_path: Path) -> None:
    crawler, archive, _, _ = build(tmp_path)

    crawler.run()

    records = list(archive.load_records())
    for record in records:
        assert record.archive_member == f"{record.doc_id}.html"
        assert "<html>" in archive.read_page(record.archive_member)


def test_record_metadata_is_filled(tmp_path: Path) -> None:
    crawler, archive, _, _ = build(tmp_path)

    crawler.run()

    home = next(r for r in archive.load_records() if r.url == HOME)
    assert home.status == 200
    assert home.title == "首页"
    assert home.embedded_date == "2026-01-15"
    assert home.depth == 0
    assert home.body_bytes > 0
    assert home.seed_url == HOME


def test_depth_grows_with_distance(tmp_path: Path) -> None:
    crawler, archive, _, _ = build(tmp_path)

    crawler.run()

    depths = {r.url: r.depth for r in archive.load_records()}
    assert depths[HOME] == 0
    assert depths[ABOUT] == 1
    assert depths[DEEP] == 2


def test_max_pages_stops_the_run(tmp_path: Path) -> None:
    crawler, archive, frontier, _ = build(tmp_path, replace(CONFIG, max_pages=2))

    crawled = crawler.run()

    assert crawled == 2
    assert frontier.pending_count > 0  # 还有没抓的，只是被上限挡住了


def test_should_stop_ends_the_run_early(tmp_path: Path) -> None:
    crawler, _, _, session = build(tmp_path)
    calls = {"n": 0}

    def stop() -> bool:
        calls["n"] += 1
        return calls["n"] > 2

    crawled = crawler.run(should_stop=stop)

    assert crawled == 2
    assert len(session.calls) == 2


def test_unreachable_page_is_not_archived(tmp_path: Path) -> None:
    archive = Archive.create(tmp_path / "crawl", "manifest.jsonl")
    frontier = Frontier()
    frontier.enqueue("https://site.example/absent", depth=0, seed_url=HOME)
    notes: list[str] = []
    crawler = Crawler(
        archive=archive,
        frontier=frontier,
        config=CONFIG,
        respect_robots=False,
        on_note=notes.append,
    )
    crawler.session = SiteSession(PAGES)  # type: ignore[assignment]

    crawled = crawler.run()

    assert crawled == 0
    assert list(archive.load_records()) == []
    assert notes and "抓取失败" in notes[0]


def test_non_html_page_is_not_archived(tmp_path: Path) -> None:
    archive = Archive.create(tmp_path / "crawl", "manifest.jsonl")
    frontier = Frontier()
    frontier.enqueue("https://site.example/file.pdf", depth=0, seed_url=HOME)
    notes: list[str] = []
    crawler = Crawler(
        archive=archive,
        frontier=frontier,
        config=CONFIG,
        respect_robots=False,
        on_note=notes.append,
    )

    class PdfSession:
        def get(self, url: str, **kwargs: object) -> FakeResponse:
            return FakeResponse(content_type="application/pdf")

        def close(self) -> None:
            return None

    crawler.session = PdfSession()  # type: ignore[assignment]

    assert crawler.run() == 0
    assert list(archive.load_records()) == []
    assert notes and "非网页内容" in notes[0]


def test_links_are_only_crawled_once(tmp_path: Path) -> None:
    # 首页与外站互相链接，去重应保证每页只抓一次
    crawler, _, _, session = build(tmp_path)

    crawler.run()

    assert len(session.calls) == len(set(session.calls))


def test_resume_marks_archived_urls_as_seen(tmp_path: Path) -> None:
    crawler, archive, _, _ = build(tmp_path)
    crawler.run()

    # 续爬：把归档里的 URL 标记为已见，重新入队的链接不应再抓
    frontier = Frontier()
    reopened = Archive.open(archive.run_dir, "manifest.jsonl")
    for record in reopened.load_records():
        frontier.mark_seen(record.url)

    assert frontier.enqueue(HOME, 0, HOME) is False
    assert frontier.enqueue(ABOUT, 1, HOME) is False


def test_fetch_result_is_reported_per_page(tmp_path: Path) -> None:
    seen: list[str] = []
    crawler, _, _, _ = build(tmp_path)
    crawler.on_page = lambda record: seen.append(record.url)

    crawler.run()

    assert set(seen) == {HOME, ABOUT, DEEP, OTHER}


def test_fetch_result_error_is_carried_by_notes(tmp_path: Path) -> None:
    """fetch_page 的错误信息应出现在 note 里，便于排查。"""
    crawler, _, _, _ = build(tmp_path)
    notes: list[str] = []
    crawler.on_note = notes.append
    crawler.session = SiteSession({})  # 所有页面 404
    crawler.frontier.enqueue("https://site.example/only", 0, HOME)

    crawler.run()

    assert any("抓取失败" in note for note in notes)


def test_fetch_result_type_matches_fetcher() -> None:
    # 保护性检查：runner 依赖 fetcher.FetchResult 的字段
    result = FetchResult(url="https://a.example/", status=200, html="<html></html>")

    assert result.ok is True
