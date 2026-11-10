"""BE-03 DUR 클라이언트 시험. 모두 오프라인이다(네트워크는 막고, 응답은 픽스처·스냅샷에서 가져온다)."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import httpx
import pytest

from app.tools import _http
from app.tools._http import ApiHttpClient, ResponseCache
from app.tools.dur import (
    NOT_SAFE_NOTE,
    CrossCheck,
    DurClient,
    cross_check,
    iso_date,
)
from app.tools.lookup import FOUND, NOT_LISTED, UNIDENTIFIED, Item

FIXTURES = Path(__file__).parent / "fixtures" / "api"
SNAPSHOTS = _http.DEFAULT_SNAPSHOT_DIR
FAKE_KEY = "TEST-KEY-abc/def+123=="
ITEM_BASE = "https://example.invalid/DURPrdlstInfoService03"
INGR_BASE = "https://example.invalid/DURIrdntInfoService03"

needs_snapshots = pytest.mark.skipif(not (SNAPSHOTS / "dur-ingr").exists(), reason="data/mock/api_snapshots 없음(로컬 전용)")

ERR_XML_RATE = (
    "<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>"
    "<returnReasonCode>22</returnReasonCode><returnAuthMsg>LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR</returnAuthMsg>"
    "</cmmMsgHeader></OpenAPI_ServiceResponse>"
)
EMPTY = json.dumps({"header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."}, "body": {"pageNo": 1, "totalCount": 0, "numOfRows": 100}})


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*a, **k):
        raise AssertionError("네트워크 호출 금지")

    monkeypatch.setattr(socket.socket, "connect", blocked)


def fx(path: str) -> str:
    return (FIXTURES / f"{path}.json").read_text(encoding="utf-8")


class FakeServer:
    """MockTransport 핸들러. 응답을 차례로 돌려주고(마지막은 반복) 요청을 기록한다."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        r = self.responses[min(len(self.requests), len(self.responses)) - 1]
        if isinstance(r, Exception):
            raise r
        return r


class FnServer(FakeServer):
    """요청 URL로 응답을 고르는 핸들러."""

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.fn(request)


def ok(text: str) -> httpx.Response:
    return httpx.Response(200, text=text)


def make(item_server=None, ingr_server=None, *, cache=False, **kw) -> DurClient:
    def http(alias, base, server):
        return ApiHttpClient(
            alias, base, FAKE_KEY,
            cache=ResponseCache(ttl_seconds=60) if cache else None,
            http_client=httpx.Client(transport=httpx.MockTransport(server or FakeServer(ok(EMPTY)))),
            sleep=lambda s: None,
        )

    return DurClient(http("dur-item", ITEM_BASE, item_server), http("dur-ingr", INGR_BASE, ingr_server), **kw)


def snapshot_client() -> DurClient:
    return DurClient(
        ApiHttpClient("dur-item", None, None, mode="snapshot"),
        ApiHttpClient("dur-ingr", None, None, mode="snapshot"),
    )


# ---------------------------------------------------------------------------------------------
# 파서·원문 보존
# ---------------------------------------------------------------------------------------------
def test_iso_date():
    assert iso_date("20090303") == "2009-03-03"
    assert iso_date("2009-03-03") is None and iso_date(None) is None


def test_item_usjnt_parses_pair_fields_and_keeps_text():
    server = FakeServer(ok(fx("dur-item/usjnt_methotrexate_injection")))
    res = make(server, max_pages=1).by_item("usjnt", "197900070")
    assert res.ok and res.level == "item" and res.kind == "usjnt"
    assert res.total_count == 460 and len(res.rows) == 3 and res.truncated and not res.empty
    r = res.rows[0]
    assert (r.item_seq, r.pair_item_seq) == ("197900070", "200806769")
    assert (r.ingr_code, r.pair_ingr_code) == ("D000716", "D000019")
    assert r.content == "간 독성\n"                      # 개행까지 원문 그대로
    assert (r.notification_date_raw, r.notification_date) == ("20090303", "2009-03-03")
    assert res.queried_at_utc.endswith("Z") and "KST" in res.queried_at_display
    assert "itemSeq=197900070" in str(server.requests[0].url)


