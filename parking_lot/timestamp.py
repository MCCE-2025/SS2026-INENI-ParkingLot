"""UTC timestamps for status events: ISO-8601 (sort key) + microsecond epoch."""

import time
from datetime import datetime, timezone


def event_timestamps():
    """Return ``(iso_ts, epoch_us)`` for the same instant.

    * ``iso_ts`` — ISO-8601 UTC with fractional seconds (DynamoDB sort key ``ts``).
    * ``epoch_us`` — microseconds since Unix epoch (stored as attribute ``epoch``).
    """
    epoch_us = time.time_ns() // 1000
    sec, micro = divmod(epoch_us, 1_000_000)
    dt = datetime.fromtimestamp(sec, tz=timezone.utc).replace(microsecond=micro)
    iso = dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return iso, epoch_us
