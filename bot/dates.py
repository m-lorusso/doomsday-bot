"""Australian date formatting - day before month, everywhere, no exceptions.

The APIs hand back ISO strings (2026-12-17T22:30) in cinema-local time, which
is already Sydney time, so those are displayed as-is. Only "now" needs a real
time zone, and Sydney's changes twice a year: AEST (UTC+10) through winter,
AEDT (UTC+11) from the first Sunday in October to the first Sunday in April.
"""

from datetime import date, datetime, timedelta, timezone


def _parse(value):
    if isinstance(value, (datetime, date)):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _first_sunday(year: int, month: int) -> date:
    d = date(year, month, 1)
    return d + timedelta(days=(6 - d.weekday()) % 7)


def sydney_offset(utc_now: datetime) -> timedelta:
    """UTC offset for Sydney at `utc_now` (an aware UTC datetime).

    Uses the system zone database when there is one (Linux, so GitHub Actions)
    and falls back to the NSW rule otherwise - Windows Python ships without
    zone data, which is where the old hard-coded +11 would have been wrong.
    """
    try:
        from zoneinfo import ZoneInfo

        return utc_now.astimezone(ZoneInfo("Australia/Sydney")).utcoffset()
    except Exception:  # noqa: BLE001 - no tz database on this machine
        pass
    # DST starts 2am AEST and ends 3am AEDT, both of which are 16:00 UTC on the
    # Saturday before the first Sunday of October / April.
    year = utc_now.year
    start = datetime.combine(_first_sunday(year, 10), datetime.min.time(), timezone.utc) - timedelta(hours=8)
    end = datetime.combine(_first_sunday(year, 4), datetime.min.time(), timezone.utc) - timedelta(hours=8)
    daylight = utc_now >= start or utc_now < end
    return timedelta(hours=11 if daylight else 10)


def now_sydney() -> datetime:
    utc = datetime.now(timezone.utc)
    return utc.astimezone(timezone(sydney_offset(utc)))


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


def days_until(target) -> int | None:
    dt = _parse(target)
    if not dt:
        return None
    d = dt.date() if isinstance(dt, datetime) else dt
    return (d - now_sydney().date()).days
