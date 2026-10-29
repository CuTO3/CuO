'''
本文件用途：Core/clock.py 的后端实现。

配置字段：
未检测到直接读取共享 Settings 或环境变量；局部参数与间接依赖仍需逐项核查。
'''

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
