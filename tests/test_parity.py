"""The backend seed + scoring must reproduce the ORIGINAL dashboard's browser-generated data exactly."""
import json
from pathlib import Path

REF = json.loads((Path(__file__).parent / "fixtures" / "reference.json").read_text(encoding="utf-8"))


def test_cases_and_scores_match_original_js(client, doctor):
    d = client.get("/api/dashboard", headers=doctor).json()
    assert len(d["cases"]) == len(REF["CASES"]) == 1120
    for got, exp in zip(d["cases"], REF["CASES"]):
        for k in ("id", "co", "rg", "ag", "gap", "doc"):
            assert got[k] == exp[k], (exp["id"], k)
        if exp["gap"]:
            for k in ("visit", "test", "outside", "conf", "src", "due", "upd", "sc"):
                assert got[k] == exp[k], (exp["id"], k)


def test_cohorts_and_totals_match(client, doctor):
    d = client.get("/api/dashboard", headers=doctor).json()
    assert d["cohorts"] == REF["CO"]
    for k in ("pe", "pf", "pc", "ce", "cf", "cc"):
        assert sum(c[k] for c in d["cohorts"]) == REF["TT"][k]
    assert d["config"] == REF["CFG"] and d["thresholds"] == REF["T"]


def test_seeded_reviews_match_original(client, doctor):
    d = client.get("/api/dashboard", headers=doctor).json()
    reviewed = [c for c in d["cases"] if c["gap"] and c["rv"]["fb"]]
    assert len(reviewed) == 14
    assert {c["id"] for c in reviewed} == {k for k, v in REF["REV"].items() if v["fb"]}
    ok = sum(c["rv"]["fb"] == "Correct gap" for c in reviewed if c["sc"]["t"] == "Likely real gap")
    assert (len(reviewed), ok) == (REF["agree"]["n"], REF["agree"]["ok"])


def test_registry_current_versions(client, doctor):
    d = client.get("/api/dashboard", headers=doctor).json()
    assert d["pv"] == {"FU": ["1.1", "1.1"], "DOC": ["1.1", "1.1"]}
    assert [v["v"] for v in d["registry"]["FU"]["vs"]] == ["1.0", "1.1"]
