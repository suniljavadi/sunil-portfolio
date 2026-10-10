import re
from typing import Any

from job_agent.models import CandidateProfile, Job

WEIGHTS = {
    "skills": 25,
    "responsibilities": 20,
    "seniority": 15,
    "track": 15,
    "location": 10,
    "projects": 10,
    "compensation": 5,
}
TRACK_TERMS = {
    "AI/GenAI": ("ai", "genai", "llm", "rag", "agent", "machine learning"),
    "Data Engineering/BI": ("data engineer", "sql", "ssis", "ssrs", "etl", "power bi", "bi developer"),
}


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9+#. ]", " ", value.lower()).strip()


def score_job(profile: CandidateProfile, job: Job) -> dict[str, Any]:
    """Score against explicitly supplied profile evidence; omit unavailable dimensions."""
    profile_skills = {_normalize(item) for item in (profile.skills or []) if item.strip()}
    project_text = " ".join(
        f"{p.get('name', '')} {p.get('description', '')} {' '.join(p.get('skills') or [])}"
        for p in (profile.projects or [])
    ).lower()
    description = (
        f"{job.title or ''} {job.description or ''} "
        f"{' '.join(job.required_skills or [])} {' '.join(job.preferred_skills or [])}"
    )
    description_terms = _normalize(description)
    required = {_normalize(skill) for skill in (job.required_skills or []) if skill.strip()}
    if not required:
        required = {skill for skill in profile_skills if skill in description_terms}

    components: dict[str, float | None] = {}
    matched = sorted(skill for skill in required if skill in profile_skills)
    missing = sorted(required - profile_skills)
    components["skills"] = (len(matched) / len(required) * 100) if required else None
    components["responsibilities"] = None

    prefs = profile.preferences or {}
    experience = prefs.get("years_experience")
    if experience is not None and job.min_experience_years is not None:
        components["seniority"] = max(0, min(100, 100 - max(0, job.min_experience_years - int(experience)) * 20))
    else:
        components["seniority"] = None

    target_tracks = profile.target_tracks or []
    matching_tracks = [
        track for track, terms in TRACK_TERMS.items()
        if any(term in description_terms for term in terms) and (not target_tracks or track in target_tracks)
    ]
    components["track"] = 100.0 if matching_tracks else (None if not target_tracks else 0.0)

    location_terms = [str(v).lower() for v in prefs.get("locations", [profile.location]) if v]
    if job.location or job.work_mode:
        location_text = f"{job.location} {job.work_mode or ''}".lower()
        components["location"] = 100.0 if any(term in location_text for term in location_terms) or (
            prefs.get("remote_in_india", True) and "remote" in location_text and "india" in location_text
        ) else 0.0
    else:
        components["location"] = None

    components["projects"] = (
        100 * sum(1 for skill in required if skill and skill in project_text) / len(required)
        if required and project_text else None
    )
    expected = prefs.get("expected_salary")
    if expected is not None and (job.salary_min is not None or job.salary_max is not None):
        ceiling = job.salary_max if job.salary_max is not None else job.salary_min
        components["compensation"] = 100.0 if expected <= ceiling else 0.0
    else:
        components["compensation"] = None

    available = [(name, value, WEIGHTS[name]) for name, value in components.items() if value is not None]
    denominator = sum(weight for _, _, weight in available)
    score = round(sum(float(value) * weight for _, value, weight in available) / denominator, 1) if denominator else 0.0
    hard_reasons = []
    if experience is not None and job.min_experience_years is not None and job.min_experience_years > int(experience) + 5:
        hard_reasons.append("Minimum experience requirement is substantially above the candidate's recorded experience.")
    status = "REJECTED_BY_RULES" if hard_reasons else (
        "ELIGIBLE" if score >= 70 else "REVIEW" if score >= 55 else "LOW_MATCH"
    )
    return {
        "score": score,
        "components": components,
        "weights": WEIGHTS,
        "matched_skills": matched,
        "missing_skills": missing,
        "matching_tracks": matching_tracks,
        "hard_reasons": hard_reasons,
        "eligibility": status,
        "missing_information": [name for name, value in components.items() if value is None],
        "band": "Excellent" if score >= 85 else "Strong" if score >= 70 else "Review" if score >= 55 else "Low",
    }
