"""BE-10-14 A: DUR 성분정보 무필터 페이징 수집기와 빌더의 D 코드 수확·매칭·diff 시험(가짜 응답, 실호출 0, 로컬 data/ 불필요).

- 수집기: dry-run 호출 0, 페이징 합산, 재개(받은 쪽 건너뜀), 호출 상한 중단·재개, 오류 중단·기록, 키·URL 비노출, 호출 간 지연
- 빌더: 수확 자리 3곳(행 머리·MIXTURE_*·`[D######]Eng(Ko)` 목록), 정확 일치, 모호(영문 불일치·영문/한글 충돌) 배제, 복합 항목 제외,
  수기 `ingr_codes.json` 보존, 철자 변형 항목 동시 부여, diff 보고
"""

from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_drug_dict import (  # noqa: E402
    build_dictionary,
    diff_api_codes,
    diff_otc_products,
    format_diff,
    harvest_dur_codes,
    resolve_api_codes,
)
from collect_dur_ingr_all import OPS, Collector, existing_pages, main, page_path, pages_for  # noqa: E402

from app.tools._http import ApiError, ApiResponse  # noqa: E402
from app.tools.drug_dict import DrugDict  # noqa: E402

OP_A, OP_B = "getPwnmTabooInfoList02", "getOdsnAtentInfoList02"
SECRET = "zq8secretKEYvalue77x"   # 가짜 키(환경변수 이름이 `_KEY`로 끝나면 redact 대상)


class FakeHttp:
    """`ApiHttpClient.get` 호환 가짜. totals로 페이징하고 `fail_at=(op, page)`에서 ApiError(메시지에 키 포함)를 낸다."""

    def __init__(self, totals: dict[str, int], fail_at: tuple[str, int] | None = None) -> None:
        self.totals, self.fail_at, self.calls = totals, fail_at, []

    def get(self, op: str, params: dict) -> ApiResponse:
        page, rows = int(params["pageNo"]), int(params["numOfRows"])
        self.calls.append((op, page))
        if self.fail_at == (op, page):
            raise ApiError("http", f"boom serviceKey={SECRET}", http_status=500)
        total, start = self.totals[op], (page - 1) * rows
        items = [{"item": {"INGR_CODE": f"D{(start + i) % 1000000:06d}", "INGR_ENG_NAME": f"Ingr{start + i}", "INGR_NAME": "성분", "MIX_TYPE": "단일"}}
                 for i in range(max(0, min(rows, total - start)))]
        body = {"pageNo": page, "numOfRows": rows, "totalCount": total, "items": items}
        parsed = {"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."}, "body": body}
        return ApiResponse(parsed, json.dumps(parsed), "live", datetime.now(UTC), "0" * 16)


def _collector(tmp_path: Path, http: FakeHttp | None, **kw) -> Collector:
    sleeps: list[float] = []
    c = Collector(http=http, snap_dir=tmp_path, rows=10, sleep=sleeps.append, out=lambda _s: None, **kw)
    c._sleeps = sleeps  # type: ignore[attr-defined]
    return c


def _items(tmp_path: Path, op: str) -> int:
    return sum(len(d["body"]["items"]) for d in existing_pages(tmp_path, op).values())


# --------------------------------------------------------------------------- 수집기

def test_plan_dry_run_makes_no_calls(tmp_path):
    http = FakeHttp({OP_A: 25})
    plans = _collector(tmp_path, http).plan([OP_A, OP_B], {OP_A: 25})
    assert http.calls == []
    assert [(p.op, p.total, p.pages, p.todo, p.total_source) for p in plans] == [(OP_A, 25, 3, 3, "assumed"), (OP_B, 112, 12, 12, "assumed")]
    text = Collector.format_plan(plans, 60)
    assert "예상 호출 15회" in text and "실호출 0" in text


def test_default_plan_covers_seven_ops_within_default_cap():
    """7 op·100행이면 약 53회(추정 totalCount 기준)라 기본 상한 60 안에 든다(lane-D §5 ①의 ≈51회와 같은 자릿수)."""
    assert len(OPS) == 7
    total = sum(pages_for(t, 100) for _l, t in OPS.values())
    assert 50 <= total <= 60


