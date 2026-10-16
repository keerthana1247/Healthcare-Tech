from .conftest import login


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_requires_token(client):
    for path in ("/api/dashboard", "/api/patients", "/api/metrics", "/api/audit", "/api/admin/users"):
        assert client.get(path).status_code == 401


def test_admin_settings_preflight_allows_put(client):
    response = client.options("/api/admin/settings", headers={
        "Origin": "http://localhost:8000",
        "Access-Control-Request-Method": "PUT",
        "Access-Control-Request-Headers": "authorization,content-type",
    })
    assert response.status_code == 200
    assert "PUT" in response.headers["access-control-allow-methods"]


def test_bad_token_rejected(client):
    assert client.get("/api/dashboard", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_each_seeded_account_authenticates_as_its_database_role(client):
    accounts = (
        ("doctor@demo.org", "DoctorDemo2026!", "doctor"),
        ("reviewer@demo.org", "ReviewerDemo2026!", "reviewer"),
        ("manager@demo.org", "ManagerDemo2026!", "manager"),
        ("admin@demo.org", "AdminDemo2026!", "administrator"),
    )
    for email, password, role in accounts:
        response = client.post("/api/auth/login", json={"email": email, "password": password, "role": role})
        assert response.status_code == 200
        assert response.json()["role"] == role


def test_wrong_password_wrong_role_and_unknown_account_are_rejected(client):
    wrong_password = client.post("/api/auth/login", json={
        "email": "doctor@demo.org", "password": "incorrect", "role": "doctor"
    })
    assert wrong_password.status_code == 401
    assert "active demo account" in wrong_password.json()["detail"]
    wrong_role = client.post("/api/auth/login", json={
        "email": "doctor@demo.org", "password": "DoctorDemo2026!", "role": "administrator"
    })
    assert wrong_role.status_code == 401
    assert "active demo account" in wrong_role.json()["detail"]
    unknown_email = client.post("/api/auth/login", json={
        "email": "unknown@demo.org", "password": "DoctorDemo2026!", "role": "doctor"
    })
    assert unknown_email.status_code == 401
    assert "active demo account" in unknown_email.json()["detail"]


def test_legacy_role_issuance_endpoints_are_removed(client):
    assert client.post("/api/auth/demo", json={"role": "administrator", "key": "demo123"}).status_code == 405
    assert client.post("/api/auth/demo-access", json={"role": "administrator"}).status_code == 422


def test_demo_access_compatibility_route_requires_valid_account_credentials(client):
    valid = {"email": "reviewer@demo.org", "password": "ReviewerDemo2026!", "role": "reviewer"}
    response = client.post("/api/auth/demo-access", json=valid)
    assert response.status_code == 200 and response.json()["role"] == "reviewer"
    invalid = {**valid, "password": "incorrect"}
    response = client.post("/api/auth/demo-access", json=invalid)
    assert response.status_code == 401
    assert "active demo account" in response.json()["detail"]


def test_role_permissions_are_enforced_by_api(client, doctor, reviewer, manager, administrator):
    patient = client.get("/api/patients", headers=doctor).json()["items"][0]
    issue_id = client.get(f"/api/patients/{patient['id']}", headers=reviewer).json()["quality_issues"][0]["id"]
    case = next(c for c in client.get("/api/dashboard", headers=reviewer).json()["cases"]
                if c["gap"] and c["rv"]["st"] == "Pending")
    review_url = f"/api/cases/{case['id']}/status"
    review_body = {"status": "Under Review", "note": ""}
    quality_url = f"/api/quality/{issue_id}/review"
    quality_body = {"outcome": "Verified", "note": "source checked"}
    followup_url = f"/api/patients/{patient['id']}/followups"
    followup_body = {"due_date": "2026-11-01", "purpose": "Routine review"}

    assert client.post(review_url, headers=doctor, json=review_body).status_code == 403
    assert client.post(quality_url, headers=doctor, json=quality_body).status_code == 403
    assert client.post(followup_url, headers=doctor, json=followup_body).status_code == 200
    assert client.post(review_url, headers=reviewer, json=review_body).status_code == 200
    assert client.post(followup_url, headers=reviewer, json=followup_body).status_code == 403
    assert client.get("/api/patients", headers=manager).status_code == 200
    assert client.post(followup_url, headers=manager, json=followup_body).status_code == 403
    assert client.get("/api/admin/users", headers=manager).status_code == 403
    assert client.get("/api/admin/users", headers=administrator).status_code == 200
    assert client.get("/api/patients", headers=administrator).status_code == 403
    assert client.post("/api/reports/exported", headers=doctor).status_code == 403
    assert client.post("/api/reports/exported", headers=manager).status_code == 200
    assert client.post("/api/reports/exported", headers=reviewer).status_code == 200
    assert client.post("/api/reports/exported", headers=administrator).status_code == 200


def test_admin_can_manage_accounts_settings_and_audit(client, administrator, manager, doctor):
    created = client.post("/api/admin/users", headers=administrator, json={
        "email": "new.reviewer@demo.org", "display_name": "New Reviewer", "role": "reviewer",
        "password": "NewReviewer2026!",
    })
    assert created.status_code == 201
    account_id = created.json()["id"]
    new_session = client.post("/api/auth/login", json={
        "email": "new.reviewer@demo.org", "password": "NewReviewer2026!", "role": "reviewer",
    })
    assert new_session.status_code == 200
    assert client.patch(f"/api/admin/users/{account_id}", headers=administrator,
                        json={"is_active": False}).status_code == 200
    assert client.get("/api/auth/me", headers={
        "Authorization": "Bearer " + new_session.json()["access_token"],
    }).status_code == 401
    assert client.post("/api/auth/login", json={
        "email": "new.reviewer@demo.org", "password": "NewReviewer2026!", "role": "reviewer",
    }).status_code == 401
    assert client.get("/api/admin/settings", headers=manager).status_code == 403
    original = client.get("/api/admin/settings", headers=administrator).json()
    changed = {**original, "min_cohort_size": original["min_cohort_size"] + 1}
    assert client.put("/api/admin/settings", headers=administrator, json=changed).json() == changed
    dashboard = client.get("/api/dashboard", headers=doctor).json()
    assert dashboard["config"]["minN"] == changed["min_cohort_size"]
    assert client.get("/api/audit", headers=administrator).status_code == 200


def test_last_active_administrator_cannot_be_demoted(client, administrator):
    account = next(x for x in client.get("/api/admin/users", headers=administrator).json()["items"]
                   if x["role"] == "administrator")
    assert client.patch(f"/api/admin/users/{account['id']}", headers=administrator,
                        json={"is_active": False}).status_code == 400


def test_admin_password_reset_invalidates_existing_user_sessions(client, administrator):
    created = client.post("/api/admin/users", headers=administrator, json={
        "email": "reset.user@demo.org", "display_name": "Reset User", "role": "doctor",
        "password": "InitialPassword2026!",
    })
    user_id = created.json()["id"]
    signed_in = client.post("/api/auth/login", json={
        "email": "reset.user@demo.org", "password": "InitialPassword2026!", "role": "doctor",
    }).json()
    assert client.patch(f"/api/admin/users/{user_id}", headers=administrator,
                        json={"password": "UpdatedPassword2026!"}).status_code == 200
    assert client.get("/api/auth/me", headers={
        "Authorization": "Bearer " + signed_in["access_token"],
    }).status_code == 401
    assert client.post("/api/auth/login", json={
        "email": "reset.user@demo.org", "password": "InitialPassword2026!", "role": "doctor",
    }).status_code == 401
    assert client.post("/api/auth/login", json={
        "email": "reset.user@demo.org", "password": "UpdatedPassword2026!", "role": "doctor",
    }).status_code == 200


def test_logout_invalidates_session(client, doctor):
    assert client.get("/api/auth/me", headers=doctor).json()["role"] == "doctor"
    assert client.post("/api/auth/logout", headers=doctor).status_code == 200
    assert client.get("/api/auth/me", headers=doctor).status_code == 401


def test_session_expiry(client, doctor):
    from backend import app as m
    tok = doctor["Authorization"][7:]
    m.SESSIONS[tok] = ("doctor", 0, 1)
    assert client.get("/api/auth/me", headers=doctor).status_code == 401


def test_sign_in_is_audited(client, manager):
    actions = [a["action"] for a in client.get("/api/audit", headers=manager).json()["items"]]
    assert "account_sign_in" in actions
