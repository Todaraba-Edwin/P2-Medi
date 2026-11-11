"""rfp03_live_check의 eyak_label 시나리오 계획(네트워크 없음)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import rfp03_live_check as live  # noqa: E402


def test_eyak_label_plan_budget_is_small_and_non_dosage_section() -> None:
    p = live.plan("eyak_label")
    assert p["mode"] == "dry-run" and p["retries"] == 0
    assert p["total_http_cap"] == 5 and sum(p["per_service_budget"].values()) <= 5
    assert p["per_service_budget"]["dur-ingr"] == 0
    sections = [s["args"].get("section") for s in p["scenarios"] if s["tool"] == "get_label_section"]
    assert sections == [live.EYAK_SECTION] and live.EYAK_SECTION != "용법용량"


def test_default_plan_unchanged() -> None:
    p = live.plan()
    assert p["total_http_cap"] == live.TOTAL_CAP == 20 and "scenario" not in p
