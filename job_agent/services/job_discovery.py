from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from job_agent.models import Application, CandidateProfile, Job, JobMatch, JobSource
from job_agent.services.applications import make_idempotency_key, transition
from job_agent.services.discovery import (
    BoardError,
    GreenhouseAdapter,
    LeverAdapter,
    canonicalize,
)
from job_agent.services.matching import score_job


def discover_jobs(
    session: Session,
    profile: CandidateProfile,
    source_ids: set[int] | None = None,
) -> dict:
    statement = select(JobSource).where(JobSource.enabled.is_(True))
    if source_ids is not None:
        if not source_ids:
            return {"new_jobs": 0, "duplicates": 0, "sources_checked": 0, "source_failures": []}
        statement = statement.where(JobSource.id.in_(source_ids))
    sources = session.scalars(statement).all()
    created = 0
    duplicates = 0
    failures = []
    for source in sources:
        adapter = GreenhouseAdapter() if source.provider == "greenhouse" else LeverAdapter()
        try:
            discovered = adapter.fetch(source.board_token)
        except BoardError as exc:
            failures.append({
                "source_id": source.id,
                "source": source.board_token,
                "provider": source.provider,
                "error": str(exc),
            })
            continue
        for item in discovered:
            canonical = canonicalize(item.url)
            existing = session.scalar(select(Job.id).where(Job.canonical_url == canonical))
            if existing:
                duplicates += 1
                continue
            job = Job(
                source_id=source.id,
                external_id=item.external_id,
                canonical_url=canonical,
                title=item.title,
                company=source.company_name,
                location=item.location,
                work_mode=item.work_mode,
                description=item.description,
            )
            try:
                with session.begin_nested():
                    session.add(job)
                    session.flush()
                    result = score_job(profile, job)
                    session.add(JobMatch(
                        job_id=job.id,
                        ai_score=result["score"] if "AI/GenAI" in result["matching_tracks"] else 0,
                        data_score=result["score"] if "Data Engineering/BI" in result["matching_tracks"] else 0,
                        components=result["components"],
                        explanation=result,
                        eligibility=result["eligibility"],
                    ))
                    application = Application(
                        job_id=job.id,
                        idempotency_key=make_idempotency_key(job.id),
                        status="DISCOVERED",
                    )
                    session.add(application)
                    transition(application, "SCORED")
                    transition(application, "ELIGIBILITY_CHECKED")
                    if result["eligibility"] == "ELIGIBLE":
                        transition(application, "RESUME_READY")
                        transition(application, "PENDING_APPROVAL")
                    elif result["eligibility"] == "REJECTED_BY_RULES":
                        application.status = "REJECTED_BY_RULES"
                    else:
                        application.status = "NEEDS_MANUAL_ACTION"
            except IntegrityError:
                duplicates += 1
                continue
            created += 1
    session.commit()
    return {
        "new_jobs": created,
        "duplicates": duplicates,
        "sources_checked": len(sources),
        "source_failures": failures,
    }
