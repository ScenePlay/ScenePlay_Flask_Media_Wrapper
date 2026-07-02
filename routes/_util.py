"""Small helpers shared across route modules."""
from datetime import datetime


def _now():
    """Local wall-clock timestamp, 'YYYY-MM-DD HH:MM:SS'.

    Single definition matters: these strings are stored in created_at /
    rolled_at columns and compared during relay sync ordering, so every
    module must format identically.
    """
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
