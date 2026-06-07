from datetime import datetime, time
import pytz

EASTERN = pytz.timezone("America/New_York")

_SESSIONS = [
    ("premarket",            time(4,  0),  time(9,  30)),
    ("ny_open",              time(9,  30), time(10,  0)),
    ("morning_continuation", time(10,  0), time(11, 30)),
    ("lunch",                time(11, 30), time(13,  0)),
    ("afternoon",            time(13,  0), time(15, 30)),
    ("power_hour",           time(15, 30), time(16,  0)),
    ("after_hours",          time(16,  0), time(20,  0)),
]


def get_session_label(timestamp) -> str:
    if isinstance(timestamp, str):
        dt = datetime.fromisoformat(timestamp)
    else:
        dt = timestamp

    if dt.tzinfo is None:
        dt = EASTERN.localize(dt)
    else:
        dt = dt.astimezone(EASTERN)

    t = dt.time()
    for label, start, end in _SESSIONS:
        if start <= t < end:
            return label

    return "closed"
