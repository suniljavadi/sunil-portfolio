from collections.abc import Generator
from dataclasses import replace
from hashlib import sha256
from io import BytesIO

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from docx import Document

from job_agent import api
from job_agent.db import Base, get_session
from job_agent.models import Application, ApplicationAnswer, AuditLog, Resume
from job_agent.services import answer_bank, tailoring
from job_agent.services.discovery import BoardError, DiscoveredJob, GreenhouseAdapter


def test_review_first_discovery_deduplicates_and_requires_approval(monkeypatch, tmp_path):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    test_sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_session() -> Generator[Session, None, None]:
        with test_sessions() as session:
            yield session

    monkeypatch.setattr(
        api,
        "settings",
        replace(
            api.settings,
            api_token="test-token",
            answer_encryption_key="test-answer-encryption-key-with-enough-entropy",
            data_dir=tmp_path,
        ),
    )
    monkeypatch.setattr(answer_bank, "settings", api.settings)
    monkeypatch.setattr(tailoring, "settings", api.settings)
    fetch_calls = []
    flaky_fetches = 0

    def fetch_board(self, board):
        nonlocal flaky_fetches
        fetch_calls.append(board)
        if board == "flaky" and flaky_fetches < 2:
            flaky_fetches += 1
            raise BoardError("temporary provider error")
        if board == "flaky":
            return []
        return [
            DiscoveredJob(
                external_id="42",
                url="https://jobs.example.org/roles/42?source=board",
                title="GenAI Engineer",
                company="Example",
                location="Hyderabad",
                description="Build Python RAG systems",
            )
        ]

    monkeypatch.setattr(GreenhouseAdapter, "fetch", fetch_board)
    api.app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(api.app) as client:
            assert client.get("/profile").status_code == 401
            headers = {"Authorization": "Bearer test-token"}
            profile = {
                "name": "Sunil Javadi",
                "location": "Hyderabad, Telangana, India",
                "summary": "AI engineer",
                "target_tracks": ["AI/GenAI"],
                "skills": ["Python", "RAG"],
                "employment_history": [],
                "education": [],
                "projects": [{"name": "RAG", "skills": ["Python", "RAG"]}],
                "preferences": {"years_experience": 6, "locations": ["Hyderabad"]},
            }
            assert client.put("/profile", headers=headers, json=profile).status_code == 200
            assert client.post(
                "/sources", headers=headers,
                json={"provider": "greenhouse", "board_token": "example"},
            ).status_code == 200
            flaky_source = client.post(
                "/sources", headers=headers,
                json={"provider": "greenhouse", "board_token": "flaky"},
            ).json()

            default_scheduler = client.get("/scheduler", headers=headers)
            assert default_scheduler.status_code == 200
            assert default_scheduler.json()["enabled"] is True
            assert default_scheduler.json()["worker_status"] == "not_seen_or_stale"
            scheduler_update = client.put(
                "/scheduler",
                headers=headers,
                json={
                    "enabled": False,
                    "hour": 9,
                    "minute": 15,
                    "timezone": "Asia/Kolkata",
                    "daily_application_limit": 3,
                },
            )
            assert scheduler_update.status_code == 200
            assert scheduler_update.json()["enabled"] is False
            assert scheduler_update.json()["hour"] == 9
            assert client.put(
                "/scheduler",
                headers=headers,
                json={
                    "enabled": True,
                    "hour": 8,
                    "minute": 0,
                    "timezone": "Not/AZone",
                    "daily_application_limit": 5,
                },
            ).status_code == 422

            first = client.post("/discovery/run", headers=headers)
            second = client.post("/discovery/run", headers=headers)
            assert first.json()["summary"]["new_jobs"] == 1
            assert second.json()["summary"]["new_jobs"] == 0
            assert second.json()["status"] == "PARTIAL"
            assert second.json()["summary"]["source_failures"][0]["source_id"] == flaky_source["id"]
            calls_before_retry = len(fetch_calls)
            retry = client.post(
                f"/scheduled-runs/{second.json()['id']}/retry",
                headers=headers,
            )
            assert retry.status_code == 200
            assert retry.json()["status"] == "COMPLETED"
            assert retry.json()["retry_of_id"] == second.json()["id"]
            assert fetch_calls[calls_before_retry:] == ["flaky"]
            assert client.post(
                f"/scheduled-runs/{retry.json()['id']}/retry",
                headers=headers,
            ).status_code == 409
            assert client.post(
                "/scheduled-runs/99999/retry",
                headers=headers,
            ).status_code == 404
            applications = client.get("/applications", headers=headers).json()
            assert len(applications) == 1
            assert applications[0]["status"] == "PENDING_APPROVAL"
            application_id = applications[0]["id"]

            missing = client.post(
                f"/applications/{application_id}/answer-check",
                headers=headers,
                json={"required_fields": ["notice_period", "work_authorization"]},
            )
            assert missing.json()["ready"] is False
            assert missing.json()["missing"] == ["notice_period", "work_authorization"]
            missing_approval = client.post(
                f"/applications/{application_id}/approve",
                headers=headers,
                json={
                    "required_fields": ["notice_period", "work_authorization"],
                    "answers_reviewed": True,
                },
            )
            assert missing_approval.status_code == 409
            assert missing_approval.json()["detail"]["missing"] == [
                "notice_period", "work_authorization",
            ]

            saved = client.put(
                "/answer-bank/notice-period",
                headers=headers,
                json={
                    "value": "30 days",
                    "verification_status": "verified",
                    "sensitive": False,
                },
            )
            assert saved.status_code == 200
            with test_sessions() as session:
                stored_answer = session.scalar(
                    select(ApplicationAnswer).where(ApplicationAnswer.field_key == "notice_period")
                )
                assert stored_answer.encrypted_value != "30 days"
            answers = client.get("/answer-bank", headers=headers)
            assert answers.json()[0]["value"] == "30 days"
            assert answers.json()[0]["verification_status"] == "verified"
            ready_check = client.post(
                f"/applications/{application_id}/answer-check",
                headers=headers,
                json={"required_fields": ["notice-period"]},
            )
            assert ready_check.json()["ready"] is True

            client.put(
                "/answer-bank/work-authorization",
                headers=headers,
                json={
                    "value": "citizenship details",
                    "verification_status": "verified",
                    "sensitive": True,
                },
            )
            sensitive_check = client.post(
                f"/applications/{application_id}/answer-check",
                headers=headers,
                json={"required_fields": ["work_authorization"]},
            )
            assert sensitive_check.json()["ready"] is False
            assert sensitive_check.json()["manual_review_required"] == ["work_authorization"]
            sensitive_value = next(
                answer for answer in client.get("/answer-bank", headers=headers).json()
                if answer["field_key"] == "work_authorization"
            )
            assert sensitive_value["value"] is None
            assert client.post(
                f"/applications/{application_id}/approve",
                headers=headers,
                json={
                    "required_fields": ["notice_period", "work_authorization"],
                    "answers_reviewed": True,
                },
            ).status_code == 409

            source_text = "Sunil Javadi\nExperience\nPython RAG SQL engineer"
            with test_sessions() as session:
                session.add(Resume(
                    filename="source.pdf",
                    content_type="application/pdf",
                    sha256=sha256(source_text.encode()).hexdigest(),
                    text=source_text,
                ))
                session.commit()

            generated = client.post(
                f"/applications/{applications[0]['id']}/resume", headers=headers,
            )
            assert generated.status_code == 200
            assert generated.json()["selected_skills"] == ["Python", "RAG"]
            downloaded = client.get(generated.json()["download_url"], headers=headers)
            assert downloaded.status_code == 200
            document = Document(BytesIO(downloaded.content))
            document_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
            assert "Sunil Javadi" in document_text
            assert "Python RAG SQL engineer" in document_text
            assert len(client.get("/resume-versions", headers=headers).json()) == 1
            runs = client.get("/scheduled-runs", headers=headers)
            assert runs.status_code == 200
            assert len(runs.json()) == 3
            assert next(run for run in runs.json() if run["id"] == retry.json()["id"])["retry_of_id"] == second.json()["id"]
            task_errors = client.get("/task-executions", headers=headers).json()
            assert len(task_errors) == 2
            assert all(task["status"] == "FAILED" for task in task_errors)

            approved = client.post(
                f"/applications/{applications[0]['id']}/approve",
                headers=headers,
                json={
                    "required_fields": ["notice_period", "work_authorization"],
                    "answers_reviewed": True,
                    "manual_review_acknowledged": True,
                },
            )
            assert approved.json()["status"] == "APPROVED"
            assert approved.json()["submission"] == "manual portal action required"
            assert approved.json()["manual_review_fields"] == ["work_authorization"]
            with test_sessions() as session:
                stored_application = session.get(Application, application_id)
                assert stored_application.answers["required_fields"] == [
                    "notice_period", "work_authorization",
                ]
                audit_entry = session.scalar(
                    select(AuditLog).where(AuditLog.action == "application_approved")
                )
                assert "citizenship details" not in str(audit_entry.details)
    finally:
        api.app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
        engine.dispose()