def test_apply_saves_pages_and_items_sum_to_total(tmp_path):
    http = FakeHttp({OP_A: 25, OP_B: 7})
    c = _collector(tmp_path, http)
    m = c.run([OP_A, OP_B])
    assert m["status"] == "done" and c.calls == 4
    assert sorted(existing_pages(tmp_path, OP_A)) == [1, 2, 3] and sorted(existing_pages(tmp_path, OP_B)) == [1]
    assert _items(tmp_path, OP_A) == 25 and _items(tmp_path, OP_B) == 7
    assert m["ops"][OP_A]["status"] == "done" and m["ops"][OP_A]["total_count"] == 25
    page = json.loads(page_path(tmp_path, OP_A, 2).read_text(encoding="utf-8"))
    assert page["body"]["items"][0]["item"]["INGR_CODE"] == "D000010" and page["_meta"]["filter"] is None
    assert set(json.loads((tmp_path / "_nofilter_manifest.json").read_text())["ops"]) == {OP_A, OP_B}


def test_resume_skips_pages_already_saved(tmp_path):
    first = FakeHttp({OP_A: 25})
    _collector(tmp_path, first).run([OP_A])
    page_path(tmp_path, OP_A, 2).unlink()   # 2쪽만 빠진 상태
    again = FakeHttp({OP_A: 25})
    c = _collector(tmp_path, again)
    m = c.run([OP_A])
    assert again.calls == [(OP_A, 2)] and c.calls == 1 and m["status"] == "done"
    # 다 받은 뒤 다시 돌리면 호출 0
    third = FakeHttp({OP_A: 25})
    _collector(tmp_path, third).run([OP_A])
    assert third.calls == []


def test_plan_uses_saved_total_count(tmp_path):
    _collector(tmp_path, FakeHttp({OP_A: 25})).run([OP_A])
    (p,) = _collector(tmp_path, None).plan([OP_A], {OP_A: 999})
    assert (p.total, p.total_source, p.have, p.todo) == (25, "saved", 3, 0)


def test_max_calls_stops_and_later_run_finishes(tmp_path):
    http = FakeHttp({OP_A: 25, OP_B: 7})
    c = _collector(tmp_path, http, max_calls=2)
    m = c.run([OP_A, OP_B])
    assert m["status"] == "budget" and c.calls == 2 and sorted(existing_pages(tmp_path, OP_A)) == [1, 2]
    assert m["ops"][OP_A]["status"] == "budget" and m["ops"][OP_A]["next_page"] == 3 and OP_B not in m["ops"]
    c2 = _collector(tmp_path, FakeHttp({OP_A: 25, OP_B: 7}), max_calls=5)
    m2 = c2.run([OP_A, OP_B])
    assert m2["status"] == "done" and c2.calls == 2 and _items(tmp_path, OP_A) == 25 and _items(tmp_path, OP_B) == 7


