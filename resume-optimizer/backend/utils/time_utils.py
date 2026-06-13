"""Datetime helpers for DB values.

SQLite (dev/tests) returns naive datetimes even for DateTime(timezone=True)
columns; Postgres returns aware ones. Normalize before any Python-side
comparison with datetime.now(timezone.utc).
"""
from datetime import datetime, timezone
from typing import Optional


def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Return dt as a timezone-aware UTC datetime (naive values assumed UTC)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