def test_item_age_has_no_age_base_and_keeps_sentence():
    res = make(FakeServer(ok(fx("dur-item/age_taboo_tylenol")))).by_item("age", "202200407")
    r = res.rows[0]
    assert res.ok and r.age_base is None and r.grade is None      # 품목정보에는 AGE_BASE가 없다
    assert r.content.startswith("-소아 및 고령자") and r.notification_date == "2014-01-09"


def test_ingr_pregnancy_grade_verbatim_no_conversion():
    res = make(ingr_server=FakeServer(ok(fx("dur-ingr/pwnm_grade")))).by_ingredient("pregnancy", "D000100")
    assert res.ok and res.level == "ingr"
    first = res.rows[0]
    assert first.grade == "1등급" and first.content == "임부에 대한 안전성 미확립."
    assert all(r.grade and r.grade.endswith("등급") for r in res.rows)   # '1'·'2'·'M'으로 바꾸지 않는다
    assert first.raw["GRADE"] == first.grade                                              # 원본 그대로 보존


def test_ingr_age_base_verbatim():
    res = make(ingr_server=FakeServer(ok(fx("dur-ingr/age_base")))).by_ingredient("age", "D000149")
    assert res.rows[0].age_base == "18세 이하" and res.rows[0].notification_date == "2014-01-09"


def test_operation_names_used():
    item, ingr = FakeServer(ok(EMPTY)), FakeServer(ok(EMPTY))
    c = make(item, ingr)
    c.by_item("usjnt", "197900070"); c.by_item("pregnancy", "197900070"); c.by_item("age", "197900070")
    c.by_ingredient("usjnt", "D000147"); c.by_ingredient("pregnancy", "D000147"); c.by_ingredient("age", "D000147")
    urls = [str(r.url) for r in item.requests] + [str(r.url) for r in ingr.requests]
    for op in ("getUsjntTabooInfoList03", "getPwnmTabooInfoList03", "getSpcifyAgrdeTabooInfoList03",
               "getUsjntTabooInfoList02", "getPwnmTabooInfoList02", "getSpcifyAgrdeTabooInfoList02"):
        assert any(f"/{op}?" in u for u in urls), op


# ---------------------------------------------------------------------------------------------
# 빈 결과·오류·입력 검증·캐시
# ---------------------------------------------------------------------------------------------
def test_empty_result_is_not_safe_claim():
    res = make().by_ingredient("pregnancy", "D000147")
    assert res.ok and res.empty and res.rows == [] and res.note == NOT_SAFE_NOTE


@pytest.mark.parametrize("bad", ["", "12345", "abcdefghi", "1234567890", None])
def test_invalid_item_seq(bad):
    server = FakeServer(ok(EMPTY))
    res = make(server).by_item("usjnt", bad)
    assert not res.ok and res.error.kind == "invalid_request" and not server.requests and not res.empty


@pytest.mark.parametrize("bad", ["", "D00014", "147", "X000147", "D0001477"])
def test_invalid_ingr_code(bad):
    res = make().by_ingredient("age", bad)
    assert not res.ok and res.error.kind == "invalid_request"


def test_ingr_code_lowercase_normalized():
    server = FakeServer(ok(EMPTY))
    assert make(ingr_server=server).by_ingredient("age", "d000147").ok
    assert "ingrCode=D000147" in str(server.requests[0].url)


def test_rate_limit_returns_error_object_without_key():
    res = make(ingr_server=FakeServer(ok(ERR_XML_RATE))).by_ingredient("usjnt", "D000147")
    assert not res.ok and res.error.kind == "rate_limit" and not res.empty
    assert FAKE_KEY not in res.model_dump_json()


def test_http_429_and_auth_and_5xx_errors():
    r429 = make(ingr_server=FakeServer(httpx.Response(429, text="x"))).by_ingredient("usjnt", "D000147")
    assert r429.error.kind == "rate_limit"
    r403 = make(ingr_server=FakeServer(httpx.Response(403, text="forbidden"))).by_ingredient("usjnt", "D000147")
    assert r403.error.kind == "auth"
    r500 = make(ingr_server=FakeServer(httpx.Response(500, text="boom"))).by_ingredient("usjnt", "D000147")
    assert r500.error.kind == "http" and r500.error.retryable


def test_timeout_returns_error():
    res = make(ingr_server=FakeServer(httpx.ReadTimeout("t"))).by_ingredient("usjnt", "D000147")
    assert not res.ok and res.error.kind == "timeout"


