"""AG-02 후속 계약: 성분 단위 연령·임부 금기 API 병기(4경우 꼬리표), 평가 모드 호출 0, H20 라사길린×덱스트로메토르판 양방향.

외부 호출 없음: 가짜 응답과 로컬 스냅샷(`data/mock/api_snapshots`, 없으면 해당 시험만 건너뜀)만 쓴다.
"""

from __future__ import annotations

import pytest
from ag02_synth import APAP, ctx

from app.agent.tools.context import ToolContext, ingredient_api_fns
from app.agent.tools.contract import check_items
from app.agent.tools.registry import invoke
from app.tools import _http
from app.tools.drug_dict import DrugDict
from app.tools.dur import DurClient, DurResult, DurRow

APAP_API, WAR_API = "D000001", "D000003"
AGE5 = {"value": 5, "unit": "세"}


def _res(kind, rows=None, ok=True):
    return DurResult(ok=ok, kind=kind, level="ingr", rows=rows or [], source_name="식약처 DUR 성분정보", queried_at_utc="2026-11-10T12:00:00Z", request_hashes=["h"])


def _age_row(base="12세 미만"):
    return DurRow(kind="age", level="ingr", age_base=base, content="API 연령 합성 문구", notification_date="2014-01-09", evidence_id="age123456789")


def _preg_row():
    return DurRow(kind="pregnancy", level="ingr", grade="2등급", content="API 임부 합성 문구", notification_date="2016-12-30", evidence_id="preg12345678")


def run(drugs, **kw):
    c = ctx(**{k: kw.pop(k) for k in ("api_enabled", "api_age_fn", "api_pregnancy_fn") if k in kw})
    out = invoke("check_contraindications", {"drugs": drugs, **kw}, c)
    assert "error" not in out and out["contract_violations"] == [], out
    return out


def of(out, kind, source_kind="FILE"):
    return [i for i in out["items"] if i["kind"] == kind and i.get("source_kind", "FILE") == source_kind and i["status"] != "UNIDENTIFIED"]


def flags(out, kind):
    return {f for i in out["items"] if i["kind"] == kind for f in i["flags"] if f.startswith(("API_", "FILE_"))}


# ------------------------------------------------------------------ 연령 4경우 (타이레놀: 파일에 12세 미만 규칙, 5세 → FOUND / 20세 → NOT_LISTED)
def test_age_api_same():
    out = run([{"name": "타이레놀정"}], age=AGE5, api_age_fn=lambda c: _res("age", [_age_row()]))
    assert flags(out, "age") == {"API_SAME"}
    assert {i["source_kind"] for i in out["items"] if i["kind"] == "age"} == {"FILE", "API_DIRECT"}  # 두 출처 모두 기록
    (f,) = of(out, "age")
    assert f["status"] == "FOUND" and f["as_of"] == "2026-07-21" and f["api"]["outcome"] == "BOTH_FOUND"


def test_age_file_only():
    out = run([{"name": "타이레놀정"}], age=AGE5, api_age_fn=lambda c: _res("age", []))
    assert flags(out, "age") == {"FILE_ONLY"}
    (f,) = of(out, "age")
    assert f["status"] == "FOUND" and any("해제되었을 수" in n and "약사·의사" in n for n in f["notes"])  # 파일 판정 그대로
    assert not of(out, "age", "API_DIRECT")


def test_age_api_only():
    out = run([{"name": "타이레놀정"}], age={"value": 20, "unit": "세"}, api_age_fn=lambda c: _res("age", [_age_row("30세 미만")]))
    assert flags(out, "age") == {"API_ONLY"}
    (f,) = of(out, "age")
    assert f["status"] == "NOT_LISTED"  # 한쪽을 확정하지 않는다
    assert any("새로 지정되었을 수" in n and "안전하다는 뜻이 아니" in n for n in f["notes"])
    assert of(out, "age", "API_DIRECT")[0]["status"] == "FOUND"


