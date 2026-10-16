"""Synthetic seed data. Everything here is invented for demonstration - no real patients."""
from __future__ import annotations
import json
from .auth import DEMO_ACCOUNTS, hash_password
from .db import audit, now
from .scoring import DEFAULT_CFG, DEFAULT_T, js_round, score_case

# ---- Cohort totals: [name, prev eligible, prev follow-up, prev complete, curr eligible, curr follow-up, curr complete]
COHORTS = [
    ("Cardiology", 250, 180, 238, 280, 242, 206),
    ("Diabetes", 230, 160, 218, 260, 222, 171),
    ("Oncology", 170, 120, 162, 190, 160, 114),
    ("Respiratory", 190, 130, 181, 210, 170, 147),
    ("Orthopedics", 160, 110, 151, 180, 158, 124),
]
SOURCES = [("Visit records", 12), ("Lab results feed", 45), ("Referral log", 20), ("Eligibility roster", 8)]
SOURCE_LIMIT_DAYS = 30

_FU = dict(name="Follow-up Completion Rate", formula="completed follow-ups ÷ eligible patients × 100")
_DOC = dict(name="Documentation Completeness", formula="records with all required fields ÷ eligible patients × 100")
REGISTRY = [
    (_FU, dict(version="1.0", numerator="Follow-up within 90 days of index visit", denominator="Eligible-condition patients", inclusion="All eligible-condition patients", exclusion="None", window="Calendar quarter", sources="Visit records", modified="2025-03-02"), "FU"),
    (_FU, dict(version="1.1", numerator="Follow-up within 60 days of index visit", denominator="Eligible-condition patients, excluding transfer-ins", inclusion="All eligible-condition patients", exclusion="Transfer-in patients", window="Calendar quarter", sources="Visit records + referral log", modified="2026-08-18"), "FU"),
    (_DOC, dict(version="1.0", numerator="Records with 5 required fields", denominator="Eligible patients", inclusion="All eligible patients", exclusion="None", window="Calendar quarter", sources="Visit records", modified="2025-03-02"), "DOC"),
    (_DOC, dict(version="1.1", numerator="Records with 6 required fields (adds follow-up date)", denominator="Eligible patients", inclusion="All eligible patients", exclusion="None", window="Calendar quarter", sources="Visit records", modified="2025-11-20"), "DOC"),
]
REGIONS = ["Urban", "Suburban", "Rural"]
AGES = ["<40", "40-59", "60+"]


def seed_demo_users(c) -> None:
    for email, display_name, role, password in DEMO_ACCOUNTS:
        if c.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            continue
        c.execute(
            """INSERT INTO users(email,display_name,role,password_hash,is_active,created_at,updated_at)
               VALUES(?,?,?,?,1,?,?)""",
            (email, display_name, role, hash_password(password), now(), now()),
        )


class Rng:
    """Park-Miller generator identical to the dashboard's `rnd()` (seed 7)."""
    def __init__(self, seed: int = 7):
        self.sd = seed

    def __call__(self) -> float:
        self.sd = self.sd * 16807 % 2147483647
        return self.sd / 2147483647


def generate_cases() -> list[dict]:
    """Deterministic port of the original generator. The ORDER of rnd() calls matters."""
    rnd = Rng(7)
    out: list[dict] = []
    seq = 1
    for name, _pe, _pf, _pc, ce, cf, cc in COHORTS:
        P = []
        for i in range(ce):
            r = 2 if rnd() < 0.3 else (1 if rnd() < 0.5 else 0)
            a = int(rnd() * 3)
            rg = "Remote" if (name == "Orthopedics" and i < 8) else REGIONS[r]
            k = rnd() + (0.5 if (r == 2 and a == 2) else 0)
            u = rnd()
            P.append(dict(case_no=seq, id=f"SYN-{seq:04d}", co=name, rg=rg, ag=AGES[a], k=k, u=u, gap=0, doc=0))
            seq += 1
        for p in sorted(P, key=lambda x: -x["k"])[: ce - cf]:
            p["gap"] = 1
        for p in sorted(P, key=lambda x: x["u"])[:cc]:
            p["doc"] = 1
        for p in P:
            if p["gap"]:
                p["visit"] = int(10 + rnd() * 340) if rnd() < 0.7 else None
                p["test"] = int(20 + rnd() * 380) if rnd() < 0.5 else None
                p["outside"] = rnd() < 0.15
                p["conf"] = rnd() < 0.08
                p["src"] = js_round(55 + rnd() * 45)
                p["due"] = int(5 + rnd() * 120) if rnd() < 0.85 else None
                p["upd"] = int(1 + rnd() * 200)
        out.extend(P)
    return out


