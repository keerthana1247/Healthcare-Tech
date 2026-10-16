"""MetricBridge Health API. SYNTHETIC DEMO DATA ONLY - not for real clinical use."""
from __future__ import annotations
import json, re, secrets, sqlite3, time
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Optional
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from . import dashboard
from .auth import ROLES, hash_password, verify_password, verify_unknown_account
from .db import ROOT, audit, connect, init_db, now

FRONTEND = ROOT / "frontend"
SESSION_TTL = 8 * 3600
SESSIONS: dict[str, tuple[str, float, int]] = {}  # token -> (role, expiry, user id)
EMAIL_RE = re.compile(r"^\S+@\S+\.\S+$")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="MetricBridge Health API", version="2.0.0", lifespan=lifespan,
              description="Synthetic-data prototype only. Not for real clinical use.")
app.add_middleware(CORSMiddleware, allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
                   allow_credentials=False, allow_methods=["GET", "POST", "PATCH", "PUT"], allow_headers=["Authorization", "Content-Type"])


# ---------------------------------------------------------------- auth
def _issue(user: sqlite3.Row, how: str) -> dict:
    token = secrets.token_urlsafe(32)
    role = user["role"]
    SESSIONS[token] = (role, time.time() + SESSION_TTL, user["id"])
    with connect() as c:
        audit(c, role, how, "session", user["id"], f"Account sign-in: {user['email']}")
    return {"access_token": token, "role": role, "demo_only": True}


def _role_ok(role: str):
    if role not in ROLES:
        raise HTTPException(400, "Unknown account role.")


class EmailLogin(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)
    role: str

class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    display_name: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=12, max_length=200)
    role: str

class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=2, max_length=100)
    password: str | None = Field(default=None, min_length=12, max_length=200)
    role: str | None = None
    is_active: bool | None = None

class AdminSettingsIn(BaseModel):
    min_cohort_size: int = Field(ge=1, le=1000)
    hidden_gap_threshold: float = Field(ge=0, le=100)
    documentation_threshold: float = Field(ge=0, le=100)
    population_threshold: float = Field(ge=0, le=100)
    change_threshold: float = Field(ge=0, le=100)


def _token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Sign in to the demo workspace.")
    return authorization[7:]


def current_role(authorization: Optional[str] = Header(default=None)) -> str:
    tok = _token(authorization)
    s = SESSIONS.get(tok)
    if not s or s[1] < time.time():
        SESSIONS.pop(tok, None)
        raise HTTPException(401, "Demo session expired. Sign in again.")
    with connect() as c:
        user = c.execute("SELECT role,is_active FROM users WHERE id=?", (s[2],)).fetchone()
    if not user or not user["is_active"] or user["role"] != s[0]:
        SESSIONS.pop(tok, None)
        raise HTTPException(401, "Account access changed. Sign in again.")
    return s[0]

def require_roles(*allowed: str):
    def check(role: str = Depends(current_role)) -> str:
        if role not in allowed:
            raise HTTPException(403, "Your account role cannot perform this action.")
        return role
    return check


@app.get("/api/health")
def health():
    return {"status": "ok", "mode": "synthetic-demo-only"}


@app.post("/api/auth/login")
def email_login(body: EmailLogin):
    _role_ok(body.role)
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address.")
    with connect() as c:
        user = c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not user:
        verify_unknown_account(body.password)
        raise HTTPException(401, "Sign-in failed. Check that the email, password, and selected role match an active demo account.")
    valid_password = verify_password(body.password, user["password_hash"])
    if not valid_password or not user["is_active"] or body.role != user["role"]:
        raise HTTPException(401, "Sign-in failed. Check that the email, password, and selected role match an active demo account.")
    return _issue(user, "account_sign_in")


@app.post("/api/auth/demo-access")
def demo_access(body: EmailLogin):
    """Credential-checked compatibility route; role-only demo access is not allowed."""
    return email_login(body)


@app.get("/api/auth/me")
def me(role: str = Depends(current_role)):
    return {"role": role, "demo_only": True}


@app.post("/api/auth/logout")
def logout(role: str = Depends(current_role), authorization: Optional[str] = Header(default=None)):
    SESSIONS.pop(_token(authorization), None)
    return {"ok": True}


# ---------------------------------------------------------------- dashboard
class ReviewStatusIn(BaseModel):
    status: str = Field(max_length=40)
    note: str = Field(default="", max_length=500)

class FeedbackIn(BaseModel):
    feedback: str = Field(max_length=40)
    note: str = Field(default="", max_length=500)