def test_cache_second_call_from_cache_with_original_time():
    server = FakeServer(ok(fx("dur-ingr/age_base")))
    c = make(ingr_server=server, cache=True, max_pages=1)
    a = c.by_ingredient("age", "D000149")
    b = c.by_ingredient("age", "D000149")
    assert a.source == "live" and b.source == "cache" and b.from_cache
    assert len(server.requests) == 1 and a.queried_at_utc == b.queried_at_utc


def test_paging_reads_until_total():
    page = lambda n, rows: ok(json.dumps({"header": {"resultCode": "00"}, "body": {"pageNo": n, "totalCount": 3, "numOfRows": 2, "items": rows}}))  # noqa: E731
    mk = lambda i: {"item": {"INGR_CODE": "D000147", "NOTIFICATION_DATE": "20140109", "PROHBT_CONTENT": f"c{i}"}}  # noqa: E731
    server = FakeServer(page(1, [mk(1), mk(2)]), page(2, [mk(3)]))
    res = make(ingr_server=server).by_ingredient("age", "D000147")
    assert res.ok and [r.content for r in res.rows] == ["c1", "c2", "c3"] and not res.truncated
    assert len(server.requests) == 2


# ---------------------------------------------------------------------------------------------
# 병용금기 쌍: 양쪽 조회
# ---------------------------------------------------------------------------------------------
def _usjnt_page(rows):
    return ok(json.dumps({"header": {"resultCode": "00"}, "body": {"pageNo": 1, "totalCount": len(rows), "numOfRows": 100,
                                                                    "items": [{"item": r} for r in rows]}}))


def _pair_row(a, b, date="20171106", content="경련"):
    return {"INGR_CODE": a, "MIXTURE_INGR_CODE": b, "NOTIFICATION_DATE": date, "PROHBT_CONTENT": content}


def test_pair_queries_both_sides_and_finds_b_side_only_hit():
    # A=D000698 조회에는 상대 D000200이 없고, D000200 조회에만 쌍이 있다(BE-03 메모 2026-11-05).
    def handler(request: httpx.Request) -> httpx.Response:
        if "ingrCode=D000698" in str(request.url):
            return _usjnt_page([_pair_row("D000698", "D000429")])
        return _usjnt_page([_pair_row("D000200", "D000698")])

    server = FnServer(handler)
    res = make(ingr_server=server).usjnt_pair_by_ingredient("D000698", "D000200")
    assert res.ok and len(res.rows) == 1 and (res.rows[0].ingr_code, res.rows[0].pair_ingr_code) == ("D000200", "D000698")
    assert len(server.requests) == 2


def test_pair_one_side_error_is_error_not_empty():
    def handler(request):
        return ok(ERR_XML_RATE) if "ingrCode=D000200" in str(request.url) else _usjnt_page([])

    res = make(ingr_server=FnServer(handler)).usjnt_pair_by_ingredient("D000698", "D000200")
    assert not res.ok and res.error.kind == "rate_limit" and not res.empty


def test_pair_no_match_is_empty_with_note():
    res = make(ingr_server=FakeServer(_usjnt_page([_pair_row("D000147", "D000999")]))).usjnt_pair_by_ingredient("D000147", "D000200")
    assert res.ok and res.empty and res.note == NOT_SAFE_NOTE


def test_pair_dedupes_same_row_seen_from_both_sides():
    row = _pair_row("D000200", "D000698")
    res = make(ingr_server=FakeServer(_usjnt_page([row]))).usjnt_pair_by_ingredient("D000200", "D000698")
    assert res.ok and len(res.rows) == 1


@pytest.mark.parametrize("a,b", [("D000147", "D000147"), ("D000147", "bad"), ("", "D000147")])
def test_pair_invalid_inputs(a, b):
    res = make().usjnt_pair_by_ingredient(a, b)
    assert not res.ok and res.error.kind == "invalid_request"


def test_pair_by_item_uses_item_seq_keys():
    row = {"ITEM_SEQ": "197900070", "MIXTURE_ITEM_SEQ": "200806769", "NOTIFICATION_DATE": "20090303", "PROHBT_CONTENT": "간 독성\n"}
    res = make(FakeServer(_usjnt_page([row]))).usjnt_pair_by_item("200806769", "197900070")
    assert res.ok and len(res.rows) == 1 and res.rows[0].content == "간 독성\n"


