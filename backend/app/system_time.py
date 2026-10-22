from datetime import datetime, timezone


def get_system_time() -> datetime:
    return datetime.now(timezone.utc)
