from datetime import date
from unittest.mock import patch

import pandas as pd

from app.data_sources.akshare_adapter import fetch
from app.services.pipeline import session_schedule


def test_fetch_retries_transient_provider_failure():
    frame = pd.DataFrame([{
        "日期": "2024-01-02", "开盘": "100", "最高": "102",
        "最低": "99", "收盘": "101", "成交量": "1,000",
    }])
    with patch("app.data_sources.akshare_adapter._fetch_frame", side_effect=[ConnectionError("temporary"), frame]) as call, patch("app.data_sources.akshare_adapter.time.sleep"):
        rows = fetch("akshare_csindex", "000300", date(2024, 1, 1), date(2024, 1, 3))

    assert call.call_count == 2
    assert len(rows) == 1
    assert rows[0]["close"] == 101


def test_session_schedule_falls_back_beyond_calendar_horizon():
    calendar = type("Calendar", (), {"sessions_in_range": lambda self, start, end: (_ for _ in ()).throw(ValueError("out of bounds"))})()
    with patch("app.services.pipeline.xcals.get_calendar", return_value=calendar):
        days, covered = session_schedule("CN", date(2030, 1, 5), date(2030, 1, 7))

    assert covered is False
    assert days == [date(2030, 1, 7)]