def test_age_api_fail_and_exception_keep_file_answer():
    for fn in (lambda c: _res("age", ok=False), lambda c: (_ for _ in ()).throw(TimeoutError("secret-url"))):
        out = run([{"name": "타이레놀정"}], age=AGE5, api_age_fn=fn)
        assert flags(out, "age") == {"API_FAIL"} and "secret" not in str(out)
        (f,) = of(out, "age")
        assert f["status"] == "FOUND" and any("실시간 확인을 하지 못함" in n for n in f["notes"])


def test_age_api_row_not_applicable_to_user_age_is_not_api_found():
    """API는 연령 조건 전체를 돌려주므로 사용자 나이에 해당하지 않는 행(20세에게 12세 미만)은 병기 비교에서 뺀다."""
    out = run([{"name": "타이레놀정"}], age={"value": 20, "unit": "세"}, api_age_fn=lambda c: _res("age", [_age_row()]))
    assert flags(out, "age") == {"API_SAME"} and of(out, "age")[0]["status"] == "NOT_LISTED"  # 양쪽 모두 목록에 없음
    assert not of(out, "age", "API_DIRECT")


def test_age_unparseable_api_condition_counts_as_applicable():
    out = run([{"name": "타이레놀정"}], age={"value": 20, "unit": "세"}, api_age_fn=lambda c: _res("age", [_age_row("연령 조건 불명")]))
    assert flags(out, "age") == {"API_ONLY"}  # 놓치지 않는 쪽, 한쪽을 확정하지 않는다


# ------------------------------------------------------------------ 임부 4경우 (와파린: 파일에 임부금기 있음, 타이레놀: 없음)
def test_pregnancy_four_cases():
    same = run([{"name": "와파린정"}], pregnancy=True, api_pregnancy_fn=lambda c: _res("pregnancy", [_preg_row()]))
    assert flags(same, "pregnancy") == {"API_SAME"} and {i["source_kind"] for i in same["items"] if i["kind"] == "pregnancy"} == {"FILE", "API_DIRECT"}
    fo = run([{"name": "와파린정"}], pregnancy=True, api_pregnancy_fn=lambda c: _res("pregnancy", []))
    assert flags(fo, "pregnancy") == {"FILE_ONLY"} and of(fo, "pregnancy")[0]["status"] == "FOUND"
    ao = run([{"name": "타이레놀정"}], pregnancy=True, api_pregnancy_fn=lambda c: _res("pregnancy", [_preg_row()]))
    assert flags(ao, "pregnancy") == {"API_ONLY"} and of(ao, "pregnancy")[0]["status"] == "NOT_LISTED"
    assert of(ao, "pregnancy", "API_DIRECT")[0]["matches"][0]["grade"] == "2등급"  # 등급 원문 그대로
    fail = run([{"name": "와파린정"}], pregnancy=True, api_pregnancy_fn=lambda c: _res("pregnancy", ok=False))
    assert flags(fail, "pregnancy") == {"API_FAIL"} and of(fail, "pregnancy")[0]["status"] == "FOUND"


def test_missing_fn_or_api_code_is_api_fail_never_pair_incomplete():
    out = run([{"name": "타이레놀정"}], age=AGE5, pregnancy=True)  # api_enabled인데 함수 없음
    assert flags(out, "age") == {"API_FAIL"} and flags(out, "pregnancy") == {"API_FAIL"}
    calls = []
    out2 = run([{"ingredient_code": APAP}], age=AGE5, api_age_fn=lambda c: calls.append(c) or _res("age"))  # KIDS 코드 입력엔 API 코드가 없다
    assert flags(out2, "age") == {"API_FAIL"} and calls == []


