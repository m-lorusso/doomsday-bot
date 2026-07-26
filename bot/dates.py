"""Australian date formatting - day before month, everywhere, no exceptions.

The APIs hand back ISO strings (2026-12-17T22:30). Nothing user-facing should
ever show that shape, and nothing should ever show a US month-first date.
"""

from datetime import date, datetime, timedelta, timezone

SYD = timezone(timedelta(hours=11))  # AEDT, which is what December is


def _parse(value):
    if isinstance(value, (datetime, date)):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def au_date(value) -> str:
    """2026-12-17 -> '17 Dec 2026'"""
    dt = _parse(value)
    return f"{dt.day} {dt:%b %Y}" if dt else str(value)


def au_short(value) -> str:
    """2026-12-17T22:30 -> 'Thu 17 Dec'"""
    dt = _parse(value)
    return f"{dt:%a} {dt.day} {dt:%b}" if dt else str(value)


def au_time(value) -> str:
    """2026-12-17T22:30 -> '10:30 PM'"""
    dt = _parse(value)
    if not dt:
        return str(value)
    return f"{dt:%I:%M %p}".lstrip("0")


def au_datetime(value) -> str:
    """2026-12-17T22:30 -> 'Thu 17 Dec 2026, 10:30 PM'"""
    dt = _parse(value)
    if not dt:
        return str(value)
    return f"{dt:%a} {dt.day} {dt:%b %Y}, " + au_time(dt)


def now_sydney() -> datetime:
    return datetime.now(timezone.utc).astimezone(SYD)


def days_until(target) -> int | None:
    dt = _parse(target)
    if not dt:
        return None
    d = dt.date() if isinstance(dt, datetime) else dt
    return (d - now_sydney().date()).days
