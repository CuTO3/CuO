from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
BEIJING = ZoneInfo("Asia/Shanghai")
def require_aware(value):
    if not isinstance(value,datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("aware datetime required")
    return value.astimezone(BEIJING)
def now():
    return datetime.now(timezone.utc)
def business_date(value):
    return (require_aware(value)-timedelta(hours=4)).date()
def day_bounds(day):
    if isinstance(day,str): day=date.fromisoformat(day)
    if type(day) is not date: raise ValueError("date required")
    start=datetime.combine(day,time(4),BEIJING)
    return start,start+timedelta(days=1)
def summary_bounds(day,cutoff):
    start,end=day_bounds(day)
    end=min(end,require_aware(cutoff))
    if end<=start: raise ValueError("future date")
    return start,end