def test_eval_mode_calls_nothing_and_has_no_api_flags():
    calls = []
    out = run([{"name": "타이레놀정"}, {"name": "와파린정"}], age=AGE5, pregnancy=True, api_enabled=False,
              api_age_fn=lambda c: calls.append(c) or _res("age", [_age_row()]), api_pregnancy_fn=lambda c: calls.append(c) or _res("pregnancy", [_preg_row()]))
    assert calls == [] and not flags(out, "age") and not flags(out, "pregnancy")
    assert all(i["source_kind"] == "FILE" for i in out["items"] if i["status"] != "UNIDENTIFIED")


def test_api_not_called_for_file_unidentified_items():
    calls = []
    out = run([{"name": "미등록정"}], age=AGE5, api_age_fn=lambda c: calls.append(c) or _res("age"))
    assert calls == [] and not flags(out, "age") and {i["status"] for i in out["items"]} == {"UNIDENTIFIED"}


def test_adapter_calls_client_by_ingredient_with_kind():
    seen = []

    class Fake:
        def by_ingredient(self, kind, code):
            seen.append((kind, code))
            return _res(kind)

    age_fn, preg_fn = ingredient_api_fns(Fake())
    age_fn("D000001"), preg_fn("D000003")
    assert seen == [("age", "D000001"), ("pregnancy", "D000003")]
    run([{"name": "타이레놀정"}], age=AGE5, api_age_fn=age_fn)
    assert seen[-1] == ("age", APAP_API)


# ------------------------------------------------------------------ 계약 검사가 새 규칙을 안다
def _item(**kw):
    base = {"kind": "age", "status": "FOUND", "evidence_id": "e", "source": "s", "as_of": "2026-07-21", "source_kind": "FILE", "flags": [], "matches": [{}]}
    return {**base, **kw}


def test_check_items_knows_single_item_api_rules():
    assert check_items("check_contraindications", [_item(flags=["API_FAIL"])]) == []
    assert any("API_PAIR_INCOMPLETE" in b for b in check_items("check_contraindications", [_item(flags=["API_PAIR_INCOMPLETE"])]))
    assert check_items("check_contraindications", [_item(kind="contra_pair", flags=["API_PAIR_INCOMPLETE"])]) == []
    assert any("둘 이상" in b for b in check_items("check_contraindications", [_item(flags=["API_SAME", "FILE_ONLY"])]))
    assert any("조회 시각" in b for b in check_items("check_contraindications", [_item(source_kind="API_DIRECT", dataset_key="dur_ingr", as_of="2026-01-01")]))


# ------------------------------------------------------------------ H20: 라사길린(D000698) × 덱스트로메토르판(D000200), 로컬 스냅샷
SNAP = _http.DEFAULT_SNAPSHOT_DIR
needs_snap = pytest.mark.skipif(not (SNAP / "dur-ingr").exists(), reason="data/mock/api_snapshots 없음(로컬 전용)")
RAS, DXM, MISS = "600001ATB", "600002ATB", "600003ATB"


def _h20_ctx(pair_fn):
    import sqlite3

    from ag02_synth import _ing, _prod, synth_dict

    from app.db import loaders

    base = synth_dict()
    ings = [_ing(0, "Rasagiline", "라사길린", [RAS], ["D000698"]), _ing(1, "Dextromethorphan", "덱스트로메토르판", [DXM], ["D000200"]),
            _ing(2, "Nosnap", "스냅샷없음", [MISS], ["D999999"])]
    prods = [_prod("700000001", "이지렉트정", "전문", kids=[RAS], api=["D000698"], ids=[0], link="edi_code"),
             _prod("700000002", "덱스트정", "일반", kids=[DXM], api=["D000200"], ids=[1], link="edi_code"),
             _prod("700000003", "스냅없는정", "일반", kids=[MISS], api=["D999999"], ids=[2], link="edi_code")]
    d = DrugDict({"meta": base.meta, "products": prods, "ingredients": ings})

    def conn():
        c = sqlite3.connect(":memory:")
        loaders.apply_schema(c)
        rows = loaders.collect([{"id": "c1", "text": "", "metadata": {
            "성분명A": "rasagiline", "성분코드A": RAS, "성분명B": "dextromethorphan", "성분코드B": DXM, "고시번호": "20250046", "고시적용일": "2025-07-14",
            "금기사유": "경련, 반사항진, 이상고열, 혼수 등", "비고": ""}},
            {"id": "c2", "text": "", "metadata": {"성분명A": "rasagiline", "성분코드A": RAS, "성분명B": "nosnap", "성분코드B": MISS, "고시번호": "1", "고시적용일": "2025-07-14",
                                               "금기사유": "합성", "비고": ""}}],
            loaders.normalize_contra_json, "contra_pair", "x.json", loaders.AS_OF_KIDS)
        loaders.load_into(c, {"x.json": rows})
        return c

    return ToolContext(d, conn_factory=conn, api_enabled=True, api_pair_fn=pair_fn)