# ---------------------------------------------------------------------------------------------
# 파일(BE-09) 판정과 병기·교차(읽기만)
# ---------------------------------------------------------------------------------------------
def _file_item(status, dates=()):
    return Item("contra_pair", status, ("D000200", "D000698"), "contra_pair:D000200:D000698", "한국의약품안전관리원", "2026-07-21",
                matches=[{"notice_date": d} for d in dates])


def _api(rows_dates, ok_=True):
    c = make(ingr_server=FakeServer(_usjnt_page([_pair_row("D000200", "D000698", d) for d in rows_dates])))
    return c.usjnt_pair_by_ingredient("D000200", "D000698")


def test_cross_check_four_cases_plus_unavailable():
    assert cross_check(_file_item(FOUND, ["2017-11-06"]), _api(["20171106"])).outcome == "BOTH_FOUND"
    assert cross_check(_file_item(FOUND, ["2017-11-06"]), _api([])).outcome == "FILE_ONLY"
    assert cross_check(_file_item(NOT_LISTED), _api(["20171106"])).outcome == "API_ONLY"
    assert cross_check(_file_item(NOT_LISTED), _api([])).outcome == "BOTH_NOT_LISTED"
    failed = make(ingr_server=FakeServer(ok(ERR_XML_RATE))).usjnt_pair_by_ingredient("D000200", "D000698")
    assert cross_check(_file_item(FOUND, ["2017-11-06"]), failed).outcome == "API_UNAVAILABLE"
    assert cross_check(_file_item(UNIDENTIFIED), _api([])).outcome == "FILE_UNIDENTIFIED"


def test_cross_check_shows_both_dates_and_does_not_claim_newer():
    cc = cross_check(_file_item(FOUND, ["2017-11-06"]), _api(["20250714"]))
    assert isinstance(cc, CrossCheck) and cc.dates_differ
    assert cc.file_notice_dates == ["2017-11-06"] and cc.api_notice_dates == ["2025-07-14"]
    assert "단정하지 않습니다" in cc.note
    same = cross_check(_file_item(FOUND, ["2017-11-06"]), _api(["20171106"]))
    assert not same.dates_differ


def test_cross_check_accepts_to_dict_and_does_not_mutate_file_item():
    item = _file_item(FOUND, ["2017-11-06"])
    before = item.to_dict()
    cc = cross_check(item.to_dict(), _api(["20171106"]))
    assert cc.outcome == "BOTH_FOUND" and item.to_dict() == before


# ---------------------------------------------------------------------------------------------
# 이관 시험: 오프라인 스냅샷(RFP-32)
# ---------------------------------------------------------------------------------------------
@needs_snapshots
def test_snapshot_pair_needs_both_sides():
    c = snapshot_client()
    # 라사길린(D000698) 조회만으로는 덱스트로메토르판(D000200) 쌍이 안 나온다.
    only_a = c.by_ingredient("usjnt", "D000698")
    assert only_a.ok and only_a.source == "snapshot" and not any(r.pair_ingr_code == "D000200" for r in only_a.rows)
    both = c.usjnt_pair_by_ingredient("D000698", "D000200")
    assert both.ok and len(both.rows) == 1 and both.rows[0].ingr_code == "D000200"
    assert both.rows[0].notification_date == "2017-11-06" and "경련" in both.rows[0].content


@needs_snapshots
def test_snapshot_pregnancy_and_age_ingredient():
    c = snapshot_client()
    preg = c.by_ingredient("pregnancy", "D000448")
    assert preg.ok and preg.rows[0].grade == "2등급" and preg.rows[0].content == "임부에 대한 안전성 미확립."
    age = c.by_ingredient("age", "D000147")
    assert age.ok and age.rows[0].age_base == "12세 미만" and age.rows[0].content.startswith("-소아 및 고령자")
    assert age.queried_at_utc.endswith("Z")


@needs_snapshots
def test_snapshot_empty_and_miss():
    c = snapshot_client()
    empty = c.by_ingredient("pregnancy", "D000147")        # 아세트아미노펜 임부금기 0건
    assert empty.ok and empty.empty and empty.note
    miss = c.by_ingredient("pregnancy", "D999999")
    assert not miss.ok and miss.error.kind == "snapshot_miss"
