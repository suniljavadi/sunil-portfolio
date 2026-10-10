import base64
import hashlib
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken

from job_agent.config import settings
from job_agent.models import ApplicationAnswer

MANUAL_REVIEW_FIELDS = {
    "work_authorization",
    "visa_status",
    "disability_declaration",
    "criminal_history_declaration",
    "background_check_consent",
    "salary_expectation",
    "current_compensation",
}


class AnswerEncryptionUnavailable(RuntimeError):
    pass


def _cipher() -> Fernet:
    key_material = settings.answer_encryption_key.encode("utf-8")
    if len(key_material) < 32:
        raise AnswerEncryptionUnavailable(
            "Set ANSWER_ENCRYPTION_KEY to a stable random value of at least 32 characters."
        )
    key = base64.urlsafe_b64encode(hashlib.sha256(key_material).digest())
    return Fernet(key)


def encrypt_answer(value: str) -> str:
    return _cipher().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_answer(value: str) -> str:
    try:
        return _cipher().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise AnswerEncryptionUnavailable(
            "Unable to decrypt the answer; confirm the configured key matches the key used to store it."
        ) from exc


def effective_status(answer: ApplicationAnswer, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    expires_at = answer.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            return "expired"
    return answer.verification_status


def check_required_answers(
    answers: list[ApplicationAnswer],
    required_fields: list[str],
    now: datetime | None = None,
) -> dict:
    by_key = {answer.field_key: answer for answer in answers}
    missing = []
    expired = []
    unverified = []
    manual_review = []
    for field in required_fields:
        answer = by_key.get(field)
        if answer is None:
            missing.append(field)
            continue
        if effective_status(answer, now) == "expired":
            expired.append(field)
            continue
        if answer.verification_status != "verified":
            unverified.append(field)
        if answer.sensitive or field.lower() in MANUAL_REVIEW_FIELDS:
            manual_review.append(field)
    return {
        "ready": not (missing or expired or unverified or manual_review),
        "missing": missing,
        "expired": expired,
        "unverified": unverified,
        "manual_review_required": manual_review,
        "limitations": [
            "This check validates answer-bank status only; it does not establish legal eligibility or submit answers."
        ],
    }
