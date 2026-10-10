from hashlib import sha256
from io import BytesIO

import pytest
from docx import Document

from job_agent.models import Application, CandidateProfile, Job, JobMatch, Resume
from job_agent.services.applications import transition
from job_agent.services.resumes import audit_resume, extract_resume
from job_agent.services.tailoring import generate_ats_docx


def test_resume_audit_uses_text_only_findings():
    audit = audit_resume("Experience\nEducation\nSkills\nProjects\nEmail: sunil@example.org Python SQL", ["Python", "SQL", "Azure"], "AI engineer")
    assert audit["readiness_score"] > 0
    assert audit["skills_found"] == ["Python", "SQL"]
    assert audit["skills_not_found"] == ["Azure"]
    assert audit["limitations"]


def test_unsupported_resume_extension_rejected():
    with pytest.raises(ValueError, match="PDF and DOCX"):
        extract_resume("resume.txt", b"not a supported resume")


def test_application_approval_gates_submission_and_confirmation():
    application = Application(status="PENDING_APPROVAL")
    with pytest.raises(ValueError, match="Invalid application transition"):
        transition(application, "SUBMITTED")
    transition(application, "APPROVED")
    transition(application, "SUBMITTED")
    with pytest.raises(ValueError, match="confirmation evidence"):
        transition(application, "CONFIRMED")
    transition(application, "CONFIRMED", "portal-reference-123")
    assert application.confirmation_reference == "portal-reference-123"


def test_generated_resume_preserves_source_and_only_surfaces_evidenced_skills(tmp_path, monkeypatch):
    from dataclasses import replace

    from job_agent.services import tailoring
    from job_agent.config import settings

    monkeypatch.setattr(tailoring, "settings", replace(settings, data_dir=tmp_path))
    source_text = (
        "Sunil Javadi\n"
        "Experience\n"
        "Built Python and RAG applications for internal users.\n"
        "Worked with SQL Server."
    )
    profile = CandidateProfile(skills=["Python", "RAG", "Azure"])
    job = Job(
        title="RAG Engineer",
        description="Develop Python and RAG applications.",
        required_skills=["Python", "RAG", "Azure"],
    )
    application = Application(id=17, job=job)
    source = Resume(id=4, filename="source.pdf", text=source_text, sha256="source")

    _, path, checksum, selected, summary = generate_ats_docx(profile, source, application)
    generated = Document(BytesIO(path.read_bytes()))
    paragraphs = [paragraph.text for paragraph in generated.paragraphs]
    rendered_text = "\n".join(paragraphs)

    assert selected == ["Python", "RAG"]
    assert source.text == source_text
    for source_line in source_text.splitlines():
        assert source_line in rendered_text
    assert "Azure" not in paragraphs[1]
    assert checksum == sha256(path.read_bytes()).hexdigest()
    assert path.suffix == ".docx"
    assert "not rewritten" in summary