@app.get("/api/dashboard")
def get_dashboard(role: str = Depends(current_role)):
    with connect() as c:
        return dashboard.build_payload(c, role)


@app.post("/api/cases/{case_id}/status")
def case_status(case_id: str, body: ReviewStatusIn, role: str = Depends(require_roles("reviewer"))):
    with connect() as c:
        return dashboard.set_status(c, role, case_id, body.status, body.note)


@app.post("/api/cases/{case_id}/feedback")
def case_feedback(case_id: str, body: FeedbackIn, role: str = Depends(require_roles("reviewer"))):
    with connect() as c:
        return dashboard.set_feedback(c, role, case_id, body.feedback, body.note)


@app.post("/api/reports/exported")
def report_exported(role: str = Depends(require_roles("manager", "reviewer", "administrator"))):
    with connect() as c:
        audit(c, role, "exported_report_csv", "report", 0, "Quality summary CSV exported")
    return {"ok": True}


# ---------------------------------------------------------------- patient care records
class PatientIn(BaseModel):
    patient_id: str = Field(min_length=3, max_length=40)
    display_name: str = Field(min_length=2, max_length=100)
    age: int = Field(ge=0, le=120)
    department: str = Field(min_length=2, max_length=80)
    condition_label: str = Field(min_length=2, max_length=200)

class TreatmentIn(BaseModel):
    treatment_date: date
    record_type: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=2, max_length=1000)
    provider: str = Field(default="", max_length=120)
    source_reference: str = Field(default="", max_length=120)
    status: str = Field(default="Documented", max_length=40)

class FollowupIn(BaseModel):
    due_date: date
    purpose: str = Field(min_length=2, max_length=250)
    status: str = Field(default="Scheduled", max_length=40)
    source_reference: str = Field(default="", max_length=120)

class ReviewIn(BaseModel):
    outcome: str = Field(min_length=2, max_length=40)
    note: str = Field(min_length=2, max_length=500)


def get_patient(con, pid):
    p = con.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    if not p:
        raise HTTPException(404, "Patient record not found.")
    return p


def serialize_patient(con, p):
    rows = lambda sql: [dict(x) for x in con.execute(sql, (p["id"],))]
    followups = []
    for d in rows("SELECT * FROM followups WHERE patient_id=? ORDER BY due_date"):
        d["computed_status"] = "Overdue" if d["status"] == "Scheduled" and d["due_date"] < date.today().isoformat() else d["status"]
        followups.append(d)
    return {**dict(p),
            "treatments": rows("SELECT * FROM treatments WHERE patient_id=? ORDER BY treatment_date DESC,id DESC"),
            "followups": followups,
            "quality_issues": rows("SELECT * FROM quality_issues WHERE patient_id=? ORDER BY id DESC"),
            "audit": rows("SELECT * FROM audit_log WHERE entity_type='patient' AND entity_id=? ORDER BY id DESC LIMIT 100")}


@app.get("/api/patients")
def list_patients(role: str = Depends(require_roles("doctor", "reviewer", "manager"))):
    with connect() as c:
        return {"items": [dict(x) for x in c.execute("SELECT * FROM patients ORDER BY patient_id")]}