def _snap_client():
    from app.tools._http import ApiHttpClient

    return DurClient(ApiHttpClient("dur-item", None, None, mode="snapshot"), ApiHttpClient("dur-ingr", None, None, mode="snapshot"))


def _pair(ctx_, names):
    out = invoke("check_contraindications", {"drugs": [{"name": n} for n in names]}, ctx_)
    assert "error" not in out and out["contract_violations"] == [], out
    return out


@needs_snap
def test_h20_rasagiline_dextromethorphan_both_sides_queried_api_same():
    client = _snap_client()
    only_a = client.by_ingredient("usjnt", "D000698")  # 한쪽(A)만 조회하면 덱스트로메토르판 쌍이 안 나온다 = 양방향이 필요한 이유
    assert only_a.ok and not any(r.pair_ingr_code == "D000200" for r in only_a.rows)
    out = _pair(_h20_ctx(client.usjnt_pair_by_ingredient), ["이지렉트정", "덱스트정"])
    pair = [i for i in out["items"] if i["kind"] == "contra_pair"]
    assert {i["source_kind"] for i in pair} == {"FILE", "API_DIRECT"} and {f for i in pair for f in i["flags"]} == {"API_SAME"}
    api = next(i for i in pair if i["source_kind"] == "API_DIRECT")
    assert api["matches"][0]["notice_date"] == "2017-11-06" and "경련" in api["matches"][0]["content"]


@needs_snap
def test_h20_one_side_missing_is_pair_incomplete_and_file_verdict_unchanged():
    client = _snap_client()
    res = client.usjnt_pair_by_ingredient("D000698", "D999999")  # 한쪽 스냅샷 없음 → 실패(partial)
    assert not res.ok and res.partial == "B"
    out = _pair(_h20_ctx(client.usjnt_pair_by_ingredient), ["이지렉트정", "스냅없는정"])
    pair = [i for i in out["items"] if i["kind"] == "contra_pair"]
    assert pair and {f for i in pair for f in i["flags"] if f.startswith("API_")} == {"API_PAIR_INCOMPLETE"}
    assert all(i["status"] == "FOUND" and i["source_kind"] == "FILE" for i in pair)  # 파일 판정은 바뀌지 않는다
    assert any("실시간 확인을 하지 못함" in n for i in pair for n in i["notes"])


def test_h20_synthetic_fake_client_fails_one_side(monkeypatch):
    """스냅샷이 없는 환경용: 쌍 함수가 한쪽 실패(partial)를 돌려주면 API_PAIR_INCOMPLETE, 코드가 없는 쪽이면 호출 0."""
    fail = lambda a, b: DurResult(ok=False, kind="usjnt", level="ingr", source_name="식약처 DUR 성분정보", partial="A")  # noqa: E731
    out = _pair(_h20_ctx(fail), ["이지렉트정", "덱스트정"])
    pair = [i for i in out["items"] if i["kind"] == "contra_pair"]
    assert {f for i in pair for f in i["flags"] if f.startswith("API_")} == {"API_PAIR_INCOMPLETE"} and all(i["status"] == "FOUND" for i in pair)
