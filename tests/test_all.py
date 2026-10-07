import os, sys, tempfile
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.pop("OPENAI_API_KEY", None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from datetime import datetime
from fastapi.testclient import TestClient
from app.main import app, kb
from app.rules import evaluate, add_business_days, DEADLINE, PKT

base = dict(attendance=82, live_sessions=3, capstone_score=78, secret_present=False)

def test_attendance_threshold():
    assert evaluate({**base, "attendance": 79.9})["certificate"] == "not_currently_eligible"
    assert evaluate(base)["certificate"] == "meets_recorded_requirements"

def test_score_threshold():
    assert evaluate({**base, "capstone_score": 69})["certificate"] == "not_currently_eligible"
    assert evaluate({**base, "capstone_score": 70})["certificate"] == "meets_recorded_requirements"
    assert evaluate({**base, "capstone_score": 65})["certificate"] == "not_currently_eligible"

def test_unknown_score_pending():
    assert evaluate({**base, "capstone_score": None})["certificate"] == "pending"

def test_medical_note_no_waiver():
    r = evaluate({**base, "attendance": 76, "live_sessions": 2, "medical_note": True})
    assert r["certificate"] == "not_currently_eligible"

def test_secret_hold():
    r = evaluate({**base, "secret_present": True})
    assert r["submission_hold"] and r["certificate"] == "pending" and r["status"] == "Waiting for Learner"

def test_extension_monday():
    assert add_business_days(DEADLINE, 1) == datetime(2026, 10, 12, 17, 0, tzinfo=PKT)
    t = datetime(2026, 10, 8, 12, 0)
    assert evaluate({**base, "extension_state": "approved", "extension_request_time": t})["due_date"].startswith("2026-10-12T17:00")
    p = evaluate({**base, "extension_state": "requested_pending", "extension_request_time": t})
    assert p["status"] == "Waiting for Mentor" and p["due_date"].startswith("2026-10-09T17:00")

def test_extension_late_or_no_timestamp():
    late = evaluate({**base, "extension_state": "approved", "extension_request_time": datetime(2026, 10, 9, 17, 0)})
    assert late["due_date"].startswith("2026-10-09") and late["next_actions"]
    none = evaluate({**base, "extension_state": "approved"})
    assert none["due_date"].startswith("2026-10-09") and none["status"] == "Waiting for Learner"

def test_retriever_excludes_superseded():
    hits = kb.retrieve("capstone pass score 60 deadline 18:00")
    assert hits and all(h["id"] != "KB-05" for h in hits)
    assert any(h["id"] == "KB-05" for h in kb.retrieve("capstone pass score 60 old policy", mode="explain", k=10))

def test_api_flow():
    c = TestClient(app)
    assert c.post("/api/cases", json={"learner_name": "A", "question": "q", "attendance": 101}).status_code == 422
    r = c.post("/api/cases", json={"learner_name": "A", "question": "Am I eligible for the certificate?", **base}).json()
    assert r["outcome"] == "meets_recorded_requirements" and r["llm_used"] is False and r["note"]
    assert c.put(f"/api/cases/{r['id']}", json={"learner_name": "A", "question": "q", **{**base, "attendance": 70}}).json()["outcome"] == "not_currently_eligible"
    assert c.post(f"/api/cases/{r['id']}/close", json={"outcome": "done"}).json()["status"] == "Closed"
    assert c.get("/api/cases/999").status_code == 404

def test_openai_path_mocked(monkeypatch):
    import httpx
    seen = {}
    class R:
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": "Explained. KB-01 v2"}}]}
    def fake_post(url, **kw):
        seen["url"], seen["auth"] = url, kw["headers"]["Authorization"]
        return R()
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key"); monkeypatch.setenv("OPENAI_MODEL", "m")
    r = TestClient(app).post("/api/cases", json={"learner_name": "A", "question": "Am I eligible?", **base}).json()
    assert r["llm_used"] is True and seen["url"] == "https://api.openai.com/v1/chat/completions"

def test_frontend_served():
    r = TestClient(app).get("/")
    assert r.status_code == 200 and 'id="root"' in r.text
    assert TestClient(app).get("/api/health").json() == {"ok": True}
