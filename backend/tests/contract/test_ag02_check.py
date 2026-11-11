"""AG-02 `check_contraindications` 계약: 상태 혼합, 코드 없음, 제형 불일치, 쌍 조합, 성분 단위, 성분 중복, API 4경우, 평가 모드."""

from __future__ import annotations

import pytest
from ag02_synth import APAP, IBU, WAR, ctx

from app.agent.renderer import render
from app.agent.tools.contract import check_items
from app.agent.tools.registry import invoke
from app.tools.dur import DurResult, DurRow


def run(drugs, **kw):
    c = ctx(**{k: kw.pop(k) for k in ("api_enabled", "api_pair_fn") if k in kw})
    args = {"drugs": drugs, **kw}
    out = invoke("check_contraindications", args, c)
    assert "error" not in out, out
    assert out["contract_violations"] == []
    return out


def pick(out, kind, status=None):
    return [i for i in out["items"] if i["kind"] == kind and (status is None or i["status"] == status)]


def test_mixed_statuses_found_notlisted_unidentified():
    out = run([{"name": "이부정"}, {"name": "와파린정"}, {"name": "미등록정"}], pregnancy=True)
    assert {i["status"] for i in out["items"]} == {"FOUND", "NOT_LISTED", "UNIDENTIFIED"}
    (pair,) = pick(out, "contra_pair", "FOUND")
    assert pair["source_kind"] == "FILE" and pair["as_of"] == "2026-07-31" and pair["matches"][0]["row_evidence_id"]
    assert {tuple(i["flags"]) for i in pick(out, "contra_pair", "UNIDENTIFIED")} == {("PAIR_NOT_CHECKED",)}
    assert len(pick(out, "contra_pair", "UNIDENTIFIED")) == 2  # 이부정-미등록정, 와파린정-미등록정
    preg = {i["drugs"][0]: i["status"] for i in pick(out, "pregnancy")}
    assert preg == {"이부정": "NOT_LISTED", "와파린정": "FOUND", "미등록정": "UNIDENTIFIED"}
    (nolink,) = pick(out, "identify")
    assert nolink["status"] == "UNIDENTIFIED" and "CODE_NOT_LINKED" in nolink["flags"] and nolink["source"] is None


def test_renderer_consumes_items():
    out = run([{"name": "이부정"}, {"name": "와파린정"}])
    res = render(out["items"], [])
    assert res.detail and res.detail[0]["status"] == "FOUND" and res.detail[0]["source_kind"] == "FILE"
    assert not [w for w in res.warnings if w["code"] == "MISSING_SOURCE_KIND"]


def test_pair_combinations_n_choose_2():
    drugs = [{"name": "타이레놀정"}, {"name": "이부정"}, {"name": "와파린정"}, {"name": "전문정"}]
    out = run(drugs)
    assert len(pick(out, "contra_pair")) == 6
    out3 = run(drugs[:3])
    assert len(pick(out3, "contra_pair")) == 3


def test_no_code_is_never_not_listed():
    out = run([{"name": "미등록정"}, {"name": "이부정"}], pregnancy=True, age={"value": 5, "unit": "세"})
    mine = [i for i in out["items"] if "미등록정" in i["drugs"]]
    assert len(mine) >= 3 and all(i["status"] == "UNIDENTIFIED" for i in mine)  # 약 식별 + 임부 + 연령 + 쌍


