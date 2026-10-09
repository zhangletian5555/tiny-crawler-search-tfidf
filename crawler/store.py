"""抓取产物落盘：data/crawl/<run_id>/ 下的 pages.zip 与 manifest.jsonl。

manifest.jsonl 是文档主键的唯一来源；zip 成员名即 doc_id，因此可以不解压整包
就定位单页。doc_id 由归一化后的 URL 哈希得到，与文件名、抓取顺序都无关——
参考代码用 'html_doc' + 序号当主键，导致下游三处靠文件名反推 doc_id 或 URL。
"""

from __future__ import annotations

import hashlib
import json
import time
import zipfile
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

from .link_extract import normalize_url

DOCUMENT_ID_LENGTH = 16  # sha1 前 16 位十六进制 = 64 bit


def document_id(url: str) -> str:
    """由归一化 URL 计算文档主键。"""
    normalized = normalize_url(url)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:DOCUMENT_ID_LENGTH]


@dataclass(frozen=True)
class RunRecord:
    """manifest.jsonl 的一行，字段定义见 docs/architecture.md。

    doc_id 由 final_url 计算：同一内容经不同入口（http/https、重定向、别名）
    到达时会归并为一篇文档。final_url 是后加的字段，旧清单里没有，因此给予空
    默认值——加载时回退为 url。
    """

    doc_id: str
    url: str
    fetched_at: str
    status: int | None
    content_type: str
    title: str
    embedded_date: str | None
    body_bytes: int
    archive_member: str
    seed_url: str
    depth: int
    version: int = 1
    final_url: str = ""

    def __post_init__(self) -> None:
        if not self.final_url:
            object.__setattr__(self, "final_url", self.url)


class Archive:
    """一次抓取运行的归档读写。"""

    def __init__(self, run_dir: Path, manifest_name: str) -> None:
        self.run_dir = run_dir
        self.manifest_name = manifest_name
        self.pages_path = run_dir / "pages.zip"
        self._zip: zipfile.ZipFile | None = None

    @classmethod
    def create(cls, crawl_root: Path, manifest_name: str) -> Archive:
        """新建一次运行。run_id 用本地时间；同一秒内重复创建时追加序号。"""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        crawl_root.mkdir(parents=True, exist_ok=True)

        run_dir = crawl_root / stamp
        suffix = 1
        while run_dir.exists():
            run_dir = crawl_root / f"{stamp}-{suffix}"
            suffix += 1
        run_dir.mkdir()
        return cls(run_dir, manifest_name)

    @classmethod
    def open(cls, run_dir: Path, manifest_name: str) -> Archive:
        """打开一个已存在的运行，用于续爬。"""
        if not run_dir.is_dir():
            raise FileNotFoundError(f"运行目录不存在：{run_dir}")
        return cls(run_dir, manifest_name)

    @property
    def run_id(self) -> str:
        return self.run_dir.name

    @property
    def manifest_path(self) -> Path:
        return self.run_dir / self.manifest_name

    def load_records(self) -> Iterator[RunRecord]:
        """逐行读取清单，跳过写坏的行（中断可能留下半行）。"""
        if not self.manifest_path.is_file():
            return
        with self.manifest_path.open(encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    yield RunRecord(**json.loads(text))
                except (json.JSONDecodeError, TypeError):
                    continue

    def write_page(self, doc_id: str, html: str) -> str:
        """把 HTML 写入 zip，返回成员名。

        zip 句柄在整个运行期间保持打开：一次运行几万页时，每页开关一次
        zip 会反复重写中央目录，代价很高。
        """
        member = f"{doc_id}.html"
        archive = self._ensure_zip()
        archive.writestr(member, html)
        return member

    def append(self, record: RunRecord) -> None:
        """追加一条清单记录。先写 zip 再写清单，避免清单指向不存在的页面。"""
        with self.manifest_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def close(self) -> None:
        """关闭 zip 句柄；重复调用无副作用。"""
        if self._zip is not None:
            self._zip.close()
            self._zip = None

    def _ensure_zip(self) -> zipfile.ZipFile:
        if self._zip is None:
            self._zip = zipfile.ZipFile(self.pages_path, "a", zipfile.ZIP_DEFLATED)
        return self._zip
