"""Audit live API reads without modifying production or printing record contents.

Run: backend/.venv/bin/python scripts/audit_production.py
Authentication only creates a local MIS login session. All dataset requests are GETs.
"""
import collections
import csv
import io
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.catalog import SOURCES
from app.config import settings
from app.production_sources import PROJECTIONS


def main():
    if not settings().source_database_url:
        raise SystemExit("Production connection is required; refusing to audit a snapshot.")
    access = (ROOT / "local-access.txt").read_text()
    results, charts, problems = [], [], []
    with httpx.Client(base_url="http://127.0.0.1:8001/api", timeout=90,
                      headers={"X-Requested-With": "PolarisMIS"}) as client:
        client.post("/auth/login", json={
            "username": re.search(r"Username: (.+)", access)[1],
            "password": re.search(r"Password: (.+)", access)[1],
        }).raise_for_status()
        options = client.get("/filters").raise_for_status().json()
        period = {"from_date": options["data_range"]["first_date"],
                  "to_date": options["data_range"]["last_date"]}

        def check(path, extra=None, scenario="all available dates", expected=(200,)):
            start = time.monotonic()
            response = client.get(path, params=period | (extra or {}))
            result = {"path": path, "scenario": scenario, "status": response.status_code,
                      "seconds": round(time.monotonic() - start, 2)}
            body = response.json() if "json" in response.headers.get("content-type", "") else {}
            if "total" in body:
                result["total"] = body["total"]
            if response.status_code != 200:
                result["reason"] = body.get("detail", "Request failed")
            results.append(result)
            if response.status_code not in expected:
                problems.append(result)
            return response, body

        for path in ["/dashboard", "/filters", "/calendar", "/internship-summary", "/coverage"]:
            check(path)
        manifest = client.get("/charts/manifest").raise_for_status().json()
        for view, section in manifest["sections"].items():
            tabs = {t["id"] for t in section["tabs"]} | {c["tab"] for c in section["charts"]}
            for tab in sorted(tabs):
                _, body = check(f"/charts/{view}/{tab}")
                for chart in body.get("charts", []):
                    charts.append({"location": f"{view} → {tab}", "title": chart["title"],
                                   "status": chart["status"], "rows": len(chart["rows"]),
                                   "note": chart.get("note", "")})
            print("Audited", view, flush=True)
        for source in list(SOURCES) + list(PROJECTIONS):
            check(f"/records/{source}", {"page_size": 1}, expected=(200, 409))
        for metric in ["att", "ontime", "missed", "assess", "score", "slaIssue", "taskOn"]:
            check("/charts/trends/overview", {"metric": metric}, scenario=f"metric={metric}")
        for mode in ["absolute", "unique"]:
            check("/charts/trends/overview", {"metric": "att", "attendance_heatmap_mode": mode},
                  scenario=f"attendance heatmap={mode}")
        semester = next((s for s in options["semesters"] if "3" in s["name"]), None)
        batch = next((b for b in options["batches"] if semester and semester["id"] in b.get("semester_ids", [])), None)
        if semester and batch:
            scope = {"semester_id": semester["id"], "batch_id": batch["id"]}
            for path in ["/dashboard", "/charts/attendance/matrix", "/charts/ojt/overview",
                         "/records/ojt_allocations", "/records/ojt_evaluations", "/records/internship_placements"]:
                check(path, scope, scenario="semester + batch")
            for source in PROJECTIONS:
                _, record = check(f"/records/{source}", scope, scenario="filtered CSV reference")
                response, _ = check(f"/records/{source}/export", scope, scenario="filtered CSV")
                count = len(list(csv.reader(io.StringIO(response.text)))) - 1
                if count != record.get("total"):
                    problems.append({"path": source, "reason": "CSV total mismatch"})
        if options["mentors"]:
            for path in ["/dashboard", "/charts/mentors/feedback", "/charts/trends/overview"]:
                check(path, {"mentor_id": options["mentors"][0]["id"]}, scenario="mentor filter")
        client.post("/auth/logout")
    counts = dict(collections.Counter(c["status"] for c in charts))
    report = {"checked_at": datetime.now(UTC).isoformat(), "period": period,
              "chart_counts": counts, "requests": results, "charts": charts, "unexpected_failures": problems}
    folder = ROOT / "reports"
    folder.mkdir(exist_ok=True)
    (folder / "production-audit.json").write_text(json.dumps(report, indent=2))
    lines = ["# Production dashboard audit", "", f"Checked: {report['checked_at']}",
             f"Period: {period['from_date']} to {period['to_date']}", "",
             f"Requests: {len(results)}; unexpected failures: {len(problems)}; charts: {counts}", "",
             "All dataset requests use production. A source-unavailable response is recorded separately from an unexpected failure.", "",
             "| Location | Chart | Status | Data rows | Explanation |", "|---|---|---|---:|---|"]
    for chart in charts:
        lines.append("| " + " | ".join(str(chart[k]).replace("|", "/").replace("\n", " ")
                     for k in ["location", "title", "status", "rows", "note"]) + " |")
    (folder / "production-audit.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"requests": len(results), "charts": counts, "unexpected_failures": problems}, indent=2))
    return bool(problems)


if __name__ == "__main__":
    sys.exit(main())