def seed_dashboard(c) -> None:
    if c.execute("SELECT COUNT(*) n FROM cohorts").fetchone()["n"]:
        return
    c.execute("INSERT INTO app_config(key,value) VALUES('cfg',?),('thresholds',?),('as_of','\"2026-10-15\"')",
              (json.dumps(DEFAULT_CFG), json.dumps(DEFAULT_T)))
    for i, row in enumerate(COHORTS):
        c.execute("INSERT INTO cohorts VALUES(?,?,?,?,?,?,?,?)", (*row, i))
    for i, (n, u) in enumerate(SOURCES):
        c.execute("INSERT INTO data_sources VALUES(?,?,?,?)", (n, u, SOURCE_LIMIT_DAYS, i))
    for meta, v, mid in REGISTRY:
        cur = 1 if v["version"] == "1.1" else 0
        c.execute("INSERT INTO metric_registry VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (mid, meta["name"], meta["formula"], v["version"], v["numerator"], v["denominator"], v["inclusion"],
                   v["exclusion"], v["window"], v["sources"], v["modified"], cur, cur))
    cases = generate_cases()
    for p in cases:
        c.execute("INSERT INTO dashboard_cases VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (p["case_no"], p["id"], p["co"], p["rg"], p["ag"], p["gap"], p["doc"], p.get("visit"), p.get("test"),
                   None if "outside" not in p else int(p["outside"]), None if "conf" not in p else int(p["conf"]),
                   p.get("src"), p.get("due"), p.get("upd")))
        if p["gap"]:
            c.execute("INSERT INTO case_reviews(case_no,status,feedback,updated_at) VALUES(?,'Pending',NULL,?)", (p["case_no"], now()))
    # Seeded synthetic reviews (same rule as the original dashboard): first 14 "Likely real gap" cases.
    cfg = DEFAULT_CFG
    n = 0
    for p in cases:
        if not p["gap"] or n >= 14:
            continue
        sc = score_case({"visit": p["visit"], "test": p["test"], "doc": p["doc"], "due": p["due"],
                         "outside": p["outside"], "conf": p["conf"], "src": p["src"]}, cfg, "1.1")
        if sc["t"] != "Likely real gap":
            continue
        fb = "Correct gap" if n < 10 else "Wrong flag" if n < 13 else "Data was missing"
        c.execute("UPDATE case_reviews SET status='Verified',feedback=?,updated_at=? WHERE case_no=?", (fb, now(), p["case_no"]))
        c.execute("INSERT INTO case_review_log(case_no,entry,actor_role,created_at) VALUES(?,?,?,?)",
                  (p["case_no"], f"2026-09-30 · Demo doctor (seeded synthetic review): {fb}", "system", now()))
        n += 1
    audit(c, "system", "seeded_dashboard_data", "database", 0, f"{len(cases)} synthetic dashboard cases initialized")


def seed_patients(c) -> None:
    if c.execute("SELECT COUNT(*) n FROM patients").fetchone()["n"]:
        return
    demos = [
        ("DEMO-001", "Demo Patient A", 54, "Cardiology", "Follow-up monitoring"),
        ("DEMO-002", "Demo Patient B", 62, "Diabetes Care", "Routine monitoring"),
        ("DEMO-003", "Demo Patient C", 41, "Oncology", "Care-plan documentation review"),
        ("DEMO-004", "Demo Patient D", 36, "General Medicine", "Post-visit follow-up"),
    ]
    ids = []
    for pid, name, age, dept, cond in demos:
        cur = c.execute("INSERT INTO patients(patient_id,display_name,age,department,condition_label,created_at) VALUES(?,?,?,?,?,?)",
                        (pid, name, age, dept, cond, now()))
        ids.append(cur.lastrowid)
    treatments = [
        (ids[0], "2026-10-10", "Consultation", "Consultation recorded; see synthetic source note DEMO-NOTE-001.", "Demo Care Team", "DEMO-NOTE-001", "Documented"),
        (ids[0], "2026-10-11", "Test / investigation", "A test record is listed in the synthetic demo; result details intentionally not supplied.", "Demo Care Team", "DEMO-LAB-001", "Needs verification"),
        (ids[1], "2026-10-09", "Medication prescribed", "Medication prescription is referenced in this synthetic record; medication and dosage are not populated.", "Demo Care Team", "DEMO-RX-002", "Needs verification"),
        (ids[2], "2026-10-08", "Consultation", "Consultation entry exists; supporting documentation reference requires review.", "Demo Care Team", "", "Imported - unverified"),
    ]
    for row in treatments:
        c.execute("""INSERT INTO treatments(patient_id,treatment_date,record_type,description,provider,source_reference,status,created_at)
                     VALUES(?,?,?,?,?,?,?,?)""", (*row, now()))
    for row in [(ids[0], "2026-10-20", "Follow-up date listed in synthetic care plan", "Scheduled", "DEMO-PLAN-001"),
                (ids[1], "2026-10-18", "Review follow-up entry", "Needs verification", ""),
                (ids[2], "2026-10-16", "Verify follow-up documentation", "Needs verification", "DEMO-PLAN-003")]:
        c.execute("INSERT INTO followups(patient_id,due_date,purpose,status,source_reference,created_at) VALUES(?,?,?,?,?,?)", (*row, now()))
    for row in [(ids[0], "treatment.source_reference", "Treatment entry has no linked source reference."),
                (ids[1], "treatment.medication_details", "Medication details are not present in this synthetic record; do not infer them."),
                (ids[1], "followup.source_reference", "Follow-up source reference is missing."),
                (ids[2], "treatment.source_reference", "Imported treatment entry is unverified and lacks a source reference."),
                (ids[3], "followup.record", "No follow-up record is present in this synthetic demo; this does not prove care was not provided.")]:
        c.execute("INSERT INTO quality_issues(patient_id,field_name,reason,status,created_at) VALUES(?,?,?,'Missing',?)", (*row, now()))
    audit(c, "system", "seeded_synthetic_demo_data", "database", 1, "Synthetic starter records initialized")
