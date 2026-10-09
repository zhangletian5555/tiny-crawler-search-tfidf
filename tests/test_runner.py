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
    """按 URL 返回固定页面的假会话；redirects 模拟服务端重定向。"""

    def __init__(self, pages: dict[str, str], redirects: dict[str, str] | None = None) -> None:
        self.pages = pages
        self.redirects = redirects or {}
        self.calls: list[str] = []

    def get(self, url: str, **kwargs: object) -> FakeResponse:
        self.calls.append(url)
        final = self.redirects.get(url, url)
        if final not in self.pages:
            return FakeResponse(status_code=404, url=final)
        return FakeResponse(text=self.pages[final], url=final)

    def close(self) -> None:
        return None


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        text: str = "",
        content_type: str = "text/html",
        url: str = "",
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.url = url
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
    session = SiteSession(PAGES)
    crawler = Crawler(
        archive=archive,
        frontier=frontier,
        config=config or CONFIG,
        respect_robots=False,
        session=session,  # type: ignore[arg-type]
    )
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
        session=SiteSession(PAGES),  # type: ignore[arg-type]
    )

    crawled = crawler.run()

    assert crawled == 0
    assert list(archive.load_records()) == []
    assert notes and "抓取失败" in notes[0]


def test_non_html_page_is_not_archived(tmp_path: Path) -> None:
    archive = Archive.create(tmp_path / "crawl", "manifest.jsonl")
    frontier = Frontier()
    frontier.enqueue("https://site.example/file.pdf", depth=0, seed_url=HOME)
    notes: list[str] = []

    class PdfSession:
        def get(self, url: str, **kwargs: object) -> FakeResponse:
            return FakeResponse(content_type="application/pdf", url=url)

        def close(self) -> None:
            return None

    crawler = Crawler(
        archive=archive,
        frontier=frontier,
        config=CONFIG,
        respect_robots=False,
        on_note=notes.append,
        session=PdfSession(),  # type: ignore[arg-type]
    )

    assert crawler.run() == 0
    assert list(archive.load_records()) == []
    assert notes and "非网页内容" in notes[0]


def test_document_is_keyed_by_final_url(tmp_path: Path) -> None:
    """http/https、别名、重定向指向同一内容时只应归档一篇。"""
    canonical = "https://site.example/canonical"
    archive = Archive.create(tmp_path / "crawl", "manifest.jsonl")
    frontier = Frontier()
    frontier.enqueue("http://site.example/canonical", 0, "http://site.example/canonical")
    frontier.enqueue(canonical, 0, canonical)
    notes: list[str] = []
    session = SiteSession(
        {canonical: "<html><head><title>规范页</title></head><body>正文</body></html>"},
        redirects={"http://site.example/canonical": canonical},
    )
    crawler = Crawler(
        archive=archive,
        frontier=frontier,
        config=CONFIG,
        respect_robots=False,
        on_note=notes.append,
        session=session,  # type: ignore[arg-type]
    )

    crawled = crawler.run()

    records = list(archive.load_records())
    assert crawled == 1
    assert len(records) == 1
    assert records[0].final_url == canonical
    assert records[0].url == "http://site.example/canonical"  # 记录请求来源
    assert any("重复页面" in note for note in notes)


def test_duplicate_doc_id_is_not_written_to_zip_twice(tmp_path: Path) -> None:
    import zipfile

    canonical = "https://site.example/canonical"
    archive = Archive.create(tmp_path / "crawl", "manifest.jsonl")
    frontier = Frontier()
    frontier.enqueue("https://site.example/a", 0, "https://site.example/a")
    frontier.enqueue("https://site.example/b", 0, "https://site.example/b")
    session = SiteSession(
        {canonical: "<html><head><title>同一内容</title></head><body>正文</body></html>"},
        redirects={
            "https://site.example/a": canonical,
            "https://site.example/b": canonical,
        },
    )
    crawler = Crawler(
        archive=archive,
        frontier=frontier,
        config=CONFIG,
        respect_robots=False,
        session=session,  # type: ignore[arg-type]
    )

    crawler.run()

    with zipfile.ZipFile(archive.pages_path) as zf:
        names = zf.namelist()
    assert len(names) == len(set(names)), f"zip 里出现了重复成员：{names}"
    assert len(list(archive.load_records())) == 1


def test_legacy_manifest_without_final_url_still_loads(tmp_path: Path) -> None:
    """final_url 是后加字段，旧清单必须仍可读。"""
    import json

    archive = Archive.create(tmp_path / "crawl", "manifest.jsonl")
    legacy = {
        "doc_id": "0123456789abcdef",
        "url": "https://site.example/old",
        "fetched_at": "2026-01-01T00:00:00+00:00",
        "status": 200,
        "content_type": "text/html",
        "title": "旧记录",
        "embedded_date": None,
        "body_bytes": 10,
        "archive_member": "0123456789abcdef.html",
        "seed_url": "https://site.example/old",
        "depth": 0,
        "version": 1,
    }
    archive.manifest_path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")

    record = next(archive.load_records())

    assert record.final_url == "https://site.example/old"


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
