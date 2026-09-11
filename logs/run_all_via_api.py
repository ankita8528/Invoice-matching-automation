"""Processes every invoice in invoices/ through the LIVE running backend
(http://localhost:8000/api/decide), in ground-truth-file order, and prints a
PASS/FAIL/SKIP(env) table against invoices/ground_truth.json -- same shape as
the pytest integration test, but exercising the real HTTP server (so the
ledger, duplicate detection, and split-invoice sequencing all behave exactly
as they would for a real user driving this through the UI).
"""
import json
import sys
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
INVOICES_DIR = REPO_ROOT / "invoices"
API_BASE = "http://localhost:8000"

with open(INVOICES_DIR / "ground_truth.json", encoding="utf-8") as f:
    ground_truth = json.load(f)

filenames = sorted(ground_truth.keys())
rows = []

for filename in filenames:
    expected = ground_truth[filename]
    path = INVOICES_DIR / filename
    t0 = time.time()
    try:
        with open(path, "rb") as f:
            resp = requests.post(f"{API_BASE}/api/decide", files={"file": (filename, f, "application/pdf")}, timeout=180)
        elapsed = time.time() - t0
        if resp.status_code != 200:
            actual = f"HTTP{resp.status_code}"
            reason = resp.text[:150]
        else:
            data = resp.json()
            actual = data.get("decision")
            reason = data.get("reason", "")[:150]
    except Exception as exc:  # noqa: BLE001
        elapsed = time.time() - t0
        actual = "ERROR"
        reason = str(exc)[:150]

    expected_decision = expected["expected_decision"]
    environment_dependent = expected.get("environment_dependent", False)
    passed = actual == expected_decision
    status = "PASS" if passed else ("SKIP(env)" if environment_dependent else "FAIL")
    rows.append((filename, expected_decision, actual, status, round(elapsed, 1), reason))
    print(f"{filename:44} {expected_decision:16} {str(actual):16} {status:10} {elapsed:6.1f}s  {reason}", flush=True)

print()
print("=" * 100)
passed_count = sum(1 for r in rows if r[3] == "PASS")
skip_count = sum(1 for r in rows if r[3] == "SKIP(env)")
fail_count = sum(1 for r in rows if r[3] == "FAIL")
print(f"TOTAL: {len(rows)}  PASS: {passed_count}  SKIP(env): {skip_count}  FAIL: {fail_count}")

with open(REPO_ROOT / "logs" / "run_all_via_api_results.json", "w", encoding="utf-8") as f:
    json.dump(
        [{"file": r[0], "expected": r[1], "actual": r[2], "status": r[3], "seconds": r[4], "reason": r[5]} for r in rows],
        f,
        indent=2,
    )

sys.exit(1 if fail_count else 0)
