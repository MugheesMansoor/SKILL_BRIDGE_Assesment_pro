import json, os
from datetime import datetime, timezone
from typing import Literal, Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Field as F, Session, SQLModel, create_engine, select
from .kb import KB
from .llm import explain, fallback_text
from .rules import evaluate

OOS_THRESHOLD = 0.08  # ASSUMPTION (see PROJECT_CONTINUATION_CONTEXT.md): untuned
engine = create_engine(f"sqlite:///{os.getenv('DB_PATH', 'cases.db')}")
kb = KB()
app = FastAPI(title="SkillBridge Case Resolution Desk")


class CaseIn(BaseModel):
    learner_name: str = Field(min_length=1)
    question: str = Field(min_length=1)
    attendance: Optional[float] = Field(None, ge=0, le=100)
    live_sessions: Optional[int] = Field(None, ge=0)
    capstone_score: Optional[float] = Field(None, ge=0, le=100)
    extension_state: Literal["unknown", "not_requested", "requested_pending", "approved", "denied"] = "unknown"
    extension_request_time: Optional[datetime] = None
    secret_present: Optional[bool] = None
    readme_present: Optional[bool] = None
    link_accessible: Optional[bool] = None
    medical_note: bool = False
    evidence_verified: bool = False


class Case(SQLModel, table=True):
    id: Optional[int] = F(default=None, primary_key=True)
    created_at: str
    updated_at: str
    learner_name: str
    question: str
    facts_json: str
    status: str
    outcome: str
    result_json: str
    citations_json: str
    note: str
    llm_used: bool
    history_json: str = "[]"


SQLModel.metadata.create_all(engine)
now = lambda: datetime.now(timezone.utc).isoformat()


def analyze(ci: CaseIn):
    facts = ci.model_dump(mode="json")
    res = evaluate(ci.model_dump())
    ex = kb.retrieve(ci.question)
    if not ex or ex[0]["score"] < OOS_THRESHOLD:
        res["next_actions"].append({"owner": "coordinator", "action": "The available policies do not establish an answer to this question; refer to the coordinator."})
    text = explain(facts, res, ex)
    return res, (text or fallback_text(res, ex)), text is not None


def fill(c: Case, ci: CaseIn, event):
    res, note, used = analyze(ci)
    c.learner_name, c.question, c.facts_json = ci.learner_name, ci.question, ci.model_dump_json()
    c.status, c.outcome, c.result_json = res["status"], res["certificate"], json.dumps(res)
    c.citations_json, c.note, c.llm_used, c.updated_at = json.dumps(res["sources"]), note, used, now()
    h = json.loads(c.history_json); h.append({"at": c.updated_at, "event": event, "status": c.status})
    c.history_json = json.dumps(h)


def _get(s, cid):
    c = s.get(Case, cid)
    if not c:
        raise HTTPException(404, "Case not found")
    return c


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/cases")
def create(ci: CaseIn):
    c = Case(created_at=now(), updated_at=now(), learner_name="", question="", facts_json="", status="",
             outcome="", result_json="", citations_json="", note="", llm_used=False)
    fill(c, ci, "created")
    with Session(engine) as s:
        s.add(c); s.commit(); s.refresh(c)
        return c


@app.get("/api/cases")
def list_cases():
    with Session(engine) as s:
        return s.exec(select(Case).order_by(Case.id.desc())).all()


@app.get("/api/cases/{cid}")
def get_case(cid: int):
    with Session(engine) as s:
        return _get(s, cid)


@app.put("/api/cases/{cid}")
def re_evaluate(cid: int, ci: CaseIn):
    with Session(engine) as s:
        c = _get(s, cid)
        fill(c, ci, "re-evaluated")
        s.add(c); s.commit(); s.refresh(c)
        return c


class CloseIn(BaseModel):
    outcome: str = Field(min_length=1)


@app.post("/api/cases/{cid}/close")
def close(cid: int, body: CloseIn):
    with Session(engine) as s:
        c = _get(s, cid)
        c.status, c.outcome, c.updated_at = "Closed", body.outcome, now()
        h = json.loads(c.history_json); h.append({"at": c.updated_at, "event": "closed", "status": "Closed"})
        c.history_json = json.dumps(h)
        s.add(c); s.commit(); s.refresh(c)
        return c


# Serve the built React frontend (frontend/dist) at "/", after all /api routes.
from pathlib import Path
from fastapi.staticfiles import StaticFiles

_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
