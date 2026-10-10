import logging
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from job_agent.config import settings
from job_agent.db import get_session
from job_agent.models import (
    Application,
    ApplicationAnswer,
    AuditLog,
    CandidateProfile,
    Job,
    JobSource,
    Resume,
    ResumeVersion,
    ScheduledRun,
    SchedulerControl,
    TaskExecution,
)
from job_agent.schemas import (
    AnswerCheckIn,
    ApplicationAnswerIn,
    ApplicationApprovalIn,
    CandidateProfileIn,
    SchedulerControlIn,
    SourceIn,
)
from job_agent.services.answer_bank import (
    AnswerEncryptionUnavailable,
    check_required_answers,
    decrypt_answer,
    encrypt_answer,
    effective_status,
)
from job_agent.services.applications import transition
from job_agent.services.audit import profile_audit
from job_agent.services.resumes import digest, extract_resume
from job_agent.services.run_history import execute_discovery_run, serialize_run
from job_agent.services.tailoring import generate_ats_docx
from job_agent.services.scheduler_control import ensure_scheduler_control, scheduler_status
from pypdf.errors import PdfReadError
from zipfile import BadZipFile

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("job_agent")

app = FastAPI(title="Sunil Javadi Job Agent", version="0.1.0")


def require_token(authorization: str | None = Header(default=None)) -> None:
    if not settings.api_token:
        raise HTTPException(status_code=503, detail="Set JOB_AGENT_API_TOKEN before using the API.")
    if authorization != f"Bearer {settings.api_token}":
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token.")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "scheduler": "independent worker process"}


@app.get("/profile", dependencies=[Depends(require_token)])
def get_profile(session: Session = Depends(get_session)) -> dict:
    profile = session.scalar(select(CandidateProfile).limit(1))
    if profile is None:
        profile = CandidateProfile()
        session.add(profile)
        session.commit()
        session.refresh(profile)
    return _profile_dict(profile)


@app.put("/profile", dependencies=[Depends(require_token)])
def update_profile(payload: CandidateProfileIn, session: Session = Depends(get_session)) -> dict:
    profile = session.scalar(select(CandidateProfile).limit(1))
    if profile is None:
        profile = CandidateProfile()
        session.add(profile)
    for key, value in payload.model_dump().items():
        setattr(profile, key, value)
    session.add(AuditLog(action="profile_updated", entity_type="candidate_profile", entity_id=str(profile.id or "new")))
    session.commit()
    session.refresh(profile)
    return _profile_dict(profile)


@app.post("/resumes", dependencies=[Depends(require_token)])
async def upload_resume(file: UploadFile = File(...), session: Session = Depends(get_session)) -> dict:
    filename = Path(file.filename or "").name
    if Path(filename).suffix.lower() not in {".pdf", ".docx"}:
        raise HTTPException(415, "Only PDF and DOCX resumes are accepted.")
    content = await file.read(settings.max_upload_bytes + 1)
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(413, "Resume exceeds the configured upload limit.")
    try:
        text, content_type = extract_resume(filename, content)
    except (ValueError, PdfReadError, BadZipFile) as exc:
        raise HTTPException(422, str(exc)) from exc
    checksum = digest(content)
    existing = session.scalar(select(Resume).where(Resume.sha256 == checksum))
    if existing:
        return {"id": existing.id, "duplicate": True}
    resume = Resume(filename=filename, content_type=content_type, sha256=checksum, text=text)
    session.add(resume)
    session.commit()
    session.refresh(resume)
    return {"id": resume.id, "filename": filename, "extracted_characters": len(text), "immutable": True}


@app.get("/audit/profile", dependencies=[Depends(require_token)])
def run_audit(session: Session = Depends(get_session)) -> dict:
    profile = session.scalar(select(CandidateProfile).limit(1)) or CandidateProfile()
    resume = session.scalar(select(Resume).order_by(Resume.created_at.desc()).limit(1))
    return profile_audit(profile, resume)


@app.post("/sources", dependencies=[Depends(require_token)])
def add_source(payload: SourceIn, session: Session = Depends(get_session)) -> dict:
    provider = payload.provider.lower()
    if provider not in {"greenhouse", "lever"}:
        raise HTTPException(422, "Supported public discovery providers: greenhouse and lever.")
    source = session.scalar(select(JobSource).where(
        JobSource.provider == provider, JobSource.board_token == payload.board_token
    ))
    if source is None:
        source = JobSource(
            provider=provider,
            board_token=payload.board_token,
            company_name=payload.company_name,
        )
        session.add(source)
        session.commit()
        session.refresh(source)
    return {
        "id": source.id,
        "provider": source.provider,
        "board_token": source.board_token,
        "company_name": source.company_name,
    }


