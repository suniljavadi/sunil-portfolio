import os
from datetime import time

import requests
import streamlit as st

st.set_page_config(page_title="Job Agent", page_icon="🧭", layout="wide")
st.title("Sunil Javadi · Job Search Agent")
st.caption("Review-first workspace. Job descriptions and portal content are untrusted data.")

api_url = os.getenv("JOB_AGENT_API_URL", "http://localhost:8000").rstrip("/")
token = st.text_input("API bearer token", type="password")
headers = {"Authorization": f"Bearer {token}"} if token else {}
if not token:
    st.info("Enter JOB_AGENT_API_TOKEN to access the private API.")
    st.stop()

page = st.sidebar.radio(
    "Workspace",
    [
        "Overview",
        "Candidate profile",
        "Profile audit",
        "Job discovery",
        "Applications",
        "Resume versions",
        "Answer bank",
        "Scheduler and logs",
    ],
)

def api(method, endpoint, **kwargs):
    try:
        response = requests.request(method, f"{api_url}{endpoint}", headers=headers, timeout=20, **kwargs)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        st.error(f"API request failed: {exc}")
        return None

if page == "Overview":
    jobs = api("GET", "/jobs") or []
    apps = api("GET", "/applications") or []
    cols = st.columns(3)
    cols[0].metric("Jobs discovered", len(jobs))
    cols[1].metric("Awaiting approval", sum(app["status"] == "PENDING_APPROVAL" for app in apps))
    cols[2].metric("Confirmed submissions", sum(app["status"] == "CONFIRMED" for app in apps))
    st.caption("A job is never reported as submitted or confirmed based on preparation alone.")
elif page == "Candidate profile":
    profile = api("GET", "/profile")
    if profile:
        with st.form("profile"):
            name = st.text_input("Name", profile["name"])
            location = st.text_input("Location", profile["location"])
            summary = st.text_area("Professional summary", profile["summary"])
            skills = st.text_area("Skills (one per line)", "\n".join(profile["skills"]))
            if st.form_submit_button("Save profile"):
                profile.update(name=name, location=location, summary=summary,
                               skills=[item.strip() for item in skills.splitlines() if item.strip()])
                saved = api("PUT", "/profile", json=profile)
                if saved:
                    st.success("Profile saved.")
        uploaded = st.file_uploader("Add immutable source resume", type=["pdf", "docx"])
        if uploaded and st.button("Upload resume"):
            result = api("POST", "/resumes", files={"file": (uploaded.name, uploaded.getvalue())})
            if result:
                st.success(f"Resume stored; extracted {result.get('extracted_characters', 0)} characters.")
elif page == "Profile audit":
    if st.button("Run profile audit"):
        audit = api("GET", "/audit/profile")
        if audit:
            st.metric("Heuristic readiness", audit["readiness_score"] if "readiness_score" in audit else "—")
            st.json(audit)
elif page == "Job discovery":
    with st.form("board"):
        provider = st.selectbox("Public job board", ["greenhouse", "lever"])
        board_token = st.text_input("Board token / site name")
        company_name = st.text_input("Company name shown on listings", "Unknown company")
        if st.form_submit_button("Add source") and board_token:
            api("POST", "/sources", json={
                "provider": provider,
                "board_token": board_token,
                "company_name": company_name,
            })
    if st.button("Run discovery now"):
        result = api("POST", "/discovery/run")
        if result:
            st.json(result)
    st.dataframe(api("GET", "/jobs") or [], use_container_width=True)
elif page == "Applications":
    applications = api("GET", "/applications") or []
    for item in applications:
        with st.expander(f"{item['job']['title']} · {item['job']['company']} · {item['status']}"):
            st.write(item["job"]["location"])
            st.write(item["job"]["match"])
            st.link_button("Open original listing", item["job"]["url"])
            required_fields = st.text_input(
                "Application fields to verify (comma-separated)",
                key=f"answer-check-fields-{item['id']}",
            )
            if st.button("Check answer readiness", key=f"answer-check-{item['id']}") and required_fields.strip():
                result = api(
                    "POST",
                    f"/applications/{item['id']}/answer-check",
                    json={"required_fields": [part.strip() for part in required_fields.split(",") if part.strip()]},
                )
                if result:
                    if result["ready"]:
                        st.success("Required answer-bank fields are verified and current.")
                    else:
                        st.warning("Review the answer-bank results before applying.")
                    st.json(result)
            if item["status"] == "PENDING_APPROVAL":
                if st.button("Prepare ATS-friendly resume", key=f"resume-{item['id']}"):
                    generated = api("POST", f"/applications/{item['id']}/resume")
                    if generated:
                        st.success(f"Prepared {generated['filename']}. Source wording is retained.")
                        st.write(f"Relevant verified skills: {', '.join(generated['selected_skills']) or 'None detected'}")
                        try:
                            document = requests.get(
                                f"{api_url}{generated['download_url']}",
                                headers=headers,
                                timeout=20,
                            )
                            document.raise_for_status()
                            st.download_button(
                                "Download generated DOCX",
                                data=document.content,
                                file_name=generated["filename"],
                                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                key=f"download-{generated['version_id']}",
                            )
                        except requests.RequestException as exc:
                            st.error(f"Resume download failed: {exc}")
                with st.form(f"approve-{item['id']}"):
                    approval_fields = st.text_input(
                        "Required answer keys (comma-separated; leave blank only if none)",
                        key=f"approval-fields-{item['id']}",
                    )
                    answers_reviewed = st.checkbox(
                        "I reviewed the application, required fields, and saved answers.",
                        key=f"answers-reviewed-{item['id']}",
                    )
                    manual_review_acknowledged = st.checkbox(
                        "I personally reviewed sensitive declarations, work authorization, and compensation answers.",
                        key=f"manual-review-{item['id']}",
                    )
                    approve = st.form_submit_button("Approve for manual submission")
                if approve:
                    result = api(
                        "POST",
                        f"/applications/{item['id']}/approve",
                        json={
                            "required_fields": [
                                part.strip() for part in approval_fields.split(",") if part.strip()
                            ],
                            "answers_reviewed": answers_reviewed,
                            "manual_review_acknowledged": manual_review_acknowledged,
                        },
                    )
                    if result:
                        st.success("Approved. Continue manually on the original portal.")
                        st.rerun()
