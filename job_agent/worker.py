import logging
from datetime import datetime, timezone

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import select

from job_agent.db import SessionLocal, engine
from job_agent.models import SchedulerControl
from job_agent.services.run_history import execute_discovery_run
from job_agent.services.scheduler_control import ensure_scheduler_control

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("job_agent.worker")
_scheduler: BlockingScheduler | None = None


def scheduled_discovery() -> None:
    """Run job discovery independently from web/dashboard processes."""
    with SessionLocal() as session:
        control = ensure_scheduler_control(session)
        if not control.enabled:
            logger.info("Skipping scheduled discovery because scheduler is paused")
            session.commit()
            return
        profile = session.scalar(select(CandidateProfile).order_by(CandidateProfile.id).limit(1))
        if profile is None:
            logger.error("Scheduled discovery skipped: candidate profile is not configured")
            return
        run = execute_discovery_run(session, profile, run_type="daily_discovery")
        if run.status in {"FAILED", "PARTIAL"}:
            logger.error("Scheduled discovery ended status=%s run_id=%s summary=%s", run.status, run.id, run.summary)


def refresh_schedule(scheduler: BlockingScheduler | None = None) -> None:
    scheduler = scheduler or _scheduler
    if scheduler is None:
        raise RuntimeError("Scheduler instance is not initialized.")
    with SessionLocal() as session:
        control = ensure_scheduler_control(session)
        control.last_heartbeat = datetime.now(timezone.utc)
        job = scheduler.get_job("daily-discovery")
        if job is None:
            scheduler.add_job(
                scheduled_discovery,
                "cron",
                id="daily-discovery",
                hour=control.hour,
                minute=control.minute,
                timezone=control.timezone,
                replace_existing=True,
                misfire_grace_time=3600,
            )
        else:
            trigger_timezone = getattr(job.trigger.timezone, "key", str(job.trigger.timezone))
            current_hour = next(field for field in job.trigger.fields if field.name == "hour")
            current_minute = next(field for field in job.trigger.fields if field.name == "minute")
            if (
                trigger_timezone != control.timezone
                or str(current_hour) != str(control.hour)
                or str(current_minute) != str(control.minute)
            ):
                scheduler.reschedule_job(
                    "daily-discovery",
                    trigger="cron",
                    hour=control.hour,
                    minute=control.minute,
                    timezone=control.timezone,
                )
        job = scheduler.get_job("daily-discovery")
        if control.enabled and job and job.next_run_time is None:
            scheduler.resume_job("daily-discovery")
        elif not control.enabled and job and job.next_run_time is not None:
            scheduler.pause_job("daily-discovery")
        session.commit()


def main() -> None:
    global _scheduler
    with SessionLocal() as session:
        control = ensure_scheduler_control(session)
        control.worker_started_at = datetime.now(timezone.utc)
        control.last_heartbeat = control.worker_started_at
        session.commit()
        timezone_name = control.timezone
        hour = control.hour
        minute = control.minute
    scheduler = BlockingScheduler(
        jobstores={"default": SQLAlchemyJobStore(engine=engine)},
        timezone=timezone_name,
    )
    _scheduler = scheduler
    scheduler.add_job(
        scheduled_discovery,
        "cron",
        id="daily-discovery",
        hour=hour,
        minute=minute,
        replace_existing=True, misfire_grace_time=3600,
    )
    scheduler.add_job(
        refresh_schedule,
        "interval",
        seconds=30,
        id="refresh-scheduler-control",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    refresh_schedule(scheduler)
    logger.info("Scheduler worker started with persisted schedule %02d:%02d %s", hour, minute, timezone_name)
    scheduler.start()


if __name__ == "__main__":
    main()
