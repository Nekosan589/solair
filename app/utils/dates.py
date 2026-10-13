from datetime import date, timedelta, datetime, timezone
from zoneinfo import ZoneInfo

from app.enums import ForecastDay, DateFilter


def get_forecast_date(day: ForecastDay) -> str:
    """Returns an ISO date string ('YYYY-MM-DD') for Open-Meteo's start/end date params."""
    target = date.today() if day == ForecastDay.today else date.today() + timedelta(days=1)
    return target.isoformat()


def day_bounds(target_date: str):
    """Returns (start, end) datetimes spanning the full day for a 'YYYY-MM-DD' date string."""
    from datetime import datetime

    start = datetime.fromisoformat(target_date)
    end = start.replace(hour=23, minute=59, second=59)
    return start, end

def get_date_range(filter: DateFilter) -> tuple[datetime, datetime]:
    now = datetime.now()
    today_start = datetime.combine(date.today(), datetime.min.time())

    if filter == DateFilter.TODAY:
        start = today_start
        end = today_start + timedelta(days=1)

    elif filter == DateFilter.THIS_WEEK:
        # Monday as start of week
        start = today_start - timedelta(days=today_start.weekday())
        end = start + timedelta(days=7)

    elif filter == DateFilter.THIS_MONTH:
        start = today_start.replace(day=1)
        # first day of next month
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1)
        else:
            end = start.replace(month=start.month + 1)

    else:
        raise ValueError("Unsupported filter")

    return start, end

PH_TZ = ZoneInfo("Asia/Manila")


def get_ph_target_date(day: ForecastDay) -> date:
    """Returns the PH-local calendar date corresponding to 'today' or 'tomorrow'."""
    now_ph = datetime.now(PH_TZ)
    return now_ph.date() if day == ForecastDay.today else now_ph.date() + timedelta(days=1)


def ph_day_utc_window(target_date: date) -> tuple[datetime, datetime]:
    """
    Returns (start, end) as NAIVE UTC datetimes spanning the full PH
    calendar day [00:00, 24:00) Asia/Manila for target_date. Half-open
    interval: a row belongs to this day if start <= hour < end.

    Naive (no tzinfo) to match how hours are stored elsewhere in the app —
    the values themselves are UTC, just without an attached tzinfo object.
    """
    ph_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=PH_TZ)
    ph_end = ph_start + timedelta(days=1)

    start_utc = ph_start.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = ph_end.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc
