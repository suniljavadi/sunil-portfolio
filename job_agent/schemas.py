from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class CandidateProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    location: str = Field(min_length=1, max_length=160)
    summary: str = ""
    target_tracks: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    employment_history: list[dict[str, Any]] = Field(default_factory=list)
    education: list[dict[str, Any]] = Field(default_factory=list)
    projects: list[dict[str, Any]] = Field(default_factory=list)
    preferences: dict[str, Any] = Field(default_factory=dict)


class SourceIn(BaseModel):
    provider: str
    board_token: str = Field(min_length=1, max_length=160)
    company_name: str = Field(default="Unknown company", min_length=1, max_length=250)


class JobInput(BaseModel):
    title: str = Field(min_length=1)
    company: str = Field(min_length=1)
    url: HttpUrl
    description: str = ""
    location: str = ""
    work_mode: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    min_experience_years: int | None = Field(default=None, ge=0, le=60)
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)


class ApplicationAnswerIn(BaseModel):
    value: str = Field(min_length=1, max_length=10_000)
    verification_status: Literal["verified", "unverified"] = "unverified"
    expires_at: datetime | None = None
    sensitive: bool = False


class AnswerCheckIn(BaseModel):
    required_fields: list[str] = Field(min_length=1, max_length=100)


class ApplicationApprovalIn(BaseModel):
    required_fields: list[str] = Field(default_factory=list, max_length=100)
    answers_reviewed: bool = False
    manual_review_acknowledged: bool = False


class SchedulerControlIn(BaseModel):
    enabled: bool
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    timezone: str = Field(min_length=1, max_length=80)
    daily_application_limit: int = Field(ge=0, le=100)
