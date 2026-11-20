"""Turn every timestamp format in the data room into UTC.

Each source system stores time differently. The rules below were checked against the data
itself (phase 4), not guessed:
  - email:   ISO 8601 with an offset, "Z", or naive. Naive values are IST: read as IST, all 185
             naive events fall in order between their neighbours; read as UTC, half do not.
  - widget:  "YYYY-MM-DD HH:MM:SS" naive (IST: exactly +5:30 from the epoch-ms history, 483/483)
             and epoch milliseconds.
  - partner: "DD/MM/YYYY HH:MM GST|IST" (explicit zone), other fields naive ISO in IST
             (exactly +5:30 from opened_on, 219/219, whatever its label).
  - calls:   "DD-MM-YYYY HH:MM" naive, assumed IST (Pune call centre; nothing to check against).
  - CSAT:    "YYYY-MM-DD HH:MM" naive, assumed IST.
"""

import re
from datetime import UTC, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), "IST")
GST = timezone(timedelta(hours=4), "GST")
ZONES = {"IST": IST, "GST": GST, "UTC": UTC, "Z": UTC}

_PARTNER = re.compile(r"^(\d{2})/(\d{2})/(\d{4}) (\d{2}):(\d{2})(?: (IST|GST|UTC))?$")
_DMY = re.compile(r"^(\d{2})-(\d{2})-(\d{4}) (\d{2}):(\d{2})$")


def parse_ts(value, naive_tz=IST) -> datetime | None:
    """Any data-room timestamp -> aware UTC datetime. None, '' and 'null' -> None."""
    if value is None or value == "" or value == "null":
        return None
    if isinstance(value, bool):
        raise ValueError("boolean is not a timestamp")
    if isinstance(value, int | float):
        seconds = value / 1000 if value > 1e11 else value  # epoch ms (data room) or seconds
        return datetime.fromtimestamp(seconds, UTC)
    s = str(value).strip()
    m = _PARTNER.match(s)
    if m:
        d, mo, y, h, mi, zone = m.groups()
        local = datetime(int(y), int(mo), int(d), int(h), int(mi), tzinfo=ZONES.get(zone, naive_tz))
        return local.astimezone(UTC)
    m = _DMY.match(s)
    if m:
        d, mo, y, h, mi = map(int, m.groups())
        return datetime(y, mo, d, h, mi, tzinfo=naive_tz).astimezone(UTC)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"unrecognised timestamp format: {re.sub(r'[0-9]', '9', s)}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=naive_tz)
    return dt.astimezone(UTC)
