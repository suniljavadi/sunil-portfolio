from uuid import uuid4

TRANSITIONS = {
    "DISCOVERED": {"SCORED", "DUPLICATE", "EXPIRED"},
    "SCORED": {"ELIGIBILITY_CHECKED", "REJECTED_BY_RULES", "EXPIRED"},
    "ELIGIBILITY_CHECKED": {"RESUME_READY", "NEEDS_MANUAL_ACTION", "REJECTED_BY_RULES", "EXPIRED"},
    "RESUME_READY": {"PENDING_APPROVAL", "NEEDS_MANUAL_ACTION"},
    "PENDING_APPROVAL": {"APPROVED", "WITHDRAWN", "NEEDS_MANUAL_ACTION"},
    "APPROVED": {"SUBMITTED", "FAILED", "NEEDS_MANUAL_ACTION"},
    "SUBMITTED": {"CONFIRMED", "FAILED", "NEEDS_MANUAL_ACTION"},
    "FAILED": {"NEEDS_MANUAL_ACTION"},
    "CONFIRMED": {"WITHDRAWN"},
    "NEEDS_MANUAL_ACTION": {"PENDING_APPROVAL", "WITHDRAWN", "FAILED"},
    "DUPLICATE": set(),
    "REJECTED_BY_RULES": set(),
    "EXPIRED": set(),
    "WITHDRAWN": set(),
}


def transition(application, target: str, confirmation_reference: str | None = None) -> None:
    if target not in TRANSITIONS.get(application.status, set()):
        raise ValueError(f"Invalid application transition: {application.status} -> {target}")
    if target == "SUBMITTED" and application.status != "APPROVED":
        raise ValueError("An application must be explicitly approved before submission.")
    if target == "CONFIRMED" and not confirmation_reference:
        raise ValueError("Portal confirmation evidence is required to mark an application confirmed.")
    application.status = target
    if target == "CONFIRMED":
        application.confirmation_reference = confirmation_reference


def make_idempotency_key(job_id: int) -> str:
    return f"job-{job_id}-{uuid4().hex}"
