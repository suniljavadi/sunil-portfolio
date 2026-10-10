# Job Agent (review-first)

This service sits beside the static portfolio; it does not alter the GitHub Pages frontend. It is a first implementation slice for private, persistent job discovery and application review. No job application is submitted automatically.

## Architecture and data flow

`Greenhouse/Lever public board API -> provider adapter -> canonical URL de-duplication -> SQLite/PostgreSQL -> deterministic explainable match -> source-preserving ATS DOCX preparation -> pending approval -> candidate opens original listing and applies manually.`

FastAPI is the authenticated API, Streamlit is an API client, and a separate APScheduler process performs the configured daily discovery. The default is 08:00 Asia/Kolkata. Scheduler enablement, daily time, timezone, daily application limit, worker heartbeat, run history, and task failures are persisted. The dashboard can pause/resume the daily job and change its schedule; the worker syncs changed settings within 30 seconds. Operate exactly one scheduler worker process per database. The daily application limit is stored as a preference; no application submission is currently automated.

Manual and scheduled discovery runs are recorded independently. A failed or partial run can be retried from the dashboard; when source failures are known, the retry is scoped to those enabled sources and linked to its original run. Retries preserve the original run and remain idempotent through canonical job URL de-duplication. A whole-run failure without source-level details retries discovery across enabled sources.

## Local setup

Requires Python 3.12+ and network access for dependency install/public boards.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Set JOB_AGENT_API_TOKEN and a distinct, stable ANSWER_ENCRYPTION_KEY.
# Generate a key locally with: python -c "import secrets; print(secrets.token_urlsafe(48))"
alembic upgrade head
uvicorn job_agent.api:app --reload
```

In another terminal, activate the same environment and run `streamlit run dashboard.py`. For daily persistence outside the dashboard, run `python -m job_agent.worker` in a separate always-on process. Configure the same database URL and token for all services. `/health` is an unauthenticated liveness check; other API routes require `Authorization: Bearer <JOB_AGENT_API_TOKEN>`.

## Sources and limits

Add only public company board identifiers: Greenhouse board token or Lever site name, plus the company display name (the default is explicitly “Unknown company”). Both adapters use their public job listing endpoints, have request timeouts, and never authenticate or submit. No LinkedIn, Naukri, Indeed, or other portal automation is implemented. Configure those sources only through an authorized integration they provide; otherwise use their listing links manually. Public source endpoints can change and may have provider-specific usage rules; check those terms before production use.

The matching engine records inputs, component weights, matched/missing skills, missing dimensions, and hard eligibility rules. It uses only candidate-entered skills/projects and does not use an LLM. Missing factors are excluded and remaining weights renormalized. Scores are heuristics, not hiring probability.

Resume uploads accept PDF and DOCX, enforce an 8 MiB default cap, hash for duplicate detection, and retain extracted text as the immutable source. No OCR is enabled; scanned documents are rejected. Audit findings are transparent text heuristics, not a proprietary ATS score or verification of employment claims.

For an eligible job, the candidate can prepare an ATS-friendly DOCX from the latest uploaded source resume. The renderer preserves the extracted source wording and adds a small “Relevant Skills” heading only for skills present in the entered candidate skill list, the resume, and the job text. Each output has a UUID, SHA-256, source-resume link, application link, timestamp, and change summary. The original upload is unchanged. No rewording, PDF conversion, or automated fact inference is performed. Review each generated file before use.

The answer bank stores each value as Fernet authenticated ciphertext using a SHA-256-derived key from `ANSWER_ENCRYPTION_KEY` (at least 32 characters). This environment secret must be random, kept separate from the API token, identical across API replicas, and backed up securely. Losing or changing it makes saved answers unrecoverable. Answer values are not written to audit logs, and fields marked sensitive are not returned by the API after storage. Set an answer to `verified` only after checking it; optional expiry is enforced by readiness checks. Sensitive fields and known legal/work-authorization/compensation declarations always require manual review.

Application approval now requires an explicit review acknowledgement, the required answer field keys, and verified, unexpired answer-bank entries for each required key. If any answer is missing, expired, or unverified, approval is blocked. Known sensitive/declaration keys require an additional candidate acknowledgement that they have been reviewed manually. The approval endpoint stores only field keys and review metadata, never answer values. This does not establish legal eligibility or submit an application. Use HTTPS for any non-local network.

## Application safety

Only matches with score >=70 and no configured hard-reject rule are prepared for approval. Approving moves to `APPROVED` but does not submit. Submission requires a separately authorized portal workflow, not yet integrated. `SUBMITTED` and `CONFIRMED` are not exposed as UI actions; confirmation requires evidence in the application service. Do not store portal passwords or cookies. Do not expose the dashboard/API directly to the public internet without TLS and a proper identity/access proxy.

## PostgreSQL deployment

Copy `.env.example` to `.env`; set unique random secrets and PostgreSQL credentials. `docker compose up --build -d` starts the database, API, dashboard, and independent scheduler. The default compose setup uses persistent Postgres volume storage. Store backups outside the host:

```sh
docker compose exec -T db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > jobagent-backup.sql
cat jobagent-backup.sql | docker compose exec -T db psql -U "$POSTGRES_USER" "$POSTGRES_DB"
```

Before upgrading, back up the database. Run `docker compose exec api alembic upgrade head` for schema upgrades. Persistent storage, background scheduler execution, protected secrets, and TLS are deployment requirements; the host must remain running and may incur infrastructure costs.

## Current gaps

- Candidate-entered profile evidence; no automated GitHub/LinkedIn/job-portal profile inspection.
- Answer-bank values are encrypted at rest, but the rest of the profile and extracted resume text are not; do not treat the database as fully encrypted.
- Resume generation currently performs source-preserving DOCX formatting and relevant-skill selection only; no rewriting, cover letter generation, PDF export, or OCR.
- No notification delivery, analytics exports, rate limiting, alerting, or portal submission integration.
- Scheduler pause/resume, schedule settings, worker heartbeat, run history, source failure details, and retry links are available; retrying is candidate-triggered rather than automatic, and full observability remains future work.
- Manual board source configuration is required. External board integrations have not been live-verified here.

Run the automated suite with `pytest -q`. Tests mock no real application submission and do not contact job boards.
