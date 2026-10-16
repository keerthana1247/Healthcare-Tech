"""SQLite access layer + schema for MetricBridge Health (synthetic demo data only)."""
from __future__ import annotations
import os, sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def db_path() -> Path:
    """Resolved on every call so tests can point METRICBRIDGE_DB at a temp file."""
    p = Path(os.getenv("METRICBRIDGE_DB", str(ROOT / "data" / "metricbridge.db")))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(db_path())
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def audit(con, role, action, entity_type, entity_id, detail=""):
    con.execute(
        "INSERT INTO audit_log(created_at,actor_role,action,entity_type,entity_id,detail) VALUES(?,?,?,?,?,?)",
        (now(), role, action, entity_type, int(entity_id), detail[:300]),
    )


SCHEMA = """
CREATE TABLE IF NOT EXISTS patients(
  id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT UNIQUE NOT NULL,
  display_name TEXT NOT NULL, age INTEGER NOT NULL, department TEXT NOT NULL,
  condition_label TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS treatments(
  id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER NOT NULL REFERENCES patients(id),
  treatment_date TEXT NOT NULL, record_type TEXT NOT NULL, description TEXT NOT NULL,
  provider TEXT DEFAULT '', source_reference TEXT DEFAULT '', status TEXT NOT NULL,
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS followups(
  id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER NOT NULL REFERENCES patients(id),
  due_date TEXT NOT NULL, purpose TEXT NOT NULL, status TEXT NOT NULL,
  source_reference TEXT DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS quality_issues(
  id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER NOT NULL REFERENCES patients(id),
  field_name TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Missing',
  created_at TEXT NOT NULL, reviewed_at TEXT, review_outcome TEXT, review_note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, actor_role TEXT NOT NULL,
  action TEXT NOT NULL, entity_type TEXT NOT NULL, entity_id INTEGER NOT NULL, detail TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  display_name TEXT NOT NULL, role TEXT NOT NULL, password_hash TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);

-- Dashboard (analytics) tables -------------------------------------------------
CREATE TABLE IF NOT EXISTS app_config(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS cohorts(
  name TEXT PRIMARY KEY, prev_eligible INTEGER NOT NULL, prev_followup INTEGER NOT NULL,
  prev_complete INTEGER NOT NULL, curr_eligible INTEGER NOT NULL, curr_followup INTEGER NOT NULL,
  curr_complete INTEGER NOT NULL, sort_order INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS data_sources(
  name TEXT PRIMARY KEY, days_since INTEGER NOT NULL, limit_days INTEGER NOT NULL, sort_order INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS metric_registry(
  metric_id TEXT NOT NULL, name TEXT NOT NULL, formula TEXT NOT NULL, version TEXT NOT NULL,
  numerator TEXT NOT NULL, denominator TEXT NOT NULL, inclusion TEXT NOT NULL, exclusion TEXT NOT NULL,
  window TEXT NOT NULL, sources TEXT NOT NULL, modified TEXT NOT NULL, is_current INTEGER NOT NULL DEFAULT 0,
  is_previous_period INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(metric_id, version));
CREATE TABLE IF NOT EXISTS dashboard_cases(
  case_no INTEGER PRIMARY KEY, case_id TEXT UNIQUE NOT NULL, cohort TEXT NOT NULL REFERENCES cohorts(name),
  region TEXT NOT NULL, age_group TEXT NOT NULL, is_gap INTEGER NOT NULL, has_doc INTEGER NOT NULL,
  visit_days INTEGER, test_days INTEGER, outside_care INTEGER, conflict INTEGER,
  source_completeness INTEGER, overdue_days INTEGER, updated_days INTEGER);
CREATE TABLE IF NOT EXISTS case_reviews(
  case_no INTEGER PRIMARY KEY REFERENCES dashboard_cases(case_no), status TEXT NOT NULL DEFAULT 'Pending',
  feedback TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS case_review_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_no INTEGER NOT NULL REFERENCES dashboard_cases(case_no),
  entry TEXT NOT NULL, actor_role TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_cases_cohort ON dashboard_cases(cohort);
CREATE INDEX IF NOT EXISTS idx_log_case ON case_review_log(case_no, id DESC);
"""


def init_db() -> None:
    from . import seed  # local import avoids a cycle
    with connect() as c:
        c.executescript(SCHEMA)
        seed.seed_demo_users(c)
        seed.seed_patients(c)
        seed.seed_dashboard(c)
