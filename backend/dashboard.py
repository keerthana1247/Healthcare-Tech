"""Dashboard data assembly and case-review workflow (persisted in SQLite)."""
from __future__ import annotations
import json
import re
from datetime import datetime, timezone
from fastapi import HTTPException
from .db import audit, now
from .scoring import FEEDBACK_VALUES, REVIEW_STATUSES, score_case

CASE_RE = re.compile(r"^SYN-\d{4,6}$")


def _cfg(con):
    g = lambda k: json.loads(con.execute("SELECT value FROM app_config WHERE key=?", (k,)).fetchone()["value"])
    return g("cfg"), g("thresholds"), g("as_of")


def registry(con):
    reg, pv = {}, {}
    for r in con.execute("SELECT * FROM metric_registry ORDER BY metric_id, version"):
        m = reg.setdefault(r["metric_id"], {"name": r["name"], "formula": r["formula"], "vs": []})
        m["vs"].append({"v": r["version"], "num": r["numerator"], "den": r["denominator"], "incl": r["inclusion"],
                        "excl": r["exclusion"], "win": r["window"], "src": r["sources"], "mod": r["modified"]})
        p = pv.setdefault(r["metric_id"], [None, None])
        if r["is_previous_period"]: p[0] = r["version"]
        if r["is_current"]: p[1] = r["version"]
    return reg, pv


def _logs(con):
    out: dict[int, list[str]] = {}
    for r in con.execute("SELECT case_no, entry FROM case_review_log ORDER BY id DESC"):
        out.setdefault(r["case_no"], []).append(r["entry"])
    return out


def build_payload(con, role: str) -> dict:
    cfg, thresholds, as_of = _cfg(con)
    reg, pv = registry(con)
    fu_ver = next(v for v in pv["FU"][1:])
    detail = role != "manager"          # managers get aggregates only: no case IDs, notes or evidence
    logs = _logs(con) if detail else {}
    reviews = {r["case_no"]: r for r in con.execute("SELECT * FROM case_reviews")}
    cases = []
    for r in con.execute("SELECT * FROM dashboard_cases ORDER BY case_no"):
        c = {"co": r["cohort"], "rg": r["region"], "ag": r["age_group"], "gap": r["is_gap"], "doc": r["has_doc"]}
        if r["is_gap"]:
            sc = score_case({"visit": r["visit_days"], "test": r["test_days"], "doc": r["has_doc"], "due": r["overdue_days"],
                             "outside": bool(r["outside_care"]), "conf": bool(r["conflict"]),
                             "src": r["source_completeness"]}, cfg, fu_ver)
            rv = reviews[r["case_no"]]
            if detail:
                c.update(id=r["case_id"], visit=r["visit_days"], test=r["test_days"], outside=bool(r["outside_care"]),
                         conf=bool(r["conflict"]), src=r["source_completeness"], due=r["overdue_days"], upd=r["updated_days"],
                         sc=sc, rv={"st": rv["status"], "fb": rv["feedback"], "log": logs.get(r["case_no"], [])})
            else:
                c.update(id=None, sc={"t": sc["t"]}, rv={"st": rv["status"], "fb": rv["feedback"], "log": []})
        else:
            c["id"] = r["case_id"] if detail else None
        cases.append(c)
    return {
        "as_of": as_of, "role": role, "config": cfg, "thresholds": thresholds,
        "cohorts": [{"n": r["name"], "pe": r["prev_eligible"], "pf": r["prev_followup"], "pc": r["prev_complete"],
                     "ce": r["curr_eligible"], "cf": r["curr_followup"], "cc": r["curr_complete"]}
                    for r in con.execute("SELECT * FROM cohorts ORDER BY sort_order")],
        "sources": [{"n": r["name"], "u": r["days_since"], "lim": r["limit_days"]}
                    for r in con.execute("SELECT * FROM data_sources ORDER BY sort_order")],
        "registry": reg, "pv": pv, "cases": cases,
    }


def _case(con, case_id: str):
    if not CASE_RE.match(case_id):
        raise HTTPException(400, "Invalid case ID.")
    r = con.execute("SELECT c.case_no,c.is_gap,v.status,v.feedback FROM dashboard_cases c "
                    "LEFT JOIN case_reviews v ON v.case_no=c.case_no WHERE c.case_id=?", (case_id,)).fetchone()
    if not r: raise HTTPException(404, "Case not found.")
    if not r["is_gap"]: raise HTTPException(400, "Only flagged potential gaps can be reviewed.")
    return r


def _state(con, case_no):
    r = con.execute("SELECT status,feedback FROM case_reviews WHERE case_no=?", (case_no,)).fetchone()
    log = [x["entry"] for x in con.execute("SELECT entry FROM case_review_log WHERE case_no=? ORDER BY id DESC", (case_no,))]
    return {"st": r["status"], "fb": r["feedback"], "log": log}


def _stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _note_part(note):
    return f" — {note}" if note else ""


def set_status(con, role, case_id, status, note):
    note = (note or "").strip()[:500]
    c = _case(con, case_id)
    if status not in REVIEW_STATUSES: raise HTTPException(400, "Invalid status.")
    if status == c["status"]: raise HTTPException(400, "Status unchanged.")
    if status in ("Resolved", "Rejected") and not note:
        raise HTTPException(400, f"A reviewer note is required for {status}.")
    con.execute("UPDATE case_reviews SET status=?,updated_at=? WHERE case_no=?", (status, now(), c["case_no"]))
    con.execute("INSERT INTO case_review_log(case_no,entry,actor_role,created_at) VALUES(?,?,?,?)",
                (c["case_no"], f"{_stamp()} · {role}: status {c['status']} → {status}{_note_part(note)}", role, now()))
    audit(con, role, "case_status_changed", "dashboard_case", c["case_no"], f"{case_id}: {c['status']} -> {status}")
    return _state(con, c["case_no"])


def set_feedback(con, role, case_id, feedback, note):
    note = (note or "").strip()[:500]
    c = _case(con, case_id)
    if feedback not in FEEDBACK_VALUES: raise HTTPException(400, "Invalid feedback value.")
    if feedback != "Correct gap" and not note:
        raise HTTPException(400, "A reviewer note is required for this outcome.")
    status = "Under Review" if c["status"] == "Pending" else c["status"]
    con.execute("UPDATE case_reviews SET feedback=?,status=?,updated_at=? WHERE case_no=?", (feedback, status, now(), c["case_no"]))
    con.execute("INSERT INTO case_review_log(case_no,entry,actor_role,created_at) VALUES(?,?,?,?)",
                (c["case_no"], f"{_stamp()} · {role}: feedback {c['feedback'] or 'none'} → {feedback}{_note_part(note)}", role, now()))
    audit(con, role, "case_feedback_recorded", "dashboard_case", c["case_no"], f"{case_id}: {feedback}")
    return _state(con, c["case_no"])