def test_component_only_usable_only_for_matching_form():
    # 에이캡슐: route_only → 판정 안 함 / 파뚜정: match → 판정 / 미네정: mismatch → 판정 안 함
    out = run([{"name": "에이캡슐"}, {"name": "파뚜정"}, {"name": "미네정"}], age={"value": 5, "unit": "세"})
    by = {i["drugs"][0]: i for i in pick(out, "age") + pick(out, "identify")}
    assert by["에이캡슐"]["status"] == "UNIDENTIFIED" and {"CODE_NOT_LINKED", "REFERENCE_ONLY"} <= set(by["에이캡슐"]["flags"])
    assert any("이 제품 판정 아님" in n for n in by["에이캡슐"]["notes"])
    assert by["미네정"]["status"] == "UNIDENTIFIED" and "REFERENCE_ONLY" in by["미네정"]["flags"]
    age = [i for i in pick(out, "age") if i["drugs"] == ["파뚜정"]]
    assert len(age) == 1 and age[0]["status"] == "FOUND" and age[0]["cause_codes"] == [APAP]  # 원인 성분코드(PRD-09-05)
    assert not any(i["status"] in ("FOUND", "NOT_LISTED") for i in out["items"] if i["drugs"] in (["에이캡슐"], ["미네정"]))


def test_ingredient_name_input_judged_by_code_as_is():
    out = run([{"name": "아세트아미노펜"}, {"name": "와파린"}], pregnancy=True)
    assert out["input_units"] and set(out["input_units"].values()) == {"ingredient"}
    assert {i["status"] for i in pick(out, "pregnancy")} == {"NOT_LISTED", "FOUND"}


def test_product_wins_over_same_name_ingredient():
    out = run([{"name": "이부프로펜"}, {"name": "와파린정"}])
    assert set(out["input_units"].values()) == {"product"}
    assert pick(out, "contra_pair", "FOUND")


def test_ambiguous_name_asks_instead_of_guessing():
    out = run([{"name": "감기정"}, {"name": "와파린정"}])
    (amb,) = pick(out, "identify")
    assert amb["status"] == "UNIDENTIFIED" and amb["flags"] == ["AMBIGUOUS_NAME"] and len(amb["candidates"]) == 2
    assert [i["status"] for i in pick(out, "contra_pair")] == ["UNIDENTIFIED"]
    # item_seq로 고르면 판정한다
    out2 = run([{"name": "감기정", "item_seq": "100000011"}, {"name": "와파린정"}])
    assert pick(out2, "contra_pair", "FOUND")


def test_unknown_name_is_unidentified_not_listed():
    out = run([{"name": "zzzqqq"}, {"name": "이부정"}])
    assert pick(out, "contra_pair")[0]["status"] == "UNIDENTIFIED"


def test_duplicate_ingredient_last_and_after_pairs():
    out = run([{"name": "타이레놀정"}, {"name": "파뚜정"}, {"name": "이부정"}])
    dup = pick(out, "dup_ingredient")
    assert len(dup) == 1 and dup[0]["cause_codes"] == [APAP] and out["items"][-1] is dup[0]


# ------------------------------------------------------------------ API 병기 4경우
def _row(text="API 병용금기 합성 문구"):
    return DurRow(kind="usjnt", level="ingr", content=text, notification_date="2026-01-01", evidence_id="abcdef012345")


def _res(ok=True, rows=None, partial=None):
    return DurResult(ok=ok, kind="usjnt", level="ingr", rows=rows or [], source_name="식약처 DUR 성분정보", queried_at_utc="2026-11-10T12:00:00Z",
                     request_hashes=["h1"], partial=partial)


PAIR_FOUND = [{"name": "이부정"}, {"name": "와파린정"}]       # 파일 FOUND
PAIR_NONE = [{"name": "타이레놀정"}, {"name": "이부정"}]       # 파일 NOT_LISTED


def _flags(out):
    return {f for i in out["items"] if i["kind"] == "contra_pair" for f in i["flags"]}


def test_api_same():
    out = run(PAIR_FOUND, api_pair_fn=lambda a, b: _res(rows=[_row()]))
    assert "API_SAME" in _flags(out)
    found = pick(out, "contra_pair", "FOUND")
    assert {i["source_kind"] for i in found} == {"FILE", "API_DIRECT"}  # 두 출처 모두 기록
    api = [i for i in found if i["source_kind"] == "API_DIRECT"][0]
    assert api["queried_at_utc"] == "2026-11-10T12:00:00Z" and api["dataset_key"] == "dur_ingr"
    assert any(i["as_of"] == "2026-07-31" for i in found)


