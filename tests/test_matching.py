from job_agent.models import CandidateProfile, Job
from job_agent.services.matching import score_job


def test_match_explains_supported_skills_and_missing_requirements():
    profile = CandidateProfile(
        skills=["Python", "SQL", "RAG"],
        target_tracks=["AI/GenAI"],
        projects=[{"name": "RAG assistant", "skills": ["RAG", "Python"]}],
        preferences={"years_experience": 6, "locations": ["Hyderabad"], "remote_in_india": True},
    )
    job = Job(
        title="GenAI Engineer", description="Build RAG applications",
        location="Hyderabad", required_skills=["Python", "RAG", "Kubernetes"],
        min_experience_years=5,
    )
    result = score_job(profile, job)
    assert result["matched_skills"] == ["python", "rag"]
    assert result["missing_skills"] == ["kubernetes"]
    assert result["matching_tracks"] == ["AI/GenAI"]
    assert result["eligibility"] == "ELIGIBLE"
    assert result["components"]["compensation"] is None
    assert 0 <= result["score"] <= 100


def test_substantially_excessive_experience_is_hard_rejected():
    result = score_job(
        CandidateProfile(skills=["SQL"], target_tracks=["Data Engineering/BI"], preferences={"years_experience": 6}),
        Job(title="Lead Data Engineer", description="SQL ETL", required_skills=["SQL"], min_experience_years=15),
    )
    assert result["eligibility"] == "REJECTED_BY_RULES"
    assert result["hard_reasons"]


def test_missing_dimensions_are_normalized_out():
    result = score_job(CandidateProfile(skills=["Python"]), Job(title="Python Engineer", required_skills=["Python"]))
    assert result["score"] == 100
    assert "compensation" in result["missing_information"]