@app.post("/discovery/run", dependencies=[Depends(require_token)])
def run_discovery(session: Session = Depends(get_session)) -> dict:
    profile = session.scalar(select(CandidateProfile).limit(1))
    if profile is None:
        raise HTTPException(409, "Create the candidate profile before discovery.")
    return serialize_run(
        execute_discovery_run(
            session,
            profile,
            run_type="manual_discovery",
        )
    )


@app.get("/scheduler", dependencies=[Depends(require_token)])
def get_scheduler(session: Session = Depends(get_session)) -> dict:
    control = ensure_scheduler_control(session)
    result = scheduler_status(control)
    session.commit()
    return result


@app.put("/scheduler", dependencies=[Depends(require_token)])
def update_scheduler(
    payload: SchedulerControlIn,
    session: Session = Depends(get_session),
) -> dict:
    try:
        ZoneInfo(payload.timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise HTTPException(422, "Unknown IANA time zone.") from exc
    control = ensure_scheduler_control(session)
    previous = {
        "enabled": control.enabled,
        "timezone": control.timezone,
        "hour": control.hour,
        "minute": control.minute,
        "daily_application_limit": control.daily_application_limit,
    }
    for key, value in payload.model_dump().items():
        setattr(control, key, value)
    session.add(AuditLog(
        action="scheduler_settings_updated",
        entity_type="scheduler",
        entity_id=str(control.id),
        details={"previous": previous, "updated": payload.model_dump()},
    ))
    session.commit()
    session.refresh(control)
    return scheduler_status(control)


@app.get("/scheduled-runs", dependencies=[Depends(require_token)])
def list_scheduled_runs(session: Session = Depends(get_session)) -> list[dict]:
    runs = session.scalars(
        select(ScheduledRun).order_by(ScheduledRun.started_at.desc()).limit(100)
    ).all()
    return [serialize_run(run) for run in runs]


@app.post("/scheduled-runs/{run_id}/retry", dependencies=[Depends(require_token)])
def retry_scheduled_run(run_id: int, session: Session = Depends(get_session)) -> dict:
    previous = session.get(ScheduledRun, run_id)
    if previous is None:
        raise HTTPException(404, "Scheduled run not found.")
    if previous.status not in {"FAILED", "PARTIAL"}:
        raise HTTPException(409, "Only failed or partial discovery runs can be retried.")
    profile = session.scalar(select(CandidateProfile).order_by(CandidateProfile.id).limit(1))
    if profile is None:
        raise HTTPException(409, "Create the candidate profile before retrying discovery.")

    source_failures = (previous.summary or {}).get("source_failures") or []
    failed_source_ids = {
        int(failure["source_id"])
        for failure in source_failures
        if "source_id" in failure
    }
    source_ids = failed_source_ids or None
    if source_ids is not None:
        enabled_source_ids = set(session.scalars(
            select(JobSource.id).where(
                JobSource.id.in_(source_ids),
                JobSource.enabled.is_(True),
            )
        ).all())
        if enabled_source_ids != source_ids:
            raise HTTPException(
                409,
                "One or more failed sources are no longer enabled; enable them before retrying.",
            )
    retry = execute_discovery_run(
        session,
        profile,
        run_type="manual_retry",
        source_ids=source_ids,
        retry_of_id=previous.id,
    )
    return serialize_run(retry)


@app.get("/task-executions", dependencies=[Depends(require_token)])
def list_task_executions(session: Session = Depends(get_session)) -> list[dict]:
    tasks = session.scalars(
        select(TaskExecution).order_by(TaskExecution.created_at.desc()).limit(100)
    ).all()
    return [
        {
            "id": task.id,
            "task_name": task.task_name,
            "status": task.status,
            "error_message": task.error_message,
            "created_at": task.created_at.isoformat(),
        }
        for task in tasks
    ]


@app.get("/jobs", dependencies=[Depends(require_token)])
def list_jobs(session: Session = Depends(get_session)) -> list[dict]:
    jobs = session.scalars(select(Job).order_by(Job.discovered_at.desc())).all()
    return [_job_dict(job) for job in jobs]


@app.post("/applications/{application_id}/approve", dependencies=[Depends(require_token)])
def approve_application(
    application_id: int,
    payload: ApplicationApprovalIn,
    session: Session = Depends(get_session),
) -> dict:
    application = session.get(Application, application_id)
    if application is None:
        raise HTTPException(404, "Application not found.")
    if not payload.answers_reviewed:
        raise HTTPException(409, "Review the application and its required answers before approval.")
    required_fields = [
        field.strip().lower().replace("-", "_") for field in payload.required_fields
    ]
    invalid = [
        field for field in required_fields
        if not field or len(field) > 100 or not field.replace("_", "").isalnum()
    ]
    if invalid:
        raise HTTPException(422, "Required answer field keys must use letters, numbers, underscores, or hyphens.")
    if len(set(required_fields)) != len(required_fields):
        raise HTTPException(422, "Required answer field keys must be unique.")
    answers = (
        session.scalars(
            select(ApplicationAnswer).where(ApplicationAnswer.field_key.in_(required_fields))
        ).all()
        if required_fields else []
    )
    readiness = check_required_answers(answers, required_fields)
    blocked = {
        key: readiness[key]
        for key in ("missing", "expired", "unverified")
        if readiness[key]
    }
    if blocked:
        raise HTTPException(
            409,
            {"message": "Required answers are missing, expired, or unverified.", **blocked},
        )
    manual_review_fields = readiness["manual_review_required"]
    if manual_review_fields and not payload.manual_review_acknowledged:
        raise HTTPException(
            409,
            {
                "message": "Sensitive or declaration answers require explicit manual review.",
                "manual_review_required": manual_review_fields,
            },
        )
    try:
        transition(application, "APPROVED")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    application.answers = {
        "required_fields": required_fields,
        "answers_reviewed": True,
        "manual_review_acknowledged": payload.manual_review_acknowledged,
        "manual_review_fields": manual_review_fields,
    }
    application.updated_at = datetime.now(timezone.utc)
    session.add(AuditLog(
        action="application_approved",
        entity_type="application",
        entity_id=str(application.id),
        details={
            "required_fields": required_fields,
            "manual_review_acknowledged": payload.manual_review_acknowledged,
            "manual_review_fields": manual_review_fields,
        },
    ))
    session.commit()
    return {
        "id": application.id,
        "status": application.status,
        "submission": "manual portal action required",
        "answers_reviewed": True,
        "manual_review_fields": manual_review_fields,
    }


@app.get("/applications", dependencies=[Depends(require_token)])
def list_applications(session: Session = Depends(get_session)) -> list[dict]:
    applications = session.scalars(select(Application).order_by(Application.updated_at.desc())).all()
    return [
        {"id": item.id, "job_id": item.job_id, "status": item.status, "job": _job_dict(item.job)}
        for item in applications
    ]


@app.get("/answer-bank", dependencies=[Depends(require_token)])
def list_answer_bank(session: Session = Depends(get_session)) -> list[dict]:
    answers = session.scalars(select(ApplicationAnswer).order_by(ApplicationAnswer.field_key)).all()
    try:
        return [
            {
                "field_key": answer.field_key,
                "value": None if answer.sensitive else decrypt_answer(answer.encrypted_value),
                "verification_status": effective_status(answer),
                "expires_at": answer.expires_at.isoformat() if answer.expires_at else None,
                "sensitive": answer.sensitive,
                "updated_at": answer.updated_at.isoformat(),
            }
            for answer in answers
        ]
    except AnswerEncryptionUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@app.put("/answer-bank/{field_key}", dependencies=[Depends(require_token)])
def save_answer(
    field_key: str,
    payload: ApplicationAnswerIn,
    session: Session = Depends(get_session),
) -> dict:
    normalized_key = field_key.strip().lower().replace("-", "_")
    if not normalized_key or len(normalized_key) > 100 or not normalized_key.replace("_", "").isalnum():
        raise HTTPException(422, "Answer field keys must use letters, numbers, underscores, or hyphens.")
    try:
        encrypted_value = encrypt_answer(payload.value)
    except AnswerEncryptionUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    answer = session.scalar(
        select(ApplicationAnswer).where(ApplicationAnswer.field_key == normalized_key)
    )
    if answer is None:
        answer = ApplicationAnswer(field_key=normalized_key, encrypted_value=encrypted_value)
        session.add(answer)
    answer.encrypted_value = encrypted_value
    answer.verification_status = payload.verification_status
    answer.expires_at = payload.expires_at
    answer.sensitive = payload.sensitive
    session.add(AuditLog(
        action="answer_updated",
        entity_type="application_answer",
        entity_id=normalized_key,
        details={
            "verification_status": payload.verification_status,
            "sensitive": payload.sensitive,
            "has_expiry": payload.expires_at is not None,
        },
    ))
    session.commit()
    session.refresh(answer)
    return {
        "field_key": answer.field_key,
        "verification_status": effective_status(answer),
        "expires_at": answer.expires_at.isoformat() if answer.expires_at else None,
        "sensitive": answer.sensitive,
        "updated_at": answer.updated_at.isoformat(),
    }


@app.post("/applications/{application_id}/answer-check", dependencies=[Depends(require_token)])
def check_application_answers(
    application_id: int,
    payload: AnswerCheckIn,
    session: Session = Depends(get_session),
) -> dict:
    if session.get(Application, application_id) is None:
        raise HTTPException(404, "Application not found.")
    normalized = [key.strip().lower().replace("-", "_") for key in payload.required_fields]
    invalid = [key for key in normalized if not key or len(key) > 100 or not key.replace("_", "").isalnum()]
    if invalid:
        raise HTTPException(422, "Required answer field keys must use letters, numbers, underscores, or hyphens.")
    answers = session.scalars(
        select(ApplicationAnswer).where(ApplicationAnswer.field_key.in_(normalized))
    ).all()
    return check_required_answers(answers, normalized)


@app.post("/applications/{application_id}/resume", dependencies=[Depends(require_token)])
def generate_resume(application_id: int, session: Session = Depends(get_session)) -> dict:
    application = session.get(Application, application_id)
    if application is None:
        raise HTTPException(404, "Application not found.")
    if application.status not in {"PENDING_APPROVAL", "APPROVED"}:
        raise HTTPException(409, "Generate a job-specific resume only after an eligible job is prepared.")
    if application.job.match is None or application.job.match.eligibility != "ELIGIBLE":
        raise HTTPException(409, "A verified eligible match is required to generate this document.")
    profile = session.scalar(select(CandidateProfile).limit(1))
    source_resume = session.scalar(select(Resume).order_by(Resume.created_at.desc()).limit(1))
    if profile is None or source_resume is None:
        raise HTTPException(409, "Candidate profile and source resume are required.")
    version_id, path, content_hash, selected_skills, summary = generate_ats_docx(
        profile, source_resume, application,
    )
    version = ResumeVersion(
        version_id=version_id,
        source_resume_id=source_resume.id,
        application_id=application.id,
        filename=path.name,
        file_path=str(path),
        sha256=content_hash,
        change_summary=summary,
        selected_skills=selected_skills,
    )
    session.add(version)
    session.add(AuditLog(
        action="resume_version_generated",
        entity_type="application",
        entity_id=str(application.id),
        details={"version_id": version_id, "sha256": content_hash},
    ))
    session.commit()
    return {
        "version_id": version_id,
        "application_id": application.id,
        "filename": version.filename,
        "download_url": f"/resume-versions/{version_id}/download",
        "selected_skills": selected_skills,
        "change_summary": summary,
        "source_resume_id": source_resume.id,
    }


@app.get("/resume-versions", dependencies=[Depends(require_token)])
def list_resume_versions(session: Session = Depends(get_session)) -> list[dict]:
    versions = session.scalars(select(ResumeVersion).order_by(ResumeVersion.created_at.desc())).all()
    return [
        {
            "version_id": version.version_id,
            "application_id": version.application_id,
            "source_resume_id": version.source_resume_id,
            "filename": version.filename,
            "sha256": version.sha256,
            "selected_skills": version.selected_skills,
            "change_summary": version.change_summary,
            "created_at": version.created_at.isoformat(),
            "download_url": f"/resume-versions/{version.version_id}/download",
        }
        for version in versions
    ]


@app.get("/resume-versions/{version_id}/download", dependencies=[Depends(require_token)])
def download_resume(version_id: str, session: Session = Depends(get_session)) -> FileResponse:
    version = session.scalar(select(ResumeVersion).where(ResumeVersion.version_id == version_id))
    if version is None:
        raise HTTPException(404, "Resume version not found.")
    allowed_dir = (settings.data_dir / "resume_versions").resolve()
    stored_path = Path(version.file_path).resolve()
    if stored_path.parent != allowed_dir or stored_path.name != version.filename:
        logger.error("Resume path validation failed for version_id=%s", version_id)
        raise HTTPException(500, "Stored resume path failed validation.")
    if not stored_path.is_file():
        raise HTTPException(410, "Generated resume file is no longer available.")
    return FileResponse(
        stored_path,
        media_type=version.content_type,
        filename=version.filename,
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(_, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled API error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "Internal error; see server log correlation."})


def _profile_dict(profile: CandidateProfile) -> dict:
    return {
        "id": profile.id, "name": profile.name, "location": profile.location, "summary": profile.summary,
        "target_tracks": profile.target_tracks, "skills": profile.skills, "employment_history": profile.employment_history,
        "education": profile.education, "projects": profile.projects, "preferences": profile.preferences,
    }


def _job_dict(job: Job) -> dict:
    return {
        "id": job.id, "title": job.title, "company": job.company, "location": job.location,
        "work_mode": job.work_mode, "url": job.canonical_url, "description": job.description,
        "active": job.active, "discovered_at": job.discovered_at.isoformat(),
        "match": {
            "ai_score": job.match.ai_score, "data_score": job.match.data_score,
            "eligibility": job.match.eligibility, "explanation": job.match.explanation,
        } if job.match else None,
    }
