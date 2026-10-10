from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from job_agent.config import settings
from job_agent.models import ApplicationAnswer
from job_agent.services import answer_bank
from job_agent.services.answer_bank import AnswerEncryptionUnavailable


def test_answers_are_encrypted_and_require_the_same_key(monkeypatch):
    key = "a-test-encryption-key-with-adequate-length"
    monkeypatch.setattr(
        answer_bank, "settings", replace(settings, answer_encryption_key=key),
    )
    encrypted = answer_bank.encrypt_answer("do-not-log-or-store-plaintext")
    assert encrypted != "do-not-log-or-store-plaintext"
    assert answer_bank.decrypt_answer(encrypted) == "do-not-log-or-store-plaintext"

    monkeypatch.setattr(
        answer_bank,
        "settings",
        replace(
            settings,
            answer_encryption_key="a-different-encryption-key-with-adequate-length",
        ),
    )
    with pytest.raises(AnswerEncryptionUnavailable, match="confirm the configured key"):
        answer_bank.decrypt_answer(encrypted)


def test_missing_expired_unverified_and_sensitive_answers_block_readiness():
    now = datetime.now(timezone.utc)
    answers = [
        ApplicationAnswer(
            field_key="notice_period",
            encrypted_value="ciphertext",
            verification_status="verified",
        ),
        ApplicationAnswer(
            field_key="expected_salary",
            encrypted_value="ciphertext",
            verification_status="verified",
            sensitive=True,
        ),
        ApplicationAnswer(
            field_key="work_authorization",
            encrypted_value="ciphertext",
            verification_status="verified",
            expires_at=now - timedelta(days=1),
        ),
        ApplicationAnswer(
            field_key="availability",
            encrypted_value="ciphertext",
            verification_status="unverified",
        ),
    ]
    result = answer_bank.check_required_answers(
        answers,
        [
            "notice_period",
            "expected_salary",
            "work_authorization",
            "availability",
            "education",
        ],
        now=now,
    )
    assert result["ready"] is False
    assert result["missing"] == ["education"]
    assert result["expired"] == ["work_authorization"]
    assert result["unverified"] == ["availability"]
    assert result["manual_review_required"] == ["expected_salary"]


def test_encryption_key_must_be_configured(monkeypatch):
    monkeypatch.setattr(
        answer_bank, "settings", replace(settings, answer_encryption_key=""),
    )
    with pytest.raises(AnswerEncryptionUnavailable, match="ANSWER_ENCRYPTION_KEY"):
        answer_bank.encrypt_answer("value")
