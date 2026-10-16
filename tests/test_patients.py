def test_seeded_patients_and_metrics(client, doctor):
    items = client.get("/api/patients", headers=doctor).json()["items"]
    assert [p["patient_id"] for p in items] == ["DEMO-001", "DEMO-002", "DEMO-003", "DEMO-004"]
    m = client.get("/api/metrics", headers=doctor).json()
    assert m["patients"] == 4 and m["treatments"] == 4 and m["open_quality_issues"] == 5


def test_create_patient_flags_missing_followup(client, doctor):
    r = client.post("/api/patients", headers=doctor, json={"patient_id": "DEMO-100", "display_name": "Demo Patient X",
                    "age": 40, "department": "Cardiology", "condition_label": "Example"})
    assert r.status_code == 200
    d = client.get(f"/api/patients/{r.json()['id']}", headers=doctor).json()
    assert d["quality_issues"][0]["field_name"] == "followup.record"
    dup = client.post("/api/patients", headers=doctor, json={"patient_id": "DEMO-100", "display_name": "Dup Person",
                      "age": 1, "department": "Cardiology", "condition_label": "x1"})
    assert dup.status_code == 409


def test_patient_validation(client, doctor):
    bad = {"patient_id": "D", "display_name": "x", "age": 999, "department": "C", "condition_label": ""}
    assert client.post("/api/patients", headers=doctor, json=bad).status_code == 422


def test_treatment_and_followup_create_quality_issues(client, doctor):
    pid = client.get("/api/patients", headers=doctor).json()["items"][3]["id"]
    t = client.post(f"/api/patients/{pid}/treatments", headers=doctor, json={
        "treatment_date": "2026-10-14", "record_type": "Consultation", "description": "Recorded visit", "source_reference": ""})
    assert t.status_code == 200
    f = client.post(f"/api/patients/{pid}/followups", headers=doctor, json={
        "due_date": "2026-10-01", "purpose": "Past due", "status": "Scheduled", "source_reference": "REF-1"})
    assert f.status_code == 200
    d = client.get(f"/api/patients/{pid}", headers=doctor).json()
    assert any(i["field_name"].startswith("treatment:") for i in d["quality_issues"])
    assert d["followups"][0]["computed_status"] == "Overdue"       # Scheduled + past due date
    assert client.post(f"/api/patients/{pid}/treatments", headers=doctor, json={
        "treatment_date": "2026-10-14", "record_type": "Consultation", "description": "x1", "status": "Made up"}).status_code == 400
    assert client.post("/api/patients/9999/followups", headers=doctor, json={
        "due_date": "2026-10-01", "purpose": "xx"}).status_code == 404


def test_quality_review_flow_and_audit(client, reviewer):
    pid = client.get("/api/patients", headers=reviewer).json()["items"][0]["id"]
    issue = client.get(f"/api/patients/{pid}", headers=reviewer).json()["quality_issues"][0]["id"]
    assert client.post(f"/api/quality/{issue}/review", headers=reviewer, json={"outcome": "Maybe", "note": "xx"}).status_code == 400
    assert client.post(f"/api/quality/{issue}/review", headers=reviewer, json={"outcome": "Verified", "note": "checked source"}).json()["status"] == "Verified"
    d = client.get(f"/api/patients/{pid}", headers=reviewer).json()
    assert d["quality_issues"][0]["status"] == "Verified"
    assert any(a["action"] == "reviewed_quality_issue" for a in d["audit"])
    assert client.post("/api/quality/9999/review", headers=reviewer, json={"outcome": "Verified", "note": "xx"}).status_code == 404


def test_manager_read_only_on_patients(client, manager):
    patients = client.get("/api/patients", headers=manager)
    assert patients.status_code == 200
    patient_id = patients.json()["items"][0]["id"]
    detail = client.get(f"/api/patients/{patient_id}", headers=manager)
    assert detail.status_code == 200 and "treatments" in detail.json()
    assert client.post("/api/patients", headers=manager, json={"patient_id": "DEMO-200", "display_name": "No Way",
                       "age": 5, "department": "Cardiology", "condition_label": "xx"}).status_code == 403
    assert client.post("/api/quality/1/review", headers=manager, json={"outcome": "Verified", "note": "xx"}).status_code == 403
