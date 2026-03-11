from datetime import datetime
from zoneinfo import ZoneInfo

from config import USER_TIMEZONE


def get_current_datetime(timezone: str | None = None) -> str:
    tz = ZoneInfo(timezone or USER_TIMEZONE)
    now = datetime.now(tz)
    return now.strftime("%Y-%m-%d %H:%M:%S %Z (%A)")
