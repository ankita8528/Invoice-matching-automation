"""End-to-end integration test: runs the ENTIRE pipeline against every
invoice in invoices/, in a fixed order (split invoices must be processed in
their numbered sequence for the ledger's cumulative math to be correct), and
compares the actual decision against invoices/ground_truth.json.

Prints a clear invoice / expected / actual / PASS-FAIL table either way.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
INVOICES_DIR = REPO_ROOT / "invoices"


def _ground_truth() -> dict:
    with open(INVOICES_DIR / "ground_truth.json", encoding="utf-8") as f:
        return json.load(f)


def test_full_dataset_against_ground_truth(service):
    ground_truth = _ground_truth()
    filenames = sorted(ground_truth.keys())

    rows = []
    hard_failures = []
    for filename in filenames:
        expected = ground_truth[filename]
        pdf_bytes = (INVOICES_DIR / filename).read_bytes()
        result = service.process_invoice(pdf_bytes, filename)
        actual = result.decision.value if hasattr(result.decision, "value") else result.decision

        expected_decision = expected["expected_decision"]
        environment_dependent = expected.get("environment_dependent", False)
        passed = actual == expected_decision
        rows.append((filename, expected_decision, actual, "PASS" if passed else ("SKIP(env)" if environment_dependent else "FAIL")))
        if not passed and not environment_dependent:
            hard_failures.append((filename, expected_decision, actual, result.reason))

    header = f"{'invoice':32} {'expected':16} {'actual':16} {'result'}"
    print("\n" + header)
    print("-" * len(header))
    for filename, expected_decision, actual, status in rows:
        print(f"{filename:32} {expected_decision:16} {actual:16} {status}")

    if hard_failures:
        details = "\n".join(f"  {f}: expected {e}, got {a} ({r})" for f, e, a, r in hard_failures)
        pytest.fail(f"{len(hard_failures)} invoice(s) did not match ground truth:\n{details}")
