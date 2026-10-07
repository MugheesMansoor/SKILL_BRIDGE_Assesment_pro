"""Deterministic rules (KB-01 v2, KB-02 v3, KB-03 v2, KB-04 v1). No LLM here."""
from datetime import datetime, timedelta, timezone

PKT = timezone(timedelta(hours=5))
DEADLINE = datetime(2026, 10, 9, 17, 0, tzinfo=PKT)  # KB-02 v3
K1, K2, K3, K4 = "KB-01 v2", "KB-02 v3", "KB-03 v2", "KB-04 v1"


def add_business_days(dt, n):
    """Mon-Fri, no holidays (KB-02)."""
    while n > 0:
        dt += timedelta(days=1)
        if dt.weekday() < 5:
            n -= 1
    return dt


def evaluate(c: dict) -> dict:
    unmet, notes, learner, mentor, review = [], [], [], [], []
    src = {K1, K2, K3, K4}
    a, s, sc = c.get("attendance"), c.get("live_sessions"), c.get("capstone_score")
    pending = False
    if a is None:
        pending = True; learner.append("Provide the recorded attendance percentage.")
    elif a < 80:
        unmet.append(f"Attendance {a}% is below the 80% requirement.")
    if s is None:
        pending = True; learner.append("Provide the number of completed live sessions.")
    elif s < 3:
        unmet.append(f"{s} live session(s) completed; at least 3 required.")
    if sc is None:
        pending = True; learner.append("Capstone score unknown: provide the recorded score.")
    elif sc < 70:
        unmet.append(f"Capstone score {sc} is below the 70 pass mark (KB-05's 60 is superseded).")
    if c.get("medical_note"):
        notes.append("A medical note does not waive requirements; attendance stays as recorded until evidence is verified.")
        if not c.get("evidence_verified"):
            review.append("Coordinator to inspect the medical evidence and check the attendance record for an error.")
    hold = c.get("secret_present") is True
    if hold:
        pending = True
        learner.append("Revoke/rotate the exposed key, remove it from the package (and repo history), and submit a clean replacement.")
        notes.append("Submission is ON HOLD: a secret was reported. No pass decision until a safe replacement is confirmed.")
    elif c.get("secret_present") is None:
        pending = True; review.append("Confirm the submission is safe to review (secret check not recorded).")
    if c.get("readme_present") is False:
        pending = True; learner.append("Provide a README with local setup steps.")
    if c.get("link_accessible") is False:
        pending = True; learner.append("Grant access to the repository link or provide a ZIP.")
    ext, t, due = c.get("extension_state") or "unknown", c.get("extension_request_time"), DEADLINE
    if ext in ("requested_pending", "approved"):
        if t is None:
            learner.append("Provide the extension request timestamp; timeliness cannot be confirmed.")
        else:
            t = t if t.tzinfo else t.replace(tzinfo=PKT)  # assumption: naive = PKT
            if t >= DEADLINE:
                review.append("Request made at/after the deadline: refer for human review; policy authorizes no extension.")
            elif ext == "approved":
                due = add_business_days(DEADLINE, 1)
            else:
                mentor.append("Mentor decision on the timely extension request is pending; the standard due date stays in force.")
    elif ext == "denied":
        notes.append("Extension denied; standard due date applies.")
    cert = ("not_currently_eligible" if unmet
            else "pending" if pending else "meets_recorded_requirements")
    status = "Waiting for Learner" if learner else "Waiting for Mentor" if mentor else "Ready for Review"
    actions = ([{"owner": "learner", "action": x} for x in learner]
               + [{"owner": "mentor", "action": x} for x in mentor]
               + [{"owner": "coordinator", "action": x} for x in review])
    return {"certificate": cert, "status": status, "reasons": unmet + notes,
            "next_actions": actions, "due_date": due.isoformat(),
            "submission_hold": hold, "sources": sorted(src)}
