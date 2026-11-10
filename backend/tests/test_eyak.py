"""BE-02 e약은요 클라이언트 시험. 모두 오프라인이다(네트워크는 막고, 응답은 픽스처·스냅샷에서 가져온다)."""

from __future__ import annotations

import json
import socket
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.config import Settings
from app.tools import _http
from app.tools._http import ApiError, ApiHttpClient, ResponseCache, mask_secret, parse_response, request_hash
from app.tools.eyak import EyakClient

FIXTURES = Path(__file__).parent / "fixtures" / "api" / "eyak"
SNAPSHOTS = _http.DEFAULT_SNAPSHOT_DIR
FAKE_KEY = "TEST-KEY-abc/def+123=="
BASE = "https://example.invalid/DrbEasyDrugInfoService"

needs_snapshots = pytest.mark.skipif(not (SNAPSHOTS / "eyak").exists(), reason="data/mock/api_snapshots 없음(로컬 전용)")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """실수로 실제 호출이 나가면 시험이 실패하게 소켓 연결을 막는다."""

    def blocked(*a, **k):
        raise AssertionError("네트워크 호출 금지")

    monkeypatch.setattr(socket.socket, "connect", blocked)


def fixture_text(name: str) -> str:
    return (FIXTURES / f"{name}.json").read_text(encoding="utf-8")


