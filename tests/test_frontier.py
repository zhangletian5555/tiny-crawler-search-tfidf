"""待抓队列：分桶、去重与单站上限。"""

from __future__ import annotations

from crawler.frontier import Frontier

A = "https://a.example/"
B = "https://b.example/"


def test_enqueue_and_take_in_order() -> None:
    frontier = Frontier()
    frontier.enqueue(A + "1", depth=0, seed_url=A)
    frontier.enqueue(A + "2", depth=1, seed_url=A)

    first = frontier.next_url()
    second = frontier.next_url()

    assert first is not None and first.url == A + "1"
    assert second is not None and second.url == A + "2"
    assert frontier.next_url() is None


def test_duplicate_is_rejected() -> None:
    frontier = Frontier()

    assert frontier.enqueue(A + "1", 0, A) is True
    assert frontier.enqueue(A + "1", 0, A) is False
    assert frontier.pending_count == 1


def test_seen_url_is_never_enqueued_again() -> None:
    frontier = Frontier()
    frontier.mark_seen(A + "1")

    assert frontier.enqueue(A + "1", 0, A) is False


def test_bucket_limit_blocks_further_enqueue() -> None:
    frontier = Frontier(bucket_limit=2)

    assert frontier.enqueue(A + "1", 0, A) is True
    assert frontier.enqueue(A + "2", 0, A) is True
    assert frontier.enqueue(A + "3", 0, A) is False
    assert frontier.pending_in_host("a.example") == 2
    # 另一个 host 不受影响
    assert frontier.enqueue(B + "1", 0, B) is True


def test_force_ignores_bucket_limit_for_resume() -> None:
    frontier = Frontier(bucket_limit=1)
    frontier.enqueue(A + "1", 0, A)

    assert frontier.enqueue(A + "2", 0, A, force=True) is True
    assert frontier.pending_in_host("a.example") == 2


def test_hosts_are_served_one_bucket_at_a_time() -> None:
    frontier = Frontier()
    frontier.enqueue(A + "1", 0, A)
    frontier.enqueue(A + "2", 0, A)
    frontier.enqueue(B + "1", 0, B)

    order = []
    while (page := frontier.next_url()) is not None:
        order.append(page.host)

    # 当前策略是"把一个 host 的待抓做完再换下一个"，对站方更友好；
    # 它也意味着慢站点会拖住后面的站点，若将来需要公平轮转再改这里。
    assert order == ["a.example", "a.example", "b.example"]


def test_depth_and_seed_are_recorded() -> None:
    frontier = Frontier()
    frontier.enqueue(A + "1", depth=3, seed_url=A)

    page = frontier.next_url()

    assert page is not None
    assert (page.depth, page.seed_url, page.host) == (3, A, "a.example")


def test_as_list_preserves_pending_pages() -> None:
    frontier = Frontier()
    frontier.enqueue(A + "1", 0, A)
    frontier.enqueue(B + "1", 1, B)

    assert {(page.url, page.depth) for page in frontier.as_list()} == {
        (A + "1", 0),
        (B + "1", 1),
    }