def test_api_error_stops_records_and_hides_secret(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TEST_DUR_FAKE_API_KEY", SECRET)
    http = FakeHttp({OP_A: 25, OP_B: 7}, fail_at=(OP_A, 2))
    lines: list[str] = []
    c = Collector(http=http, snap_dir=tmp_path, rows=10, sleep=lambda _s: None, out=lines.append)
    m = c.run([OP_A, OP_B])
    assert m["status"] == "error" and m["ops"][OP_A]["status"] == "error" and m["ops"][OP_A]["next_page"] == 2
    assert m["ops"][OP_A]["error"]["kind"] == "http" and m["ops"][OP_A]["error"]["http_status"] == 500
    assert sorted(existing_pages(tmp_path, OP_A)) == [1] and OP_B not in m["ops"]   # 뒤 op은 시도하지 않는다
    blob = (tmp_path / "_nofilter_manifest.json").read_text(encoding="utf-8") + "\n".join(lines) + capsys.readouterr().out
    assert SECRET not in blob and "boom ***" in blob   # 값(과 `serviceKey=` 패턴)이 가려지고 메시지는 남는다


def test_delay_between_calls_uses_clock(tmp_path):
    http = FakeHttp({OP_A: 25})
    t = [0.0]
    c = _collector(tmp_path, http, delay=0.5)
    c.clock = lambda: t[0]
    c.run([OP_A])
    assert c._sleeps == [0.5, 0.5]   # 첫 호출은 지연 없음, 이후 2번은 0.5초씩(시계가 멈춰 있으므로 전부 기다린다)


def test_cli_dry_run_prints_plan_without_http(tmp_path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["--snap-dir", str(tmp_path), "--ops", OP_A, "--assume-total", f"{OP_A}=250"])
    assert rc == 0 and "| 3 | 0 | 3 |" in buf.getvalue() and not any(tmp_path.iterdir())


def test_cli_rejects_unknown_op_and_bad_assume(tmp_path):
    with pytest.raises(SystemExit):
        main(["--snap-dir", str(tmp_path), "--ops", "getNope"])
    with pytest.raises(SystemExit):
        main(["--snap-dir", str(tmp_path), "--assume-total", "getNope=3"])


# --------------------------------------------------------------------------- 빌더: 수확

def test_harvest_three_places_and_name_variants():
    rows = [
        # 금기·주의 op(단일): 머리 INGR_NAME
        {"INGR_CODE": "D000147", "INGR_ENG_NAME": "Acetaminophen", "INGR_NAME": "아세트아미노펜", "MIX_TYPE": "단일", "MIX_INGR": ""},
        # 복합 행 머리 + MIX_INGR 목록
        {"INGR_CODE": "D000147", "INGR_ENG_NAME": "Acetaminophen", "INGR_NAME": "아세트아미노펜", "MIX_TYPE": "복합",
         "MIX_INGR": "[D000493]Guaifenesin(구아이페네신)/[D000200]Dextromethorphan(덱스트로메토르판)"},
        # 병용 op: INGR_KOR_NAME, MIXTURE_*, MIX·MIXTURE_MIX
        {"TYPE_NAME": "병용금기", "MIX_TYPE": "복합", "INGR_CODE": "D000153", "INGR_ENG_NAME": "Esomeprazole", "INGR_KOR_NAME": "에스오메프라졸",
         "MIX": "[D000982]Naproxen(나프록센)", "MIXTURE_MIX_TYPE": "복합", "MIXTURE_INGR_CODE": "D000665", "MIXTURE_INGR_ENG_NAME": "Emtricitabine",
         "MIXTURE_INGR_KOR_NAME": "엠트리시타빈", "MIXTURE_MIX": "[D000281]Tenofovir(테노포비르)/[D000225]Rilpivirine"},
        {"INGR_CODE": "bad", "INGR_ENG_NAME": "X", "TYPE_NAME  ": "끝 공백 키"},
    ]
    obs = harvest_dur_codes(rows, {"D000698": "라사길린메실산염"})
    assert set(obs) == {"D000147", "D000493", "D000200", "D000153", "D000982", "D000665", "D000281", "D000225", "D000698"}
    assert obs["D000147"] == {"en": {"Acetaminophen": 2}, "ko": {"아세트아미노펜": 2}, "n": 2, "compound_head": 1}
    assert dict(obs["D000493"]["en"]) == {"Guaifenesin": 1} and dict(obs["D000493"]["ko"]) == {"구아이페네신": 1}
    assert dict(obs["D000665"]["ko"]) == {"엠트리시타빈": 1} and obs["D000665"]["compound_head"] == 1
    assert dict(obs["D000225"]["en"]) == {"Rilpivirine": 1} and dict(obs["D000225"]["ko"]) == {}   # 한글 괄호 없음
    assert dict(obs["D000698"]["en"]) == {} and dict(obs["D000698"]["ko"]) == {"라사길린메실산염": 1}   # 수기 목록은 한글 관측만


# --------------------------------------------------------------------------- 빌더: 매칭

KIDS = [
    {"product_code": "100000001", "name": "타이레놀정(아세트아미노펜)_(500mg/1정)", "ingr_code": "101301ATB", "ingr_name": "acetaminophen", "entp": "A"},
    {"product_code": "100000002", "name": "부루펜정(이부프로펜)_(200mg/1정)", "ingr_code": "172802ATB", "ingr_name": "ibuprofen", "entp": "B"},
    {"product_code": "100000003", "name": "콜드정", "ingr_code": "999901ATB", "ingr_name": "acetaminophen+ibuprofen", "entp": "C"},
    {"product_code": "100000004", "name": "넥시움정(에스오메프라졸)_(20mg/1정)", "ingr_code": "200001ATB", "ingr_name": "esomeprazole", "entp": "D"},
    {"product_code": "100000005", "name": "넥시정(에스오메프라졸)_(20mg/1정)", "ingr_code": "200002ATB", "ingr_name": "esomeprazol", "entp": "E"},
    {"product_code": "100000006", "name": "이지렉트정(라사길린메실산염)_(1mg/1정)", "ingr_code": "300001ATB", "ingr_name": "rasagiline mesylate", "entp": "F"},
    {"product_code": "100000007", "name": "와파린정(와파린나트륨)_(2mg/1정)", "ingr_code": "400001ATB", "ingr_name": "warfarin sodium", "entp": "G"},
    {"product_code": "100000008", "name": "아스피린정(아스피린)_(100mg/1정)", "ingr_code": "500001ATB", "ingr_name": "aspirin", "entp": "H"},
]
EMPTY_SNAPS = {"prmsn": [], "eyak": [], "detail": [], "dur_ingr": [], "ingr_codes": {}}


def _build(dur_rows, manual=None):
    snaps = {**EMPTY_SNAPS, "dur_ingr": dur_rows, "ingr_codes": manual or {}}
    data, stats = build_dictionary(KIDS, [], snaps, {"m": "1"})
    return data, stats, {i["set_key"]: i for i in data["ingredients"]}


def test_exact_en_match_attaches_and_compound_gets_nothing():
    rows = [{"INGR_CODE": "D000147", "INGR_ENG_NAME": "Acetaminophen", "INGR_NAME": "아세트아미노펜", "MIX_TYPE": "복합",
             "MIX_INGR": "[D000363]Ibuprofen(이부프로펜)"}]
    data, stats, by = _build(rows)
    assert by["acetaminophen"]["api_codes"] == ["D000147"] and by["ibuprofen"]["api_codes"] == ["D000363"]
    assert by["acetaminophen+ibuprofen"]["api_codes"] == []
    rep = stats["api_code_harvest"]
    assert (rep["codes_observed"], rep["attached"], rep["unmatched"], rep["conflict_count"], rep["inconsistent_en_count"]) == (2, 2, 0, 0, 0)
    prods = {p["name"]: p for p in data["products"]}
    assert prods["부루펜정(이부프로펜)_(200mg/1정)"]["api_codes"] == ["D000363"]
    assert sorted(prods["콜드정"]["api_codes"]) == []   # 복합 성분 항목에 연결된 제품은 성분 합집합이 비어 있다(기존 규칙)
    assert DrugDict(data).lookup_name("이부프로펜").candidates[0].api_codes == ("D000363",)


def test_inconsistent_en_names_for_one_code_are_not_attached():
    rows = [{"INGR_CODE": "D000999", "INGR_ENG_NAME": "Ibuprofen", "INGR_NAME": "이부프로펜", "MIX_TYPE": "단일"},
            {"INGR_CODE": "D000999", "INGR_ENG_NAME": "Aspirin", "INGR_NAME": "아스피린", "MIX_TYPE": "단일"}]
    _d, stats, by = _build(rows)
    assert by["ibuprofen"]["api_codes"] == [] and by["aspirin"]["api_codes"] == []
    assert stats["api_code_harvest"]["inconsistent_en"][0]["code"] == "D000999"


def test_en_and_ko_pointing_to_different_ingredients_is_a_conflict():
    rows = [{"INGR_CODE": "D000777", "INGR_ENG_NAME": "Ibuprofen", "INGR_NAME": "아스피린", "MIX_TYPE": "단일"}]
    _d, stats, by = _build(rows)
    assert by["ibuprofen"]["api_codes"] == [] and by["aspirin"]["api_codes"] == []
    (c,) = stats["api_code_harvest"]["conflict"]
    assert c["code"] == "D000777" and c["en_hits"] == ["이부프로펜"] and c["ko_hits"] == ["아스피린"]


def test_ko_variants_for_one_code_fall_back_to_en_only():
    rows = [{"INGR_CODE": "D000555", "INGR_ENG_NAME": "Warfarin", "INGR_NAME": "와파린", "MIX_TYPE": "단일"},
            {"INGR_CODE": "D000555", "INGR_ENG_NAME": "Warfarin Sodium", "INGR_NAME": "왈파린", "MIX_TYPE": "단일"}]
    _d, stats, by = _build(rows)
    assert by["warfarin"]["api_codes"] == ["D000555"] and stats["api_code_harvest"]["ko_varies"] == 1


def test_manual_ingr_codes_and_spelling_variants_preserved():
    """기존 판의 수기 코드(ingr_codes.json, 한글만)와 esomeprazol/esomeprazole 동시 부여가 그대로 남는다."""
    rows = [{"INGR_CODE": "D000153", "INGR_ENG_NAME": "Esomeprazole", "INGR_KOR_NAME": "에스오메프라졸", "MIX_TYPE": "단일"}]
    _d, stats, by = _build(rows, manual={"D000698": "라사길린메실산염"})
    assert by["rasagiline"]["api_codes"] == ["D000698"] and stats["api_code_harvest"]["ko_only"] == 1
    assert by["esomeprazole"]["api_codes"] == ["D000153"] and by["esomeprazol"]["api_codes"] == ["D000153"]


def test_unmatched_codes_are_counted_not_attached():
    rows = [{"INGR_CODE": "D000003", "INGR_ENG_NAME": "Nelfinavir", "INGR_NAME": "넬피나비어", "MIX_TYPE": "단일"}]
    _d, stats, by = _build(rows)
    assert stats["api_code_harvest"]["unmatched"] == 1 and all(i["api_codes"] == [] for i in by.values())


def test_resolve_reports_over_cap():
    ings = [{"id": 0, "components": [{"key": "ibuprofen"}], "display": "이부프로펜", "set_key": "ibuprofen"}]
    obs = harvest_dur_codes([{"INGR_CODE": f"D00000{n}", "INGR_ENG_NAME": "Ibuprofen", "INGR_NAME": "이부프로펜"} for n in (1, 2, 3)])
    attached, rep = resolve_api_codes(obs, ings)
    assert attached == {0: {"D000001", "D000002", "D000003"}} and rep["over_cap_count"] == 1 and rep["over_cap"][0]["ingredient"] == "이부프로펜"


# --------------------------------------------------------------------------- diff

def test_diff_reports_gained_lost_and_otc_tables():
    old, _s, _b = _build([{"INGR_CODE": "D000147", "INGR_ENG_NAME": "Acetaminophen", "INGR_NAME": "아세트아미노펜", "MIX_TYPE": "단일"}])
    new, _s2, _b2 = _build([{"INGR_CODE": "D000363", "INGR_ENG_NAME": "Ibuprofen", "INGR_NAME": "이부프로펜", "MIX_TYPE": "단일"},
                            {"INGR_CODE": "D000452", "INGR_ENG_NAME": "Aspirin", "INGR_NAME": "아스피린", "MIX_TYPE": "단일"}])
    d = diff_api_codes(old, new)
    assert d["ingredients_with_codes"] == {"old": 1, "new": 2} and d["gained"] == 2 and sorted(d["gained_sample"]) == ["aspirin", "ibuprofen"]
    assert d["lost"] == [{"set_key": "acetaminophen", "old": ["D000147"], "new": []}] and d["products_with_codes"] == {"old": 1, "new": 2}
    otc = {r["key"]: r for r in d["otc_ingredients"]}
    assert otc["ibuprofen"]["new"] == ["D000363"] and otc["acetaminophen"]["old"] == ["D000147"] and "metformin" not in otc
    prods = diff_otc_products(DrugDict(old), DrugDict(new), ["이부프로펜", "없는약이름zz"])
    assert prods[0]["old"] == [] and prods[0]["new"] == ["D000363"] and prods[1]["top"] is None
    text = format_diff(d, prods)
    assert "8 → 51" not in text and "| 이부프로펜 (ibuprofen) | - | D000363 |" in text and "사라진 코드 1건" in text
