from job_agent.models import CandidateProfile, Resume
from job_agent.services.resumes import audit_resume


def profile_audit(profile: CandidateProfile, resume: Resume | None) -> dict:
    if resume is None:
        return {
            "readiness_score": 0,
            "ai_readiness_score": 0,
            "data_readiness_score": 0,
            "findings": ["Upload a resume to run evidence-backed parsing checks."],
            "limitations": ["No resume has been uploaded."],
        }
    audit = audit_resume(resume.text, profile.skills, profile.summary)
    return {
        **audit,
        "ai_readiness_score": audit["readiness_score"],
        "data_readiness_score": audit["readiness_score"],
        "limitations": audit["limitations"] + [
            "Track-specific scoring is unavailable until candidate experience and project evidence are entered separately."
        ],
    }
