import os, sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Fresh seeded SQLite database per test."""
    monkeypatch.setenv("METRICBRIDGE_DB", str(tmp_path / "test.db"))
    monkeypatch.delenv("METRICBRIDGE_DEMO_KEY", raising=False)
    monkeypatch.delenv("METRICBRIDGE_REQUIRE_KEY", raising=False)
    from fastapi.testclient import TestClient
    from backend import app as app_module
    app_module.SESSIONS.clear()
    with TestClient(app_module.app) as c:   # runs lifespan -> init_db()
        yield c


def login(client, role="doctor"):
    accounts = {
        "doctor": ("doctor@demo.org", "DoctorDemo2026!"),
        "reviewer": ("reviewer@demo.org", "ReviewerDemo2026!"),
        "manager": ("manager@demo.org", "ManagerDemo2026!"),
        "administrator": ("admin@demo.org", "AdminDemo2026!"),
    }
    email, password = accounts[role]
    r = client.post("/api/auth/login", json={"email": email, "password": password, "role": role})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


@pytest.fixture()
def doctor(client):
    return login(client, "doctor")


@pytest.fixture()
def manager(client):
    return login(client, "manager")


@pytest.fixture()
def reviewer(client):
    return login(client, "reviewer")


@pytest.fixture()
def administrator(client):
    return login(client, "administrator")
