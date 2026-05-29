"""UTC timestamps for status events (control Lambda)."""

import time
from datetime import datetime, timezone


def event_timestamps():
    epoch_us = time.time_ns() // 1000
    sec, micro = divmod(epoch_us, 1_000_000)
    dt = datetime.fromtimestamp(sec, tz=timezone.utc).replace(microsecond=micro)
    iso = dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return iso, epoch_us
