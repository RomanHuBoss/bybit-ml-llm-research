from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.strategies import _latest_fresh_closed_position


class _Rows:
    def __init__(self, rows):
        self._rows = rows
        self.empty = not rows
        self.iloc = self

    def __len__(self):
        return len(self._rows)

    def __getitem__(self, index):
        return self._rows[index]


def test_latest_fresh_closed_position_skips_unclosed_tail_bar():
    now = datetime.now(timezone.utc)
    rows = _Rows(
        [
            {"start_time": now - timedelta(minutes=45)},
            {"start_time": now - timedelta(minutes=30)},
            {"start_time": now - timedelta(minutes=15)},
            {"start_time": now},
        ]
    )

    assert _latest_fresh_closed_position(rows, "15", scan_tail=4) == 2


def test_latest_fresh_closed_position_rejects_stale_market():
    now = datetime.now(timezone.utc)
    rows = _Rows([{"start_time": now - timedelta(hours=12)}])

    assert _latest_fresh_closed_position(rows, "15", scan_tail=4) is None
