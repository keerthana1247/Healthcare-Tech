# MetricBridge Health

Clinical-quality analytics dashboard + patient care record workspace, backed by a FastAPI API and SQLite.
**Synthetic demo data only. Not for diagnosis, prescribing or real clinical use. Never enter real patient data.**

```
frontend/   index.html · script.js · style.css   (your dashboard, now API-driven)
            patients.html                         (Patient Care Records workspace)
backend/    app.py (routes/auth) · dashboard.py (data assembly + review workflow)
            scoring.py (evidence-score rules) · seed.py (synthetic data) · db.py (SQLite schema)
tests/      pytest suite · tests/e2e (headless browser checks) · tests/fixtures/reference.json
data/       metricbridge.db is created here on first start (git-ignored)
```

One server serves both the API (`/api/*`) and the front end (`/`): no CORS or second port to manage.

## Run it (VS Code)

1. Install **Python 3.10+** (and optionally Node 18+ for the browser checks). In VS Code: *File → Open Folder…* → `MetricBridge_Health`. Install the recommended **Python** extension.
2. Open a terminal (*Terminal → New Terminal*) and create the environment.

   macOS / Linux:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements-dev.txt
   ```
   Windows (PowerShell):
   ```powershell
   py -m venv .venv
   .venv\Scripts\Activate.ps1      # if blocked: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
   pip install -r requirements-dev.txt
   ```
3. `Ctrl/Cmd+Shift+P` → **Python: Select Interpreter** → pick the `.venv` one.
4. Start the server: press **F5** and choose *MetricBridge: run server (reload)*, or run
   ```bash
   python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
   ```
5. Open **http://127.0.0.1:8000** and select the role matching your demo account. API docs: http://127.0.0.1:8000/docs

### Local demo accounts

These four accounts are created on first start if the corresponding email is not already present. Passwords are stored as salted PBKDF2 hashes. The login role selector must match the account's stored role.

| Role | Email | Password |
|---|---|---|
| Doctor / Care Team Member | `doctor@demo.org` | `DoctorDemo2026!` |
| Reviewer / Data Quality Reviewer | `reviewer@demo.org` | `ReviewerDemo2026!` |
| Manager / Analyst | `manager@demo.org` | `ManagerDemo2026!` |
| Administrator | `admin@demo.org` | `AdminDemo2026!` |

Change a password or access state in **User & Access** as an administrator. Existing account passwords and roles are not reset on server restart.

Always use that address; don't double-click `index.html` (the page needs the API on the same origin).

## Roles (simulated, enforced by the API)

| Role | Dashboard | Case-level data | Review actions | Audit log |
|---|---|---|---|---|
| Doctor | yes | yes | Patient/treatment/follow-up workflows | no |
| Reviewer | yes | yes | Case and missing-data review | yes |
| Manager / Analyst | yes | Dashboard cases: **no** (aggregate-only; IDs, evidence and notes withheld); Patient Records: read-only | no (read-only) | yes |
| Administrator | yes | yes | User/access administration, selected configuration, audit review | yes |

The API checks account role for each session and each protected write. Sessions are in-memory (8 h) and cleared on server restart; disabling or changing an account's role invalidates its active sessions. The dashboard and Patient Records page share one session. This is local prototype authentication, not production identity or security.
There is no shared demo access key. The old `POST /api/auth/demo` key-based route and role-only `demo-access` login are not supported; the compatibility alias requires the same valid account credentials as `/api/auth/login`.

## What is connected to the API

| Feature | Endpoint(s) |
|---|---|
| Account sign-in / log out | `POST /api/auth/login` and credential-checked compatibility alias `POST /api/auth/demo-access` (JSON: `email`, `password`, `role`); `POST /api/auth/logout`; `GET /api/auth/me` |
| Dashboard data (cohorts, sources, metric registry, thresholds, cases + scores) | `GET /api/dashboard` |
| Case review: status + feedback with notes and history | `POST /api/cases/{id}/status`, `/feedback` |
| CSV export audit trail | `POST /api/reports/exported` |
| Audit Log page (manager/reviewer/administrator) | `GET /api/audit` |
| Live patient-record counts on Overview | `GET /api/metrics` |
| Patient Records: list, detail, add patient/treatment/follow-up, missing-data review | `/api/patients…`, `/api/quality/{id}/review` |
| Administrator: user/access management | `/api/admin/users` (create, update role, password, and active state) |
| Administrator: selected system settings | `/api/admin/settings` (trust thresholds and minimum cohort size only) |

Evidence scores are computed **server-side** (`backend/scoring.py`) using the same rules as your original `score()`. They are review-priority values, not probabilities or clinical decisions.

## Tests

```bash
python -m pytest -q                         # Python API and authorization tests
cd tests/e2e && npm install && cd ../..     # once
python scripts/run_e2e.py                   # headless browser checks on a throwaway server + DB
```
`tests/test_parity.py` proves the backend reproduces your original dashboard's data and scores exactly. The fixture was produced by running your original `script.js` (`scripts/export_reference.js`).

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `METRICBRIDGE_DB` | `data/metricbridge.db` | SQLite file |

Administrator settings can change documentation, population, change, and hidden-gap thresholds plus minimum cohort size. Scoring weights and reporting dates remain fixed. To reset the demo database, stop the server and use `python scripts/reset_db.py`; this resets application data and demo accounts to the documented initial credentials.

## Troubleshooting

* **`ModuleNotFoundError: backend`** — run from the project root (the folder containing `backend/`).
* **Port busy** — use `--port 8001` and open that address.
* **Login button does nothing / "Request failed"** — you opened the HTML file directly, or the server isn't running.
* **"Session expired"** — the server restarted; sign in again.
* **Different font offline** — Inter is loaded from Google Fonts; system fonts are the fallback.

## Known limits (prototype)

Demo accounts and salted password hashes, in-memory sessions, no rate limiting/HTTPS/encryption at rest, single-node SQLite. Production use needs real identity, hardened audit storage, and privacy/compliance review.
