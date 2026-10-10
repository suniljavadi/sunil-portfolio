import re
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx


@dataclass
class DiscoveredJob:
    external_id: str
    url: str
    title: str
    company: str
    location: str
    description: str
    work_mode: str | None = None


class BoardError(RuntimeError):
    pass


class GreenhouseAdapter:
    """Reads public Greenhouse job-board endpoints; does not submit applications."""

    provider = "greenhouse"

    def fetch(self, board_token: str) -> list[DiscoveredJob]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
        try:
            response = httpx.get(url, timeout=15, follow_redirects=True)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BoardError(f"Greenhouse board fetch failed: {exc}") from exc
        return [
            DiscoveredJob(
                external_id=str(item["id"]),
                url=item["absolute_url"],
                title=item["title"],
                company=board_token,
                location=(item.get("location") or {}).get("name", ""),
                description=_strip_html(item.get("content", "")),
            )
            for item in data.get("jobs", [])
            if item.get("id") and item.get("absolute_url") and item.get("title")
        ]


class LeverAdapter:
    """Reads public Lever postings; does not submit applications."""

    provider = "lever"

    def fetch(self, site: str) -> list[DiscoveredJob]:
        url = f"https://api.lever.co/v0/postings/{site}?mode=json"
        try:
            response = httpx.get(url, timeout=15, follow_redirects=True)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BoardError(f"Lever board fetch failed: {exc}") from exc
        result = []
        for item in data if isinstance(data, list) else []:
            categories = item.get("categories") or {}
            result.append(DiscoveredJob(
                external_id=str(item.get("id", "")),
                url=item.get("hostedUrl", ""),
                title=item.get("text", ""),
                company=site,
                location=categories.get("location", ""),
                description=_strip_html(item.get("descriptionPlain", "")),
                work_mode=categories.get("commitment"),
            ))
        return [item for item in result if item.external_id and item.url and item.title]


def _strip_html(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", value)).strip()


def canonicalize(url: str) -> str:
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url.strip())
    if parts.scheme not in {"https", "http"} or not parts.hostname:
        raise ValueError("Job URL must be an absolute HTTP(S) URL.")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def as_utc(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value