@app.post("/api/patients")
def create_patient(body: PatientIn, role: str = Depends(require_roles("doctor"))):
    with connect() as c:
        try:
            cur = c.execute("INSERT INTO patients(patient_id,display_name,age,department,condition_label,created_at) VALUES(?,?,?,?,?,?)",
                            (body.patient_id.strip(), body.display_name.strip(), body.age, body.department.strip(), body.condition_label.strip(), now()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "That patient ID already exists.")
        pid = cur.lastrowid
        audit(c, role, "created_patient", "patient", pid, "Created synthetic patient record")
        c.execute("INSERT INTO quality_issues(patient_id,field_name,reason,status,created_at) VALUES(?,?,?,?,?)",
                  (pid, "followup.record", "No follow-up record has been entered yet; verify the source before deciding whether one is needed.", "Missing", now()))
        return {"id": pid, "patient_id": body.patient_id.strip()}


@app.get("/api/patients/{pid}")
def patient_detail(pid: int, role: str = Depends(require_roles("doctor", "reviewer", "manager"))):
    with connect() as c:
        return serialize_patient(c, get_patient(c, pid))


@app.post("/api/patients/{pid}/treatments")
def add_treatment(pid: int, body: TreatmentIn, role: str = Depends(require_roles("doctor"))):
    if body.status not in {"Documented", "Needs verification", "Imported - unverified"}:
        raise HTTPException(400, "Invalid treatment record status.")
    with connect() as c:
        get_patient(c, pid)
        cur = c.execute("""INSERT INTO treatments(patient_id,treatment_date,record_type,description,provider,source_reference,status,created_at)
          VALUES(?,?,?,?,?,?,?,?)""", (pid, body.treatment_date.isoformat(), body.record_type.strip(), body.description.strip(),
                                       body.provider.strip(), body.source_reference.strip(), body.status, now()))
        tid = cur.lastrowid
        audit(c, role, "added_treatment", "patient", pid, f"Treatment record #{tid}; status={body.status}")
        if not body.source_reference.strip() or body.status != "Documented":
            reason = "Source reference is missing." if not body.source_reference.strip() else "Treatment record requires verification."
            c.execute("INSERT INTO quality_issues(patient_id,field_name,reason,status,created_at) VALUES(?,?,?,'Missing',?)",
                      (pid, f"treatment:{tid}", reason, now()))
        return {"id": tid, "saved": True}


@app.post("/api/patients/{pid}/followups")
def add_followup(pid: int, body: FollowupIn, role: str = Depends(require_roles("doctor"))):
    if body.status not in {"Scheduled", "Completed", "Needs verification", "Cancelled"}:
        raise HTTPException(400, "Invalid follow-up status.")
    with connect() as c:
        get_patient(c, pid)
        cur = c.execute("INSERT INTO followups(patient_id,due_date,purpose,status,source_reference,created_at) VALUES(?,?,?,?,?,?)",
                        (pid, body.due_date.isoformat(), body.purpose.strip(), body.status, body.source_reference.strip(), now()))
        fid = cur.lastrowid
        audit(c, role, "added_followup", "patient", pid, f"Follow-up #{fid}; status={body.status}")
        if not body.source_reference.strip() or body.status == "Needs verification":
            c.execute("INSERT INTO quality_issues(patient_id,field_name,reason,status,created_at) VALUES(?,?,?,'Missing',?)",
                      (pid, f"followup:{fid}", "Follow-up needs source verification or a source reference is missing.", now()))
        return {"id": fid, "saved": True}


@app.post("/api/quality/{issue_id}/review")
def review_quality(issue_id: int, body: ReviewIn, role: str = Depends(require_roles("reviewer"))):
    status_map = {"Verified": "Verified", "Still missing": "Missing", "Conflict": "Conflict"}
    if body.outcome not in status_map:
        raise HTTPException(400, "Outcome must be Verified, Still missing, or Conflict.")
    with connect() as c:
        issue = c.execute("SELECT * FROM quality_issues WHERE id=?", (issue_id,)).fetchone()
        if not issue:
            raise HTTPException(404, "Quality issue not found.")
        c.execute("UPDATE quality_issues SET status=?,reviewed_at=?,review_outcome=?,review_note=? WHERE id=?",
                  (status_map[body.outcome], now(), body.outcome, body.note.strip(), issue_id))
        audit(c, role, "reviewed_quality_issue", "patient", issue["patient_id"], f"Issue #{issue_id}: {body.outcome}; note recorded")
        return {"saved": True, "status": status_map[body.outcome]}


@app.get("/api/metrics")
def metrics(role: str = Depends(current_role)):
    q = lambda sql: connect().execute(sql).fetchone()["n"]
    return {"patients": q("SELECT COUNT(*) n FROM patients"),
            "treatments": q("SELECT COUNT(*) n FROM treatments"),
            "pending_followups": q("SELECT COUNT(*) n FROM followups WHERE status IN ('Scheduled','Needs verification')"),
            "open_quality_issues": q("SELECT COUNT(*) n FROM quality_issues WHERE status IN ('Missing','Conflict')")}


@app.get("/api/audit")
def all_audit(role: str = Depends(current_role)):
    if role not in {"manager", "reviewer", "administrator"}:
        raise HTTPException(403, "Your account role cannot view all audit entries.")
    with connect() as c:
        return {"items": [dict(x) for x in c.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 500")]}


@app.get("/api/admin/users")
def list_users(_: str = Depends(require_roles("administrator"))):
    with connect() as c:
        return {"items": [dict(x) for x in c.execute(
            "SELECT id,email,display_name,role,is_active,created_at,updated_at FROM users ORDER BY email"
        )]}


@app.post("/api/admin/users", status_code=201)
def create_user(body: UserCreate, _: str = Depends(require_roles("administrator"))):
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "Enter a valid email address.")
    _role_ok(body.role)
    with connect() as c:
        try:
            cur = c.execute(
                """INSERT INTO users(email,display_name,role,password_hash,is_active,created_at,updated_at)
                   VALUES(?,?,?,?,1,?,?)""",
                (email, body.display_name.strip(), body.role, hash_password(body.password), now(), now()),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "An account with that email already exists.")
        audit(c, "administrator", "created_user", "user", cur.lastrowid, f"Created {body.role} account: {email}")
        return {"id": cur.lastrowid, "email": email, "role": body.role, "is_active": True}


@app.patch("/api/admin/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, _: str = Depends(require_roles("administrator"))):
    fields = body.dict(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "Provide at least one account field to update.")
    if any(value is None for value in fields.values()):
        raise HTTPException(400, "Account fields cannot be null.")
    if "role" in fields:
        _role_ok(fields["role"])
    if "password" in fields:
        fields["password_hash"] = hash_password(fields.pop("password"))
    with connect() as c:
        target = c.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if not target:
            raise HTTPException(404, "Account not found.")
        is_losing_admin = target["role"] == "administrator" and target["is_active"] and (
            fields.get("role", "administrator") != "administrator" or fields.get("is_active") is False
        )
        if is_losing_admin:
            remaining = c.execute(
                "SELECT COUNT(*) n FROM users WHERE role='administrator' AND is_active=1 AND id<>?",
                (user_id,),
            ).fetchone()["n"]
            if not remaining:
                raise HTTPException(400, "The last active administrator cannot be disabled or demoted.")
        updates = {key: value for key, value in fields.items() if key in {"display_name", "role", "is_active", "password_hash"}}
        if not updates:
            raise HTTPException(400, "No valid account fields were provided.")
        updates["updated_at"] = now()
        c.execute(
            "UPDATE users SET " + ",".join(f"{key}=?" for key in updates) + " WHERE id=?",
            (*updates.values(), user_id),
        )
        if "password_hash" in updates:
            for token, session in list(SESSIONS.items()):
                if session[2] == user_id:
                    SESSIONS.pop(token, None)
        audit(c, "administrator", "updated_user", "user", user_id, f"Updated account: {target['email']}")
        return {"id": user_id, "email": target["email"], **{
            "display_name": updates.get("display_name", target["display_name"]),
            "role": updates.get("role", target["role"]),
            "is_active": updates.get("is_active", target["is_active"]),
        }}


@app.get("/api/admin/settings")
def get_admin_settings(_: str = Depends(require_roles("administrator"))):
    with connect() as c:
        config = json.loads(c.execute("SELECT value FROM app_config WHERE key='cfg'").fetchone()["value"])
        thresholds = json.loads(c.execute("SELECT value FROM app_config WHERE key='thresholds'").fetchone()["value"])
    return {
        "min_cohort_size": config["minN"],
        "hidden_gap_threshold": config["hg"],
        "documentation_threshold": thresholds["doc"],
        "population_threshold": thresholds["pop"],
        "change_threshold": thresholds["chg"],
    }


@app.put("/api/admin/settings")
def update_admin_settings(body: AdminSettingsIn, _: str = Depends(require_roles("administrator"))):
    with connect() as c:
        cfg_row = c.execute("SELECT value FROM app_config WHERE key='cfg'").fetchone()
        threshold_row = c.execute("SELECT value FROM app_config WHERE key='thresholds'").fetchone()
        config, thresholds = json.loads(cfg_row["value"]), json.loads(threshold_row["value"])
        config["minN"] = body.min_cohort_size
        config["hg"] = body.hidden_gap_threshold
        thresholds.update(doc=body.documentation_threshold, pop=body.population_threshold, chg=body.change_threshold)
        c.execute("UPDATE app_config SET value=? WHERE key='cfg'", (json.dumps(config),))
        c.execute("UPDATE app_config SET value=? WHERE key='thresholds'", (json.dumps(thresholds),))
        audit(c, "administrator", "updated_system_settings", "configuration", 0,
              "Updated trust thresholds and minimum cohort size")
    return {
        "min_cohort_size": body.min_cohort_size,
        "hidden_gap_threshold": body.hidden_gap_threshold,
        "documentation_threshold": body.documentation_threshold,
        "population_threshold": body.population_threshold,
        "change_threshold": body.change_threshold,
    }


# Static front end (index.html, script.js, style.css, patients.html) - mounted last so /api/* wins.
app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
