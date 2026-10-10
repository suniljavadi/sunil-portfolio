from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from job_agent.models import (
    CandidateProfile,
    ScheduledRun,
    TaskExecution,
)
from job_agent.services.job_discovery import discover_jobs


def execute_discovery_run(
    session: Session,
    profile: CandidateProfile,
    *,
    run_type: str,
    source_ids: set[int] | None = None,
    retry_of_id: int | None = None,
) -> ScheduledRun:
    run = ScheduledRun(
        run_type=run_type,
        retry_of_id=retry_of_id,
        status="RUNNING",
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    try:
        summary = discover_jobs(session, profile, source_ids=source_ids)
        run.summary = summary
        run.status = "COMPLETED" if not summary["source_failures"] else "PARTIAL"
        for failure in summary["source_failures"]:
            session.add(TaskExecution(
                task_name=f"discovery_source:{failure['provider']}:{failure['source_id']}",
                status="FAILED",
                error_message=failure["error"],
            ))
    except Exception as exc:
        session.rollback()
        run = session.get(ScheduledRun, run.id)
        if run is None:
            raise RuntimeError("Scheduled run disappeared while recording its failure.") from exc
        run.status = "FAILED"
        run.summary = {"error": str(exc), "source_failures": []}
        session.add(TaskExecution(
            task_name="daily_discovery",
            status="FAILED",
            error_message=str(exc),
        ))
    run.finished_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(run)
    return run


def serialize_run(run: ScheduledRun) -> dict:
    return {
        "id": run.id,
        "retry_of_id": run.retry_of_id,
        "run_type": run.run_type,
        "status": run.status,
        "summary": run.summary,
        "started_at": run.started_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
