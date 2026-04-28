from __future__ import annotations


def test_bounded_worker_count_caps_jobs_and_hard_limit():
    from app.concurrency import bounded_worker_count

    assert bounded_worker_count(10, 3, hard_limit=8) == 3
    assert bounded_worker_count(10, 20, hard_limit=4) == 4
    assert bounded_worker_count(0, 5) == 1
    assert bounded_worker_count(3, 0) == 0
