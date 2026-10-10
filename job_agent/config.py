import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./job_agent.db")
    api_token: str = os.getenv("JOB_AGENT_API_TOKEN", "")
    answer_encryption_key: str = os.getenv("ANSWER_ENCRYPTION_KEY", "")
    data_dir: Path = Path(os.getenv("JOB_AGENT_DATA_DIR", "./data"))
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", str(8 * 1024 * 1024)))
    scheduler_timezone: str = os.getenv("SCHEDULER_TIMEZONE", "Asia/Kolkata")
    scheduler_hour: int = int(os.getenv("SCHEDULER_HOUR", "8"))
    scheduler_minute: int = int(os.getenv("SCHEDULER_MINUTE", "0"))
    daily_application_limit: int = int(os.getenv("DAILY_APPLICATION_LIMIT", "5"))


settings = Settings()
