"""Server-side port of the dashboard's evidence-score rules (script.js `score()`).

Scores are REVIEW-PRIORITY values (0-100), never probabilities, and never clinical decisions.
"""
from __future__ import annotations
import math

DEFAULT_CFG = {
    "minN": 10, "hg": 15, "base": 50, "hi": 75, "lo": 45, "agreeMin": 10,
    "w": {"visit": 15, "labs": 10, "info": 10, "overdue": 15, "noRec": -20, "outside": -20, "lowSrc": -10, "conflict": -15},
}
DEFAULT_T = {"doc": 80, "pop": 10, "chg": 10}

REVIEW_STATUSES = ["Pending", "Under Review", "Verified", "Resolved", "Rejected"]
FEEDBACK_VALUES = ["Correct gap", "Wrong flag", "Data was missing"]


def js_round(x: float) -> int:
    """JavaScript Math.round (half rounds up), unlike Python's banker's rounding."""
    return math.floor(x + 0.5)


def clamp(x: float) -> int:
    return max(0, min(100, js_round(x)))


def score_case(p: dict, cfg: dict, fu_version: str) -> dict:
    """p keys: visit, test, doc, due, outside, conf, src (None allowed for visit/test/due)."""
    w = cfg["w"]
    up: list[str] = []
    dn: list[str] = []
    mi: list[str] = []
    s = cfg["base"]
    if p["visit"] is not None and p["visit"] <= 365:
        s += w["visit"]; up.append(f"Relevant visit recorded {p['visit']} days ago")
    if p["test"] is not None:
        s += w["labs"]; up.append("Related test result on file")
    if p["doc"]:
        s += w["info"]; up.append("Record has expected supporting information")
    else:
        mi.append("Supporting documentation incomplete")
    if p["due"] is not None and p["due"] > 0:
        s += w["overdue"]; up.append(f"Follow-up overdue by {p['due']} days under demo definition v{fu_version}")
    else:
        mi.append("Days overdue not calculable")
    if p["visit"] is None and p["test"] is None:
        s += w["noRec"]; dn.append("No relevant record in preceding 12 months (not proof care was not given)")
    if p["outside"]:
        s += w["outside"]; dn.append("Record suggests care may have occurred elsewhere — verify")
    if p["src"] < 70:
        s += w["lowSrc"]; dn.append(f"Low source completeness ({p['src']}%)")
    if p["conf"]:
        s += w["conflict"]; dn.append("Conflicting documentation between sources")
    known = sum(x is not None for x in (p["visit"], p["test"], p["due"]))
    if p["conf"] or known < 1:
        t = "Unclear"
    elif p["outside"]:
        t = "Outside-care suspected"
    elif s >= cfg["hi"]:
        t = "Likely real gap"
    elif (not p["doc"]) or s <= cfg["lo"]:
        t = "Likely documentation gap"
    else:
        t = "Unclear"
    return {"s": clamp(s), "up": up, "dn": dn, "mi": mi, "t": t}
