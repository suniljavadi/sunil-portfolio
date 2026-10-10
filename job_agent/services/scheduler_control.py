from datetime import datetime, timezone

from sqlalchemy.orm import Session

from job_agent.config import settings
from job_agent.models import SchedulerControl


def ensure_scheduler_control(session: Session) -> SchedulerControl:
    control = session.get(SchedulerControl, 1)
    if control is None:
        control = SchedulerControl(
            id=1,
            enabled=True,
            timezone=settings.scheduler_timezone,
            hour=settings.scheduler_hour,
            minute=settings.scheduler_minute,
            daily_application_limit=settings.daily_application_limit,
        )
        session.add(control)
        session.flush()
    return control


def scheduler_status(
    control: SchedulerControl,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    heartbeat = control.last_heartbeat
    if heartbeat is not None and heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=timezone.utc)
    is_alive = bool(heartbeat and (now - heartbeat).total_seconds() <= 90)
    return {
        "enabled": control.enabled,
        "timezone": control.timezone,
        "hour": control.hour,
        "minute": control.minute,
        "daily_application_limit": control.daily_application_limit,
        "worker_status": "running" if is_alive else "not_seen_or_stale",
        "worker_started_at": control.worker_started_at.isoformat() if control.worker_started_at else None,
        "last_heartbeat": control.last_heartbeat.isoformat() if control.last_heartbeat else None,
    }