elif page == "Resume versions":
    versions = api("GET", "/resume-versions") or []
    st.dataframe(versions, use_container_width=True)
    for version in versions:
        try:
            document = requests.get(
                f"{api_url}{version['download_url']}",
                headers=headers,
                timeout=20,
            )
            document.raise_for_status()
            st.download_button(
                f"Download {version['filename']}",
                data=document.content,
                file_name=version["filename"],
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"resume-version-{version['version_id']}",
            )
        except requests.RequestException as exc:
            st.warning(f"{version['filename']} is unavailable: {exc}")
elif page == "Answer bank":
    st.caption("Answers are encrypted at rest. Never enter information you do not want stored.")
    answers = api("GET", "/answer-bank")
    if answers is not None:
        existing_by_key = {answer["field_key"]: answer for answer in answers}
        with st.form("answer-bank"):
            field_key = st.text_input("Field key (e.g. notice_period, work_authorization)")
            existing = existing_by_key.get(field_key.strip().lower().replace("-", "_"))
            value = st.text_input(
                "Answer",
                value=existing["value"] if existing and not existing["sensitive"] else "",
                type="password" if existing and existing["sensitive"] else "default",
                help="Sensitive existing values are not shown; enter a replacement to update them."
                if existing and existing["sensitive"] else None,
            )
            status = st.selectbox(
                "Verification",
                ["unverified", "verified"],
                index=1 if existing and existing["verification_status"] == "verified" else 0,
            )
            expiry = st.text_input(
                "Expiry (optional ISO date/time)",
                existing["expires_at"] or "" if existing else "",
            )
            sensitive = st.checkbox("Sensitive or requires manual review", value=bool(existing and existing["sensitive"]))
            save = st.form_submit_button("Save answer")
        if save:
            if not value.strip():
                st.error("Enter an answer value. Sensitive existing answers are intentionally not displayed.")
            else:
                payload = {
                    "value": value,
                    "verification_status": status,
                    "expires_at": expiry or None,
                    "sensitive": sensitive,
                }
                saved = api("PUT", f"/answer-bank/{field_key}", json=payload)
                if saved:
                    st.success(f"Saved {saved['field_key']} ({saved['verification_status']}).")
                    st.rerun()
        st.dataframe(
            [
                {
                    "field_key": answer["field_key"],
                    "verification_status": answer["verification_status"],
                    "expires_at": answer["expires_at"],
                    "sensitive": answer["sensitive"],
                    "updated_at": answer["updated_at"],
                }
                for answer in answers
            ],
            use_container_width=True,
        )
elif page == "Scheduler and logs":
    state = api("GET", "/scheduler")
    if state:
        st.metric("Worker status", state["worker_status"])
        st.caption(f"Last heartbeat: {state['last_heartbeat'] or 'Not reported'}")
        with st.form("scheduler-settings"):
            enabled = st.toggle("Daily scheduler enabled", value=state["enabled"])
            schedule_time = st.time_input(
                "Daily run time",
                value=time(state["hour"], state["minute"]),
            )
            timezone_name = st.text_input("IANA time zone", state["timezone"])
            daily_limit = st.number_input(
                "Daily application limit",
                min_value=0,
                max_value=100,
                value=state["daily_application_limit"],
            )
            if st.form_submit_button("Save scheduler settings"):
                updated = api(
                    "PUT",
                    "/scheduler",
                    json={
                        "enabled": enabled,
                        "hour": schedule_time.hour,
                        "minute": schedule_time.minute,
                        "timezone": timezone_name,
                        "daily_application_limit": int(daily_limit),
                    },
                )
                if updated:
                    st.success("Scheduler settings saved; the worker syncs them within 30 seconds.")
                    st.rerun()
    st.subheader("Recent scheduled runs")
    runs = api("GET", "/scheduled-runs") or []
    st.dataframe(runs, use_container_width=True)
    for run in runs:
        if run["status"] in {"FAILED", "PARTIAL"}:
            summary = run.get("summary") or {}
            failures = summary.get("source_failures") or []
            label = "Retry failed sources" if failures else "Retry discovery"
            if st.button(label, key=f"retry-run-{run['id']}"):
                retried = api("POST", f"/scheduled-runs/{run['id']}/retry")
                if retried:
                    st.success(
                        f"Created recovery run #{retried['id']} linked to run #{run['id']}."
                    )
                    st.rerun()
    st.subheader("Recent task errors")
    st.dataframe(api("GET", "/task-executions") or [], use_container_width=True)
