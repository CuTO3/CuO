"""All business dates use original trigger time and a 04:00 Beijing boundary."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

BEIJING = ZoneInfo("Asia/Shanghai")


def require_aware(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timezone-aware datetime required")
    return value.astimezone(BEIJING)


def now() -> datetime:
    return datetime.now(timezone.utc)


def business_date(triggered_at: datetime) -> date:
    return (require_aware(triggered_at) - timedelta(hours=4)).date()


def day_bounds(day: date | str) -> tuple[datetime, datetime]:
    if isinstance(day, str):
        day = date.fromisoformat(day)
    start = datetime.combine(day, time(4), BEIJING)
    return start, start + timedelta(days=1)


def summary_bounds(day: date | str, cutoff: datetime) -> tuple[datetime, datetime]:
    start, end = day_bounds(day)
    end = min(end, require_aware(cutoff))
    if end <= start:
        raise ValueError("future or empty date range")
    return start, end


get_business_date = business_date
business_day_bounds = day_bounds
