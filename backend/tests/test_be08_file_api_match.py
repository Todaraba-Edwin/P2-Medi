"""BE-08 파일·API 일치율 관찰 스크립트 시험(2026-11-18). 합성 사전·소규모 SQLite·가짜 DUR 함수만 쓴다(공공 API·원격 DB·LLM 호출 0)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "evaluation", Path(__file__).resolve().parent / "e2e"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import file_api_match as F  # noqa: E402
import sealed_guard as G  # noqa: E402
from golden_synth import SOURCE_INGR, DurResult, golden_conn, golden_dict  # noqa: E402

from app.agent.tools.context import ToolContext  # noqa: E402

COLD, AZI, T500 = "타이레놀콜드-에스정", "이지렉트정1.0밀리그램", "타이레놀정500밀리그람"
PAIR = {"id": "p1", "drugs": [AZI, COLD], "age": None, "pregnant": False}
PREG = {"id": "g1", "drugs": [T500], "age": None, "pregnant": True}


def test_dry_run_counts_planned_calls_by_the_tool_rules_without_any_call():
    res = F.dry_run([PAIR, PREG, {"id": "u1", "drugs": ["없는약XYZ"], "age": None, "pregnant": True}], golden_dict())
    by = {r["id"]: r for r in res["items"]}
    # 이지렉트(D 코드 1개) × 콜드-에스(D 코드 3개 중 앞 2개, 약당 상한 MAX_API_CODES_PER_DRUG) = 2회
    assert by["p1"]["calls"] == {"pair": 2, "pregnancy": 0, "age": 0} and by["g1"]["calls"]["pregnancy"] == 1
    assert by["u1"]["identified"] == 0 and by["u1"]["total"] == 0  # 식별 못 한 약은 호출 없음
    assert res["planned_calls_total"] == 3 and res["inputs_without_api_call"] == 1 and res["mode"] == "dry-run"
    assert COLD not in json.dumps(res, ensure_ascii=False)  # 약 이름을 남기지 않는다


def _ctx(pair_rows: bool) -> tuple[ToolContext, list[str]]:
    seen: list[str] = []

    def pair(a: str, b: str) -> DurResult:
        seen.append("pair")
        return DurResult(ok=True, kind="usjnt", level="ingr", rows=[], source_name=SOURCE_INGR, queried_at_utc="2026-11-18T00:00:00Z")

    def single(code: str) -> DurResult:
        seen.append("single")
        return DurResult(ok=True, kind="pregnancy", level="ingr", rows=[], source_name=SOURCE_INGR, queried_at_utc="2026-11-18T00:00:00Z")

    counter = {"calls": 0, "refused": 0}
    ctx = ToolContext(drug_dict=golden_dict(), conn_factory=golden_conn, api_enabled=True, api_pair_fn=F.capped(pair, counter, 99),
                      api_age_fn=F.capped(single, counter, 99), api_pregnancy_fn=F.capped(single, counter, 99))
    return ctx, seen


def test_execute_tallies_flags_into_a_match_rate_and_keeps_no_names():
    ctx, seen = _ctx(True)
    res = F.execute([PAIR, PREG], ctx, max_calls=99)
    assert res["mode"] == "execute" and len(seen) >= 1
    total = sum(res["flags"].get(f, 0) for f in F.MATCH_FLAGS)
    assert res["match_rate"]["n"] == total and res["match_rate"]["k"] == res["flags"].get("API_SAME", 0)
    raw = json.dumps(res, ensure_ascii=False)
    assert COLD not in raw and AZI not in raw and "9장 지표 아님" in res["note"]


SIMPLE_PAIR = {"id": "s1", "drugs": [AZI, T500], "age": None, "pregnant": False}  # 두 약 모두 DUR 코드 1개 → 쌍 호출 1회


@pytest.mark.parametrize("cap,flags,calls,refused", [(9, {"API_SAME": 1}, 1, 0), (0, {"API_FAIL": 1}, 0, 1)])
def test_call_cap_refuses_extra_calls_and_records_them_as_not_compared(cap, flags, calls, refused):
    counter = {"calls": 0, "refused": 0}

    def pair(a: str, b: str) -> DurResult:
        return DurResult(ok=True, kind="usjnt", level="ingr", rows=[], source_name=SOURCE_INGR)

    ctx = ToolContext(drug_dict=golden_dict(), conn_factory=golden_conn, api_enabled=True, api_pair_fn=F.capped(pair, counter, cap))
    res = F.execute([SIMPLE_PAIR], ctx, max_calls=cap, counter=counter)
    assert res["flags"] == flags and res["api_calls"] == calls and res["api_calls_refused_by_cap"] == refused
    assert res["match_rate"]["k"] == res["match_rate"]["n"] == calls  # 상한으로 못 부른 쌍은 분모에서 빠진다


def test_sealed_input_is_refused(tmp_path):
    p = tmp_path / "x.SEALED.jsonl"
    p.write_text('{"id": "t", "drugs": ["a"]}\n', encoding="utf-8")
    with pytest.raises(G.SealedAccessError):
        F.load_inputs(p)


def test_default_inputs_are_the_dev_judgment_items_only():
    if not F.DEV_SET.exists():
        pytest.skip("개발셋 없음")
    rows = F.load_inputs(None)
    assert len(rows) == 35 and all(r["id"].startswith("dev-") and r["drugs"] for r in rows)


def test_execute_needs_yes_and_a_call_cap(capsys):
    assert F.main(["--execute"]) == 2 and F.main(["--execute", "--yes"]) == 2
    assert "실행하지 않았다" in capsys.readouterr().out
