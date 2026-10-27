from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from tests.unit.domain.assertions import expect_validation
from quotedesk.domain.shared.windows import DateWindow

UNORDERED = "A window's end is on or after its start."
NOT_A_DATE = "A window is made of calendar dates."


def test_window_requires_ordered_dates():
    day = date(2026, 11, 7)
    same_day = DateWindow(start=day, end=day)
    assert same_day.start == day
    assert same_day.end == day

    later = DateWindow(start=day, end=date(2026, 11, 9))
    assert later.end == date(2026, 11, 9)

    expect_validation(
        lambda: DateWindow(start=day, end=date(2026, 11, 6)),
        "date_window.unordered",
        UNORDERED,
    )


def test_window_contains_edges():
    window = DateWindow(start=date(2026, 11, 7), end=date(2026, 11, 9))
    assert window.contains(date(2026, 11, 6)) is False
    assert window.contains(date(2026, 11, 7)) is True
    assert window.contains(date(2026, 11, 8)) is True
    assert window.contains(date(2026, 11, 9)) is True
    assert window.contains(date(2026, 11, 10)) is False


def test_window_rejects_aware_datetime():
    civil = date(2026, 11, 7)
    accepted = DateWindow(start=civil, end=civil)
    assert accepted.start == civil

    naive = datetime(2026, 11, 7, 12, 0)
    aware = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
    johannesburg = datetime(2026, 11, 7, 0, 30, tzinfo=ZoneInfo("Africa/Johannesburg"))
    for value in (naive, aware, johannesburg):
        expect_validation(
            lambda value=value: DateWindow(start=value, end=civil),
            "date_window.not_a_date",
            NOT_A_DATE,
        )
        expect_validation(
            lambda value=value: DateWindow(start=civil, end=value),
            "date_window.not_a_date",
            NOT_A_DATE,
        )
        expect_validation(
            lambda value=value: DateWindow(start=civil, end=civil).contains(value),
            "date_window.not_a_date",
            NOT_A_DATE,
        )