def test_file_only():
    out = run(PAIR_FOUND, api_pair_fn=lambda a, b: _res(rows=[]))
    assert "FILE_ONLY" in _flags(out)
    (f,) = pick(out, "contra_pair", "FOUND")
    assert any("해제되었을 수" in n and "약사·의사" in n for n in f["notes"]) and f["status"] == "FOUND"  # 파일 판정은 그대로


def test_api_only():
    out = run(PAIR_NONE, api_pair_fn=lambda a, b: _res(rows=[_row()]))
    assert "API_ONLY" in _flags(out)
    file_item = [i for i in pick(out, "contra_pair") if i["source_kind"] == "FILE"][0]
    assert file_item["status"] == "NOT_LISTED"                         # 한쪽을 확정하지 않는다
    assert any("새로 지정되었을 수" in n and "안전하다는 뜻이 아니" in n for n in file_item["notes"])
    assert any(i["source_kind"] == "API_DIRECT" and i["status"] == "FOUND" for i in out["items"])


def test_api_fail_keeps_file_answer():
    out = run(PAIR_FOUND, api_pair_fn=lambda a, b: _res(ok=False))
    assert "API_FAIL" in _flags(out)
    (f,) = pick(out, "contra_pair", "FOUND")
    assert any("실시간 확인을 하지 못함" in n for n in f["notes"])


def test_api_exception_becomes_api_fail():
    def boom(a, b):
        raise TimeoutError("secret-url")
    out = run(PAIR_FOUND, api_pair_fn=boom)
    assert "API_FAIL" in _flags(out) and "secret" not in str(out)


def test_api_pair_incomplete_when_one_side_fails_or_missing():
    out = run(PAIR_FOUND, api_pair_fn=lambda a, b: _res(ok=False, partial="B"))
    assert "API_PAIR_INCOMPLETE" in _flags(out) and pick(out, "contra_pair", "FOUND")[0]["status"] == "FOUND"
    calls = []
    out2 = run([{"ingredient_code": IBU}, {"ingredient_code": WAR}], api_pair_fn=lambda a, b: calls.append((a, b)) or _res())  # API 코드 없는 입력
    assert "API_PAIR_INCOMPLETE" in _flags(out2) and calls == []
    assert pick(out2, "contra_pair", "FOUND")


def test_eval_mode_api_off_calls_nothing():
    calls = []
    out = run(PAIR_FOUND, api_enabled=False, api_pair_fn=lambda a, b: calls.append(1) or _res(rows=[_row()]))
    assert calls == [] and not _flags(out) and all(i["source_kind"] == "FILE" for i in out["items"] if i["status"] != "UNIDENTIFIED")


def test_api_enabled_but_no_client_is_api_fail():
    out = run(PAIR_FOUND, api_enabled=True)
    assert "API_FAIL" in _flags(out)


def test_db_error_is_not_listed_never():
    c = ctx(conn_factory=lambda: _BadConn())
    out = invoke("check_contraindications", {"drugs": [{"name": "이부정"}, {"name": "와파린정"}]}, c)
    assert out["items"] and all(i["status"] == "UNIDENTIFIED" for i in out["items"])
    assert "hunter2" not in str(out) and check_items("check_contraindications", out["items"]) == []


class _BadConn:
    def cursor(self):
        raise RuntimeError("db password=hunter2")

    def close(self):
        pass


def test_same_ingredient_pair_not_self_compared():
    out = run([{"ingredient_code": APAP}, {"ingredient_code": APAP}])
    assert not pick(out, "contra_pair") and len(pick(out, "dup_ingredient")) == 1


@pytest.mark.parametrize("flag", ["NO_PRODUCT_INFO"])
def test_ingredient_items_do_not_carry_product_fields(flag):
    out = invoke("identify_drug", {"name": "와파린"}, ctx())
    assert flag in out["items"][0]["flags"] and out["items"][0]["form"] is None