class FakeServer:
    """MockTransport 핸들러. 응답 목록을 차례로 돌려주고 요청을 기록한다."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        r = self.responses[min(len(self.requests), len(self.responses)) - 1]
        if isinstance(r, Exception):
            raise r
        return r


def ok(name: str) -> httpx.Response:
    return httpx.Response(200, text=fixture_text(name))


def make_client(server, *, cache=True, **kw) -> EyakClient:
    http = ApiHttpClient(
        "eyak", BASE, FAKE_KEY,
        cache=ResponseCache(ttl_seconds=60) if cache is True else cache or None,
        http_client=httpx.Client(transport=httpx.MockTransport(server)),
        sleep=lambda s: None,
        **kw,
    )
    return EyakClient(http)


# ---------------------------------------------------------------------------------------------
# 파서·필드 보존
# ---------------------------------------------------------------------------------------------
def test_hit_parses_fields_and_keeps_label_text_verbatim():
    raw = json.loads(fixture_text("hit_tylenol"))["body"]["items"][0]
    res = make_client(FakeServer(ok("hit_tylenol"))).search_by_name("타이레놀", num_of_rows=3)
    assert res.ok and not res.empty and res.total_count == 7 and len(res.items) == 3
    first = res.items[0]
    assert first.item_seq == "202005623" and first.item_name == raw["itemName"]
    # 문장형 필드는 원문 그대로(끝 개행 포함)
    assert first.efcy == raw["efcyQesitm"] and first.efcy.endswith("\n")
    assert first.use_method == raw["useMethodQesitm"]
    assert first.atpn_warn == raw["atpnWarnQesitm"]
    assert first.atpn == raw["atpnQesitm"]
    assert first.intrc == raw["intrcQesitm"]
    assert first.se == raw["seQesitm"]
    assert "사용법" in first.label_sections() and "만 7~12세" in first.label_sections()["사용법"]
    assert res.has_more  # 3건 중 7건


def test_dates_normalized_and_raw_kept():
    res = make_client(FakeServer(ok("hit_tylenol"))).search_by_name("타이레놀", num_of_rows=3)
    it = res.items[0]
    assert it.open_de and it.open_date is not None and it.open_date.strftime("%Y%m%d") == it.open_de
    if it.update_de:
        assert it.update_date is not None and it.update_date.isoformat() == it.update_de


def test_empty_rx_methotrexate_is_empty_not_error():
    res = make_client(FakeServer(ok("empty_rx_methotrexate"))).search_by_name("메토트렉세이트", num_of_rows=3)
    assert res.ok and res.empty and res.items == [] and res.total_count == 0 and res.error is None
    assert not res.has_more


def test_page2_no_filter():
    server = FakeServer(ok("page2_no_filter"))
    res = make_client(server).list_page(page_no=2, num_of_rows=3)
    assert res.ok and res.page_no == 2 and res.total_count > 4000 and len(res.items) == 3 and res.has_more
    assert "pageNo=2" in str(server.requests[0].url) and "numOfRows=3" in str(server.requests[0].url)
    assert "itemName" not in str(server.requests[0].url)


def test_item_key_with_trailing_space_is_trimmed():
    body = {"header": {"resultCode": "00", "resultMsg": "OK"},
            "body": {"pageNo": 1, "totalCount": 1, "numOfRows": 100, "items": [{"itemSeq": 123456789, "itemName ": "가짜정", "efcyQesitm": " 앞뒤 공백 유지\n"}]}}
    res = make_client(FakeServer(httpx.Response(200, json=body))).get_by_item_seq("123456789")
    assert res.items[0].item_name == "가짜정" and res.items[0].item_seq == "123456789"
    assert res.items[0].efcy == " 앞뒤 공백 유지\n"


def test_single_item_dict_is_wrapped():
    body = {"header": {"resultCode": "00"}, "body": {"totalCount": 1, "items": {"itemSeq": "111111111"}}}
    res = make_client(FakeServer(httpx.Response(200, json=body))).get_by_item_seq("111111111")
    assert [i.item_seq for i in res.items] == ["111111111"]


# ---------------------------------------------------------------------------------------------
# 조회 시각·캐시
# ---------------------------------------------------------------------------------------------
def test_queried_at_is_utc_iso_and_display():
    res = make_client(FakeServer(ok("hit_tylenol"))).search_by_name("타이레놀")
    parsed = datetime.strptime(res.queried_at_utc, "%Y-%m-%dT%H:%M:%SZ")
    assert abs((datetime.now(UTC).replace(tzinfo=None) - parsed).total_seconds()) < 30
    assert res.queried_at_display.endswith("(KST)") and res.source == "live" and not res.from_cache


def test_second_identical_request_is_served_from_cache():
    server = FakeServer(ok("hit_tylenol"))
    client = make_client(server)
    first = client.search_by_name("타이레놀")
    second = client.search_by_name("타이레놀")
    assert len(server.requests) == 1
    assert second.from_cache and second.source == "cache" and not first.from_cache
    assert second.queried_at_utc == first.queried_at_utc  # 데이터를 받은 시각이 유지된다
    assert second.items == first.items


def test_different_request_is_not_cache_hit():
    server = FakeServer(ok("hit_tylenol"))
    client = make_client(server)
    client.search_by_name("타이레놀")
    client.search_by_name("타이레놀", page_no=2)
    assert len(server.requests) == 2


def test_cache_ttl_expiry():
    now = [1000.0]
    cache = ResponseCache(ttl_seconds=10, clock=lambda: now[0])
    server = FakeServer(ok("hit_tylenol"))
    client = make_client(server, cache=cache)
    client.search_by_name("타이레놀")
    now[0] += 5
    assert client.search_by_name("타이레놀").from_cache
    now[0] += 20
    assert not client.search_by_name("타이레놀").from_cache
    assert len(server.requests) == 2


def test_file_cache_survives_new_cache_object(tmp_path):
    server = FakeServer(ok("hit_tylenol"))
    make_client(server, cache=ResponseCache(tmp_path, ttl_seconds=60)).search_by_name("타이레놀")
    again = make_client(FakeServer(AssertionError("호출되면 안 됨")), cache=ResponseCache(tmp_path, ttl_seconds=60)).search_by_name("타이레놀")
    assert again.ok and again.from_cache
    assert FAKE_KEY not in "".join(p.read_text(encoding="utf-8") for p in tmp_path.glob("*.json"))


def test_errors_are_not_cached():
    server = FakeServer(httpx.Response(429), ok("hit_tylenol"))
    client = make_client(server)
    assert not client.search_by_name("타이레놀").ok
    assert client.search_by_name("타이레놀").ok
    assert len(server.requests) == 2


# ---------------------------------------------------------------------------------------------
# 오류·제한
# ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("response", [
    httpx.Response(429, text="Too Many Requests"),
    httpx.Response(200, text="<OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>"
                              "<returnReasonCode>22</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>"),
    httpx.Response(200, json={"header": {"resultCode": "22", "resultMsg": "LIMITED NUMBER OF SERVICE REQUESTS EXCEEDS ERROR."}}),
])
def test_rate_limit_returns_clear_error_object_without_retry(response):
    server = FakeServer(response)
    res = make_client(server).search_by_name("타이레놀")
    assert not res.ok and res.items == [] and res.error.kind == "rate_limit" and not res.error.retryable
    assert "호출 제한" in res.error.message
    assert len(server.requests) == 1  # 제한 오류는 재시도하지 않는다


def test_auth_error_403():
    res = make_client(FakeServer(httpx.Response(403, text="<OpenAPI_ServiceResponse><cmmMsgHeader><returnReasonCode>30</returnReasonCode>"
                                                           "</cmmMsgHeader></OpenAPI_ServiceResponse>"))).search_by_name("타이레놀")
    assert res.error.kind == "auth" and res.error.http_status == 403


def test_timeout_retries_up_to_limit_then_error():
    server = FakeServer(httpx.ReadTimeout("느림"))
    res = make_client(server, max_retries=2).search_by_name("타이레놀")
    assert res.error.kind == "timeout" and res.error.retryable
    assert len(server.requests) == 3  # 첫 시도 + 재시도 2회


def test_5xx_then_success_retries():
    server = FakeServer(httpx.Response(503), ok("hit_tylenol"))
    res = make_client(server).search_by_name("타이레놀")
    assert res.ok and len(server.requests) == 2


def test_retry_cap_is_enforced():
    server = FakeServer(httpx.ConnectError("x"))
    make_client(server, max_retries=99).search_by_name("타이레놀")
    assert len(server.requests) == _http.MAX_RETRIES_CAP + 1


def test_call_budget_stops_further_calls():
    server = FakeServer(ok("hit_tylenol"))
    client = make_client(server, cache=False, max_calls=2)
    assert client.search_by_name("타이레놀").ok
    assert client.search_by_name("타이레놀", page_no=2).ok
    res = client.search_by_name("타이레놀", page_no=3)
    assert res.error.kind == "call_budget" and len(server.requests) == 2


def test_non_json_body_is_parse_error():
    res = make_client(FakeServer(httpx.Response(200, text="<html>점검 중</html>"))).search_by_name("타이레놀")
    assert res.error.kind == "parse"


def test_network_error_message_has_no_key():
    res = make_client(FakeServer(httpx.ConnectError(f"fail https://x/?serviceKey={FAKE_KEY}"))).search_by_name("타이레놀")
    assert res.error.kind == "network" and FAKE_KEY not in res.model_dump_json()


def test_missing_config_is_config_error():
    res = EyakClient(ApiHttpClient("eyak", None, None)).search_by_name("타이레놀")
    assert res.error.kind == "config"


@pytest.mark.parametrize("name", ["", "   ", "가" * 101, "a\nb"])
def test_invalid_name_is_rejected_without_call(name):
    server = FakeServer(ok("hit_tylenol"))
    res = make_client(server).search_by_name(name)
    assert res.error.kind == "invalid_request" and not server.requests


@pytest.mark.parametrize("seq", ["", "12345", "12345678a", "1234567890", None])
def test_invalid_item_seq_is_rejected_without_call(seq):
    server = FakeServer(ok("hit_tylenol"))
    assert make_client(server).get_by_item_seq(seq).error.kind == "invalid_request" and not server.requests


@pytest.mark.parametrize("page,rows", [(0, 10), (1, 0), (1, 101), (True, 10)])
def test_invalid_paging_is_rejected(page, rows):
    server = FakeServer(ok("hit_tylenol"))
    assert make_client(server).search_by_name("타이레놀", page_no=page, num_of_rows=rows).error.kind == "invalid_request"
    assert not server.requests


def test_request_url_has_key_but_result_never_does():
    server = FakeServer(ok("hit_tylenol"))
    res = make_client(server).search_by_name("타이레놀")
    assert "serviceKey=" in str(server.requests[0].url)
    assert FAKE_KEY not in res.model_dump_json()
    assert mask_secret(f"k={FAKE_KEY}", FAKE_KEY) == "k=***"


def test_parse_response_maps_codes():
    assert pytest.raises(ApiError, parse_response, json.dumps({"header": {"resultCode": "30"}, "body": {}})).value.kind == "auth"
    assert pytest.raises(ApiError, parse_response, json.dumps({"header": {"resultCode": "99", "resultMsg": "x"}, "body": {}})).value.kind == "service"


# ---------------------------------------------------------------------------------------------
# 요청 해시·스냅샷(이관 시험)
# ---------------------------------------------------------------------------------------------
def test_request_hash_matches_snapshot_collector():
    """`evaluation/mock_gen/api_snapshot.py`가 manifest.jsonl에 남긴 해시(타이레놀 identify)와 같아야 한다."""
    assert request_hash("eyak", "getDrbEasyDrugList", {"itemName": "타이레놀"}) == "baa15a87ab716e41"


def snapshot_client(**kw) -> EyakClient:
    return EyakClient(ApiHttpClient("eyak", BASE, FAKE_KEY, mode="snapshot", **kw))


@needs_snapshots
def test_snapshot_mode_reads_tylenol_without_network():
    res = snapshot_client().search_by_name("타이레놀")
    assert res.ok and res.source == "snapshot" and res.from_cache
    assert res.total_count == 7 and len(res.items) == 7
    assert {i.item_seq for i in res.items} >= {"202005623"}
    assert all(i.efcy for i in res.items)


@needs_snapshots
@pytest.mark.parametrize("name", ["이지렉트", "에소메졸", "미프론", "심바로드", "로바스크"])
def test_snapshot_prescription_drugs_are_empty(name):
    res = snapshot_client().search_by_name(name)
    assert res.ok and res.empty


@needs_snapshots
def test_snapshot_miss_is_explicit_error_not_network():
    res = snapshot_client().search_by_name("스냅샷에없는가상약이름")
    assert not res.ok and res.error.kind == "snapshot_miss"


@needs_snapshots
def test_snapshot_item_seq_lookup():
    res = snapshot_client().get_by_item_seq("202005623")
    if res.error and res.error.kind == "snapshot_miss":
        pytest.skip("이 품목기준코드 스냅샷 없음")
    assert res.ok and [i.item_seq for i in res.items] == ["202005623"]


def test_from_settings_uses_config_without_env_file(tmp_path):
    s = Settings(drdeasydrug_end_point=BASE, drdeasydrug_api_key=FAKE_KEY, mediagent_api_mode="snapshot", _env_file=None)
    client = EyakClient.from_settings(s)
    assert client._http.mode == "snapshot" and client._http.base_url == BASE
    assert FAKE_KEY not in repr(client._http)


# ---------------------------------------------------------------------------------------------
# be-fix: 요청 해시·절 단위 항목·스냅샷 시각 구분
# ---------------------------------------------------------------------------------------------
def test_result_carries_request_hash_and_not_on_failure():
    server = FakeServer(ok("hit_tylenol"))
    res = make_client(server).search_by_name("타이레놀", num_of_rows=3)
    assert res.request_hash and len(res.request_hash) >= 16
    bad = make_client(FakeServer()).search_by_name("")
    assert not bad.ok and bad.request_hash is None


def test_label_section_items_keep_empty_sections_and_evidence_ids():
    body = {"header": {"resultCode": "00"},
            "body": {"pageNo": 1, "totalCount": 1, "numOfRows": 100,
                     "items": [{"itemSeq": "202106954", "itemName": "가짜정", "efcyQesitm": " 효능 원문\n",
                                "intrcQesitm": None, "seQesitm": "   "}]}}
    item = make_client(FakeServer(httpx.Response(200, json=body))).get_by_item_seq("202106954").items[0]
    secs = item.label_section_items()
    assert [s.key for s in secs] == ["efcy", "use_method", "atpn_warn", "atpn", "intrc", "se"]
    assert [s.label for s in secs] == ["효능", "사용법", "경고", "주의사항", "상호작용", "부작용"]
    by = {s.key: s for s in secs}
    assert by["efcy"].text == " 효능 원문\n" and not by["efcy"].empty              # 원문 그대로
    assert by["intrc"].empty and by["intrc"].text is None                         # 빈 절도 남김
    assert by["se"].empty and by["se"].text == "   "
    assert by["intrc"].evidence_id == "eyak:202106954:intrc"
    assert len({s.evidence_id for s in secs}) == 6
    assert set(item.label_sections()) == {"효능", "부작용"}                         # 기존 함수는 그대로(None만 뺀다, 공백뿐인 절은 남는다)


def test_snapshot_time_is_distinguished_from_fetch_time():
    from app.tools.eyak import EyakResult

    snap = EyakResult(ok=True, source="snapshot", queried_at_utc="2026-11-05T00:00:00Z")
    live = EyakResult(ok=True, source="live")
    cached = EyakResult(ok=True, source="cache", from_cache=True)
    assert (snap.queried_at_kind, snap.flags) == ("SNAPSHOT_COLLECTED", ["SNAPSHOT_TIME"])
    assert (live.queried_at_kind, live.flags) == ("FETCHED", [])
    assert cached.queried_at_kind == "FETCHED"
    assert EyakResult(ok=False).queried_at_kind is None
    assert snap.model_dump()["queried_at_kind"] == "SNAPSHOT_COLLECTED"
