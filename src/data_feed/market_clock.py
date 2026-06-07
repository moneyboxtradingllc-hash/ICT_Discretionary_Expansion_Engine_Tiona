from datetime import datetime
import pytz

_EASTERN = pytz.timezone("America/New_York")


def is_within_scan_window(start_str: str = "08:30", end_str: str = "15:00") -> bool:
    """
    Return True if the current ET time falls within [start_str, end_str).
    Both strings must be in "HH:MM" 24-hour format.
    No market-open check — window is time-only, scan mode only.
    """
    now_et = datetime.now(_EASTERN)
    now_minutes = now_et.hour * 60 + now_et.minute

    sh, sm = map(int, start_str.split(":"))
    eh, em = map(int, end_str.split(":"))

    return (sh * 60 + sm) <= now_minutes < (eh * 60 + em)
