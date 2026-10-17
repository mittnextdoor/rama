"""One clock for the whole system, so tests and demos can freeze or advance time."""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
LOCAL = ZoneInfo("America/New_York")
_fixed: datetime | None = None


def now() -> datetime:
    return _fixed if _fixed is not None else datetime.now(UTC).replace(microsecond=0)


def freeze(dt: datetime | str | None):
    global _fixed
    _fixed = parse(dt) if isinstance(dt, str) else dt


def advance(**kw):
    freeze(now() + timedelta(**kw))


def iso(dt: datetime | None = None) -> str:
    return (dt or now()).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def local(dt: datetime | None = None) -> datetime:
    return (dt or now()).astimezone(LOCAL)


def month(dt: datetime | None = None) -> str:
    return local(dt).strftime("%Y-%m")


def add_business_days(dt: datetime, days: int) -> datetime:
    d = dt
    while days > 0:
        d += timedelta(days=1)
        if local(d).weekday() < 5:
            days -= 1
    return d


def days_left_in_month(dt: datetime | None = None) -> int:
    d = local(dt).date()
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return (nxt - d).days
