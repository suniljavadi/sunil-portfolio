import hashlib
from pathlib import Path

from docx import Document
from pypdf import PdfReader


def extract_resume(filename: str, content: bytes) -> tuple[str, str]:
    extension = Path(filename).suffix.lower()
    if extension == ".pdf":
        import io

        reader = PdfReader(io.BytesIO(content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        content_type = "application/pdf"
    elif extension == ".docx":
        import io

        document = Document(io.BytesIO(content))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        raise ValueError("Only PDF and DOCX resumes are supported.")
    if not text.strip():
        raise ValueError("No text could be extracted; scanned PDFs require OCR, which is not configured.")
    return text, content_type


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def audit_resume(text: str, profile_skills: list[str], profile_summary: str) -> dict:
    lowered = text.lower()
    sections = {
        "experience": any(word in lowered for word in ("experience", "employment", "professional history")),
        "education": "education" in lowered,
        "skills": "skills" in lowered or "technical stack" in lowered,
        "projects": "project" in lowered,
        "contact": "@" in text or "linkedin.com" in lowered or "github.com" in lowered,
    }
    skills_present = sorted(skill for skill in profile_skills if skill.lower() in lowered)
    skills_missing = sorted(skill for skill in profile_skills if skill.lower() not in lowered)
    vague_claims = [
        phrase for phrase in ("expert in", "world-class", "best-in-class", "significantly improved")
        if phrase in lowered
    ]
    score = round(100 * (sum(sections.values()) / len(sections)) * 0.6 + (
        40 * len(skills_present) / len(profile_skills) if profile_skills else 0
    ))
    findings = [
        f"Missing recognizable {section} section." for section, found in sections.items() if not found
    ]
    if skills_missing:
        findings.append("Profile-listed skills not found in resume: " + ", ".join(skills_missing))
    if vague_claims:
        findings.append("Review broad or unsubstantiated phrases: " + ", ".join(vague_claims))
    if profile_summary and profile_summary.lower() not in lowered:
        findings.append("Profile summary is not present verbatim; verify role positioning is consistent.")
    return {
        "readiness_score": min(100, score),
        "section_checks": sections,
        "skills_found": skills_present,
        "skills_not_found": skills_missing,
        "potentially_unsupported_phrases": vague_claims,
        "findings": findings,
        "limitations": ["Heuristic text-only checks; no proprietary ATS score, OCR, date reconciliation, or claim verification."],
    }
