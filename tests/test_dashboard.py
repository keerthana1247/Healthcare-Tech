def _first_gap(d, **kw):
    return next(c for c in d["cases"] if c["gap"] and all(c["rv"][k] == v for k, v in kw.items()))


def test_manager_payload_is_aggregate_only(client, manager):
    d = client.get("/api/dashboard", headers=manager).json()
    assert d["role"] == "manager"
    assert all(c["id"] is None for c in d["cases"])
    gaps = [c for c in d["cases"] if c["gap"]]
    assert gaps and all(set(c["sc"]) == {"t"} and c["rv"]["log"] == [] for c in gaps)
    for forbidden in ("visit", "test", "due", "src", "upd"):
        assert all(forbidden not in c for c in d["cases"])


def test_manager_cannot_review(client, manager, doctor):
    cid = _first_gap(client.get("/api/dashboard", headers=doctor).json(), st="Pending")["id"]
    r = client.post(f"/api/cases/{cid}/status", headers=manager, json={"status": "Under Review", "note": ""})
    assert r.status_code == 403
    r = client.post(f"/api/cases/{cid}/feedback", headers=manager, json={"feedback": "Correct gap", "note": ""})
    assert r.status_code == 403


def test_status_change_persists_and_logs(client, reviewer):
    cid = _first_gap(client.get("/api/dashboard", headers=reviewer).json(), st="Pending")["id"]
    r = client.post(f"/api/cases/{cid}/status", headers=reviewer, json={"status": "Under Review", "note": "checking"})
    assert r.status_code == 200 and r.json()["st"] == "Under Review"
    assert "reviewer: status Pending → Under Review — checking" in r.json()["log"][0]
    d = client.get("/api/dashboard", headers=reviewer).json()
    c = next(x for x in d["cases"] if x["id"] == cid)
    assert c["rv"]["st"] == "Under Review" and len(c["rv"]["log"]) == 1


def test_status_rules(client, reviewer):
    cid = _first_gap(client.get("/api/dashboard", headers=reviewer).json(), st="Pending")["id"]
    url = f"/api/cases/{cid}/status"
    assert client.post(url, headers=reviewer, json={"status": "Pending", "note": ""}).status_code == 400     # unchanged
    assert client.post(url, headers=reviewer, json={"status": "Resolved", "note": ""}).status_code == 400    # note required
    assert client.post(url, headers=reviewer, json={"status": "Rejected", "note": "  "}).status_code == 400
    assert client.post(url, headers=reviewer, json={"status": "Bogus", "note": "x"}).status_code == 400
    assert client.post(url, headers=reviewer, json={"status": "Resolved", "note": "closed"}).status_code == 200


def test_feedback_rules_and_auto_under_review(client, reviewer):
    cid = _first_gap(client.get("/api/dashboard", headers=reviewer).json(), st="Pending")["id"]
    url = f"/api/cases/{cid}/feedback"
    assert client.post(url, headers=reviewer, json={"feedback": "Wrong flag", "note": ""}).status_code == 400
    assert client.post(url, headers=reviewer, json={"feedback": "Nope", "note": "x"}).status_code == 400
    r = client.post(url, headers=reviewer, json={"feedback": "Correct gap", "note": ""})
    assert r.status_code == 200 and r.json()["fb"] == "Correct gap" and r.json()["st"] == "Under Review"


def test_reviewer_role_can_review(client, reviewer):
    d = client.get("/api/dashboard", headers=reviewer).json()
    cid = _first_gap(d, st="Pending")["id"]
    assert client.post(f"/api/cases/{cid}/status", headers=reviewer, json={"status": "Verified", "note": ""}).status_code == 200


def test_invalid_and_non_gap_cases(client, reviewer):
    d = client.get("/api/dashboard", headers=reviewer).json()
    non_gap = next(c for c in d["cases"] if not c["gap"])["id"]
    body = {"status": "Verified", "note": ""}
    assert client.post(f"/api/cases/{non_gap}/status", headers=reviewer, json=body).status_code == 400
    assert client.post("/api/cases/SYN-9999/status", headers=reviewer, json=body).status_code == 404
    assert client.post("/api/cases/bad-id/status", headers=reviewer, json=body).status_code == 400


def test_review_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("METRICBRIDGE_DB", str(tmp_path / "persist.db"))
    from fastapi.testclient import TestClient
    from backend import app as m
    from .conftest import login
    with TestClient(m.app) as c:
        h = login(c, "reviewer")
        cid = _first_gap(c.get("/api/dashboard", headers=h).json(), st="Pending")["id"]
        c.post(f"/api/cases/{cid}/status", headers=h, json={"status": "Under Review", "note": "persist"})
    with TestClient(m.app) as c2:           # new app lifespan = "server restart"; must not reseed or lose data
        h = login(c2, "reviewer")
        d = c2.get("/api/dashboard", headers=h).json()
        assert len(d["cases"]) == 1120
        assert next(x for x in d["cases"] if x["id"] == cid)["rv"]["st"] == "Under Review"


def test_review_actions_are_audited_for_manager(client, reviewer, manager):
    cid = _first_gap(client.get("/api/dashboard", headers=reviewer).json(), st="Pending")["id"]
    client.post(f"/api/cases/{cid}/status", headers=reviewer, json={"status": "Under Review", "note": ""})
    items = client.get("/api/audit", headers=manager).json()["items"]
    assert any(a["action"] == "case_status_changed" and cid in a["detail"] for a in items)


def test_audit_forbidden_for_doctor(client, doctor):
    assert client.get("/api/audit", headers=doctor).status_code == 403


def test_export_logged(client, manager):
    assert client.post("/api/reports/exported", headers=manager).status_code == 200
    assert any(a["action"] == "exported_report_csv" for a in client.get("/api/audit", headers=manager).json()["items"])


def test_static_frontend_served(client):
    assert "MetricBridge Health" in client.get("/").text
    assert client.get("/script.js").status_code == 200
    assert client.get("/style.css").status_code == 200
    assert "Patient" in client.get("/patients.html").text
