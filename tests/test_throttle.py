"""按 host 限速与前缀去重。"""

from __future__ import annotations

from crawler.throttle import HostThrottle, delay_for


def test_first_request_needs_no_wait() -> None:
    throttle = HostThrottle()

    assert throttle.wait_seconds("https://a.example/x", 5.0, now=1000.0) == 0.0


def test_same_host_waits_out_the_interval() -> None:
    throttle = HostThrottle()
    throttle.record("https://a.example/x", now=1000.0)

    assert throttle.wait_seconds("https://a.example/y", 5.0, now=1002.0) == 3.0
    assert throttle.wait_seconds("https://a.example/y", 5.0, now=1006.0) == 0.0


def test_different_hosts_do_not_interfere() -> None:
    throttle = HostThrottle()
    throttle.record("https://a.example/x", now=1000.0)

    assert throttle.wait_seconds("https://b.example/y", 5.0, now=1000.5) == 0.0


def test_host_comparison_ignores_case_but_keeps_port() -> None:
    throttle = HostThrottle()
    throttle.record("https://A.Example:8443/x", now=1000.0)

    # 同一 host 的大小写不同应视为同一 host（netloc 统一小写）
    assert throttle.wait_seconds("https://a.example:8443/y", 5.0, now=1001.0) == 4.0
    # 不同端口视为不同站点，互不影响
    assert throttle.wait_seconds("https://a.example/y", 5.0, now=1001.0) == 0.0


def test_zero_delay_never_waits() -> None:
    throttle = HostThrottle()
    throttle.record("https://a.example/x", now=1000.0)

    assert throttle.wait_seconds("https://a.example/y", 0.0, now=1000.0) == 0.0


def test_delay_for_prefers_larger_robots_value() -> None:
    class FakeRobots:
        def __init__(self, delay: float | None) -> None:
            self.delay = delay

        def crawl_delay_for(self, url: str) -> float | None:
            return self.delay

    assert delay_for("https://a.example/", 1.0, FakeRobots(None)) == 1.0
    assert delay_for("https://a.example/", 1.0, FakeRobots(0.5)) == 1.0  # 配置更大
    assert delay_for("https://a.example/", 1.0, FakeRobots(10.0)) == 10.0  # robots 更大
    assert delay_for("https://a.example/", 1.0, None) == 1.0
