"""OpenAI 비용 일일 보고 시험(DevOps 2026-11-24). 실제 OpenAI·카카오 호출 0(가짜 HTTP·가짜 전송기), `.env` 미사용."""

from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import sys
import urllib.error
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings

BACKEND = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("openai_usage_report_t", BACKEND / "scripts" / "openai_usage_report.py")
rep = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = rep  # dataclass가 모듈을 찾을 수 있게
spec.loader.exec_module(rep)

@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """전체 시험 중 다른 시험이 환경변수로 실제 키를 남겨도 `Settings(_env_file=None)`에 섞이지 않게 한다(2026-11-24 순서 의존 실패 재현)."""
    for name in ("OPENAI_ADMIN_KEY", "KAKAO_REST_API_KEY", "KAKAO_CLIENT_SECRET", "KAKAO_REFRESH_TOKEN", "MEDIAGENT_NOTIFY"):
        monkeypatch.delenv(name, raising=False)


KST = ZoneInfo("Asia/Seoul")
ADMIN = "sk-admin-SECRETVALUE-123"
NOW = datetime(2026, 11, 24, 12, 0, tzinfo=KST)


def bucket(day: datetime, items: dict[str, float]) -> dict:
    start = int(day.timestamp())
    return {"object": "bucket", "start_time": start, "end_time": start + 86400,
            "results": [{"object": "organization.costs.result", "line_item": k, "amount": {"value": v, "currency": "usd"}}
                        for k, v in items.items()]}


def kst_day(m: int, d: int) -> datetime:
    return datetime(2026, m, d, tzinfo=KST)


def utc_day(m: int, d: int) -> datetime:
    """UTC 자정. OpenAI 일 버킷의 실제 정렬 시각이자 요청 창 경계(2026-11-24 실측)."""
    return datetime(2026, m, d, tzinfo=UTC)


def sample() -> list[dict]:
    return [
        bucket(kst_day(11, 1), {"gpt-6-luna, input_tokens": 1.0}),
        bucket(kst_day(11, 18), {"gpt-6-luna, input_tokens": 2.0, "gpt-6-luna, output_tokens": 1.0}),
        bucket(kst_day(11, 23), {"gpt-6-luna, input_tokens": 0.5, "embed, input": 0.25}),
        bucket(kst_day(11, 24), {"gpt-6-luna, input_tokens": 99.0}),  # 진행 중(오늘) 버킷: 제외돼야 한다
    ]


class FakeFetch:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url, headers):
        self.calls.append((url, headers))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeNotifier:
    def __init__(self, fail=False):
        self.sent: list[str] = []
        self.fail = fail

    def send_now(self, text):
        if self.fail:
            raise RuntimeError("memo send rejected (HTTP 401)")
        self.sent.append(text)


def settings(admin=ADMIN):
    return Settings(_env_file=None, openai_admin_key=admin) if admin else Settings(_env_file=None)


def run(argv, fetch, notifier=None, st=None, now=NOW):
    out, err = io.StringIO(), io.StringIO()
    code = rep.run(argv, settings=st or settings(), fetch=fetch, notifier=notifier, now=now, log_path=None, out=out, err=err)
    return code, out.getvalue(), err.getvalue()


def test_parse_excludes_in_progress_and_sums():
    buckets = rep.parse_buckets(sample(), NOW)
    totals = {b.day.isoformat(): b.total for b in buckets}
    assert totals == {"2026-11-01": 1.0, "2026-11-18": 3.0, "2026-11-23": 0.75}


def msgs_for(raw, today, now=None):
    now = now or datetime(today.year, today.month, today.day, 12, tzinfo=KST)
    return rep.build_messages(rep.parse_buckets(raw, now), today, 7)


def test_monday_yesterday_is_single_week_line():
    msgs = rep.build_messages(rep.parse_buckets(sample(), NOW), NOW.date(), 7)  # 어제 = 11/23(월)
    assert len(msgs) == 1
    assert msgs[0].split("\n") == [rep.PREFIX, "2026 (UTC)", "ISO 48/53(11/23~11/29) Total $0.75", "MON(11/23) $0.75"]
    assert all(len(m) <= rep.MAX_LEN for m in msgs)
    for gone in ("11월 누적", "7일 합계", "합계", "gpt-6-luna", "추이"):  # 옛 보고 줄은 없다
        assert gone not in msgs[0]


def test_sunday_yesterday_is_single_sun_line_under_last_week_header():
    today = datetime(2026, 11, 30).date()  # 어제 = 11/29(일): 헤더는 지난주(11/23~11/29)
    raw = [bucket(kst_day(11, 22), {"x": 50.0}),  # 그 전주: 포함되면 안 된다
           bucket(kst_day(11, 23), {"x": 0.75}), bucket(kst_day(11, 25), {"x": 1.25}), bucket(kst_day(11, 29), {"x": 2.0})]
    lines = msgs_for(raw, today)[0].split("\n")
    assert lines == [rep.PREFIX, "2026 (UTC)", "ISO 48/53(11/23~11/29) Total $4.00", "SUN(11/29) $2.00"]  # Total은 월~어제 누적(0.75+1.25+2.0), 줄은 어제만


@pytest.mark.parametrize(("yday", "abbr"), [(25, "WED"), (26, "THU"), (27, "FRI"), (28, "SAT"), (29, "SUN"), (30, "MON"), (24, "TUE")])
def test_daily_report_shows_only_yesterday_for_every_weekday(yday, abbr):
    """어제가 무슨 요일이든 일별 줄은 어제 하나뿐이고 Total은 월요일~어제의 주간 누적이다(2026-11-25 수정)."""
    d = datetime(2026, 11, 24) + timedelta(days=yday - 24)  # 11/24(화)부터 11/30(월)
    today = (d + timedelta(days=1)).date()
    raw = [bucket(kst_day(11, n), {"x": float(n)}) for n in range(23, 31)]  # 날마다 다른 값(11/23=23 ... 11/30=30)
    monday = d - timedelta(days=d.weekday())
    week_total = sum(n for n in range(monday.day, d.day + 1))  # 같은 달 안에서만 쓰는 시험
    lines = msgs_for(raw, today)[0].split("\n")
    assert len(lines) == 4 and lines[0] == rep.PREFIX and lines[1] == "2026 (UTC)"
    assert lines[3] == f"{abbr}({d:%m/%d}) ${float(d.day):.2f}"
    assert lines[2].endswith(f"Total ${float(week_total):.2f}")
    assert sum(1 for ln in lines if ln.startswith(rep.DAY_ABBR)) == 1


def test_week_does_not_leak_previous_week_or_include_today():
    raw = [bucket(kst_day(11, 22), {"x": 50.0}), bucket(kst_day(11, 23), {"x": 2.0}), bucket(kst_day(11, 24), {"x": 9.0})]
    msgs = rep.build_messages(rep.parse_buckets(raw, NOW), NOW.date(), 7)
    assert "Total $2.00" in msgs[0] and "11/22)" not in msgs[0] and "11/24)" not in msgs[0]  # 11/24는 진행 중이라 제외


def test_week_crossing_month_boundary():
    today = datetime(2026, 12, 4).date()  # 어제 = 12/03(목), 주 = 11/30~12/06
    raw = [bucket(kst_day(11, 30), {"x": 1.0}), bucket(kst_day(12, 3), {"x": 0.5})]
    lines = msgs_for(raw, today)[0].split("\n")
    assert lines == [rep.PREFIX, "2026 (UTC)", "ISO 49/53(11/30~12/06) Total $1.50", "THU(12/03) $0.50"]  # 월 경계 헤더 유지, Total은 11/30~어제 누적, 줄은 어제만


@pytest.mark.parametrize(("today", "year", "head", "last_day"), [
    (datetime(2027, 1, 1).date(), "2026 (UTC)", "ISO 53/53(12/28~01/03) Total $0.00", "THU(12/31) $0.00"),  # 어제 = 2026-12-31, 2026은 53주 해
    (datetime(2027, 1, 2).date(), "2026 (UTC)", "ISO 53/53(12/28~01/03) Total $0.00", "FRI(01/01) $0.00"),  # 달력은 2027이어도 ISO 연도는 2026
    (datetime(2027, 1, 5).date(), "2027 (UTC)", "ISO 1/52(01/04~01/10) Total $0.00", "MON(01/04) $0.00"),  # 2027은 52주 해
    (datetime(2025, 12, 31).date(), "2026 (UTC)", "ISO 1/53(12/29~01/04) Total $0.00", "TUE(12/30) $0.00"),  # 달력은 2025이어도 ISO 2026 1주
])
def test_iso_year_and_week_count_at_year_end(today, year, head, last_day):
    lines = msgs_for([], today)[0].split("\n")
    assert lines[1] == year and lines[2] == head and lines[-1] == last_day


def test_no_cost_days_show_zero_not_missing():
    raw = [bucket(kst_day(11, 23), {})]  # 버킷은 있으나 항목 없음
    assert msgs_for(raw, datetime(2026, 11, 24).date())[0].split("\n")[3] == "MON(11/23) $0.00"
    assert msgs_for([], datetime(2026, 11, 24).date())[0].split("\n")[3] == "MON(11/23) $0.00"


def test_seoul_boundary_attribution():
    # 2026-11-22 15:00 UTC == 2026-11-23 00:00 KST: 서울 11/23로 귀속
    start = int(datetime(2026, 11, 22, 15, tzinfo=UTC).timestamp())
    raw = [{"start_time": start, "end_time": start + 86400, "results": [{"line_item": "a", "amount": {"value": 1.5, "currency": "usd"}}]}]
    assert [b.day.isoformat() for b in rep.parse_buckets(raw, NOW)] == ["2026-11-23"]
    # UTC 날짜로 보면 11/22이지만 서울 기준 11/23
    assert datetime.fromtimestamp(start, UTC).date().isoformat() == "2026-11-22"


def test_request_window_is_utc_midnight_and_params():
    f = FakeFetch([(200, {"data": [], "has_more": False})])
    code, _, _ = run(["--days", "7"], f)  # 어제 = 월요일 11/23: 창은 그 주 월요일 00:00Z ~ 오늘 00:00Z
    assert code == 0
    url, headers = f.calls[0]
    end = int(utc_day(11, 24).timestamp())
    assert f"end_time={end}" in url and "bucket_width=1d" in url and "group_by=line_item" in url and "limit=180" in url
    assert f"start_time={int(utc_day(11, 23).timestamp())}" in url  # --days는 무시, 월초도 아님
    assert headers["Authorization"] == f"Bearer {ADMIN}"


def _utc_bucket(day: datetime, items: dict[str, float]) -> dict:
    return bucket(day, items)  # day가 UTC 자정이면 실제 API 버킷과 같은 정렬


def test_utc_midnight_bucket_is_attributed_to_seoul_date_of_start():
    # 실제 API 버킷: 시작 00:00Z == 서울 09:00 -> 서울 날짜는 UTC 날짜와 같다
    raw = [_utc_bucket(utc_day(11, 20), {"a": 1.25}), _utc_bucket(utc_day(11, 23), {"a": 0.5})]
    assert [(b.day.isoformat(), b.total) for b in rep.parse_buckets(raw, NOW)] == [("2026-11-20", 1.25), ("2026-11-23", 0.5)]
    today = datetime(2026, 11, 24).date()
    lines = msgs_for([_utc_bucket(utc_day(11, 20), {"a": 1.25})], today)[0].split("\n")
    assert lines[2] == "ISO 48/53(11/23~11/29) Total $0.00"  # 11/20은 어제(11/23)가 속한 주가 아니라 제외
    lines = msgs_for([_utc_bucket(utc_day(11, 20), {"a": 1.25})], datetime(2026, 11, 21).date())[0].split("\n")  # 어제 = 11/20(금)
    assert "FRI(11/20) $1.25" in lines


def test_request_window_bounds_are_integer_utc_midnight_timestamps():
    import re
    f = FakeFetch([(200, {"data": [], "has_more": False})])
    code, _, _ = run([], f)
    assert code == 0
    start = int(re.search(r"start_time=(\d+)", f.calls[0][0]).group(1))
    end = int(re.search(r"end_time=(\d+)", f.calls[0][0]).group(1))
    assert start % 86400 == 0 and end % 86400 == 0  # UTC 자정이면 에포크 초가 86400의 배수
    assert datetime.fromtimestamp(start, UTC) == utc_day(11, 23) and datetime.fromtimestamp(end, UTC) == utc_day(11, 24)
    f = FakeFetch([(200, {"data": [], "has_more": False})])
    run(["--date", "2026-11-18"], f)
    start = int(re.search(r"start_time=(\d+)", f.calls[0][0]).group(1))
    end = int(re.search(r"end_time=(\d+)", f.calls[0][0]).group(1))
    assert start == int(utc_day(11, 18).timestamp()) and end == int(utc_day(11, 24).timestamp())
    assert start % 86400 == 0 and end % 86400 == 0


def test_yesterday_utc_bucket_is_included_in_report_at_seoul_noon():
    # 11-24 12:00(서울) 기준: 어제 버킷 [11-23 00:00Z, 11-24 00:00Z)은 끝났으므로 포함, 오늘 버킷 [11-24 00:00Z~)은 진행 중이라 제외
    raw = [_utc_bucket(utc_day(11, 22), {"x": 40.0}),  # 지난주 일요일
           _utc_bucket(utc_day(11, 23), {"x": 1.5}),
           _utc_bucket(utc_day(11, 24), {"x": 9.0})]
    code, out, _ = run([], FakeFetch([(200, {"data": raw, "has_more": False})]), now=datetime(2026, 11, 24, 12, 0, tzinfo=KST))
    assert code == 0
    assert out.split("\n")[:4] == [rep.PREFIX, "2026 (UTC)", "ISO 48/53(11/23~11/29) Total $1.50", "MON(11/23) $1.50"]
    assert "$9.00" not in out and "$40.00" not in out


def test_request_window_starts_at_monday_of_yesterdays_week():
    f = FakeFetch([(200, {"data": [], "has_more": False})])
    code, _, _ = run([], f, now=datetime(2026, 11, 30, 9, 0, tzinfo=KST))  # 어제 = 일요일 11/29
    assert code == 0
    url = f.calls[0][0]
    assert f"start_time={int(utc_day(11, 23).timestamp())}" in url and f"end_time={int(utc_day(11, 30).timestamp())}" in url


def test_days_option_is_ignored_for_default_report():
    outs = []
    for argv in ([], ["--days", "3"], ["--days", "31"]):
        code, out, _ = run(argv, FakeFetch([(200, {"data": sample(), "has_more": False})]))
        assert code == 0
        outs.append(out)
    assert outs[0] == outs[1] == outs[2] and "MON(11/23) $0.75" in outs[0]


def test_pagination_followed():
    f = FakeFetch([(200, {"data": [bucket(kst_day(11, 22), {"a": 1.0})], "has_more": True, "next_page": "CURSOR1"}),
                   (200, {"data": [bucket(kst_day(11, 23), {"a": 2.0})], "has_more": False, "next_page": None})])
    code, out, _ = run([], f)
    assert code == 0 and len(f.calls) == 2 and "page=CURSOR1" in f.calls[1][0]
    assert "MON(11/23) $2.00" in out and "Total $2.00" in out and "11/22)" not in out  # 지난주 일요일 버킷은 제외


@pytest.mark.parametrize(("value", "text"), [(0.0, "$0.00"), (1234.5, "$1,234.50"), (0.0004, "$0.00"), (0.004, "$0.00"), (0.006, "$0.01"), (12.346, "$12.35")])
def test_fmt_usd(value, text):
    assert rep.fmt_usd(value) == text


def test_message_is_single_and_capped_at_max_len():
    today = datetime(2026, 11, 30).date()  # 7줄(일요일이 어제)
    typical = [bucket(kst_day(11, d), {"a": 12.34}) for d in range(23, 30)]
    msgs = msgs_for(typical, today)
    assert len(msgs) == 1 and len(msgs[0]) <= rep.MAX_LEN and not msgs[0].endswith("…")
    huge = [bucket(kst_day(11, d), {"a": 1234567.89}) for d in range(23, 30)]
    msgs = msgs_for(huge, today)
    assert len(msgs) == 1 and len(msgs[0]) <= rep.MAX_LEN and msgs[0].startswith(rep.PREFIX)
    assert len(rep._pack(["x" * 500, "b"])) <= rep.MAX_LEN


def test_dry_run_never_calls_kakao():
    n = FakeNotifier()
    f = FakeFetch([(200, {"data": sample(), "has_more": False})])
    code, out, _ = run(["--dry-run"], f, notifier=n)
    assert code == 0 and n.sent == [] and rep.PREFIX in out
    f2 = FakeFetch([(200, {"data": sample(), "has_more": False})])
    code, _, _ = run([], f2, notifier=n)  # 기본도 dry-run
    assert code == 0 and n.sent == []


def test_send_sends_messages():
    n = FakeNotifier()
    f = FakeFetch([(200, {"data": sample(), "has_more": False})])
    code, _, _ = run(["--send"], f, notifier=n)
    assert code == 0 and len(n.sent) == 1 and n.sent[0].startswith(rep.PREFIX)  # 기본 보고는 한 건


def test_send_without_kakao_config_exits_nonzero_without_http():
    f = FakeFetch([])
    code, _, err = run(["--send"], f)  # 카카오 설정 없음 -> from_settings None
    assert code == 2 and "kakao_not_configured" in err and f.calls == []


def test_missing_admin_key_no_send_no_http():
    n, f = FakeNotifier(), FakeFetch([])
    code, _, err = run(["--send"], f, notifier=n, st=settings(admin=None))
    assert code == 2 and "admin_key_missing" in err and n.sent == [] and f.calls == []


@pytest.mark.parametrize(("responses", "kind"), [
    ([(401, {}), (401, {})], "http_401"),
    ([(500, {}), (500, {})], "http_500"),
    ([TimeoutError(), TimeoutError()], "timeout"),
    ([urllib.error.URLError("boom"), urllib.error.URLError("boom")], "network_error"),
    ([(200, {"data": [{"start_time": "x"}], "has_more": False})], "bad_response"),
])
def test_api_errors_do_not_leak_exceptions(responses, kind):
    n = FakeNotifier()
    f = FakeFetch(responses)
    code, out, err = run(["--send", "--notify-failure"], f, notifier=n)
    assert code == 3 and kind in err and out == ""
    assert n.sent == [f"{rep.PREFIX} OpenAI 비용 보고 실패({kind})"]
    assert ADMIN not in err and ADMIN not in n.sent[0]


def test_4xx_not_retried_5xx_retried_once_then_ok():
    f = FakeFetch([(403, {})])
    run([], f)
    assert len(f.calls) == 1
    f = FakeFetch([(500, {}), (200, {"data": sample(), "has_more": False})])
    code, _, _ = run([], f)
    assert code == 0 and len(f.calls) == 2


def test_no_notify_failure_flag_means_no_kakao_on_error():
    n = FakeNotifier()
    code, _, _ = run(["--send"], FakeFetch([(401, {}), (401, {})]), notifier=n)
    assert code == 3 and n.sent == []


def test_kakao_send_failure_exit_4_no_value_leak():
    n = FakeNotifier(fail=True)
    f = FakeFetch([(200, {"data": sample(), "has_more": False})])
    code, _, err = run(["--send"], f, notifier=n)
    assert code == 4 and "kakao_send_failed(RuntimeError)" in err and ADMIN not in err


def test_log_line_has_no_secrets(tmp_path):
    log = tmp_path / "logs" / "r.log"
    out, err = io.StringIO(), io.StringIO()
    f = FakeFetch([(401, {}), (401, {})])
    rep.run([], settings=settings(), fetch=f, now=NOW, log_path=log, out=out, err=err)
    text = log.read_text()
    assert "fail kind=http_401" in text and ADMIN not in text
    f = FakeFetch([(200, {"data": sample(), "has_more": False})])
    rep.run([], settings=settings(), fetch=f, now=NOW, log_path=log, out=out, err=err)
    assert "ok mode=dry-run" in log.read_text() and ADMIN not in log.read_text() and ADMIN not in out.getvalue()


def test_days_out_of_range():
    code, _, err = run(["--days", "0"], FakeFetch([]))
    assert code == 2 and "--days" in err


def test_message_has_no_project_or_user_ids():
    raw = [bucket(kst_day(11, 23), {"gpt-6-luna, input_tokens": 1.0})]
    raw[0]["results"][0]["project_id"] = "proj_SECRETPROJECT"
    text = "\n".join(rep.build_messages(rep.parse_buckets(raw, NOW), NOW.date(), 7))
    assert "proj_" not in text


# ---- 설치 스크립트 ----

SH = BACKEND / "scripts" / "launchd" / "install_usage_report.sh"


def _sh(args, tmp_path, python_exists=True):
    agents = tmp_path / "LaunchAgents"
    fake_ctl = tmp_path / "ctl.sh"
    fake_ctl.write_text(f'#!/bin/bash\necho "$@" >> "{tmp_path}/ctl.log"\n')
    fake_ctl.chmod(0o755)
    py = tmp_path / "python"
    if python_exists:
        py.write_text("#!/bin/sh\n")
        py.chmod(0o755)
    env = {**os.environ, "LAUNCH_AGENTS_DIR": str(agents), "LAUNCHCTL": str(fake_ctl), "USAGE_REPORT_PYTHON": str(py), "HOME": str(tmp_path)}
    r = subprocess.run(["bash", str(SH), *args], env=env, capture_output=True, text=True, check=False)  # noqa: S603, S607
    return r, agents


def test_install_without_yes_writes_nothing(tmp_path):
    r, agents = _sh([], tmp_path)
    assert r.returncode == 0 and "계획" in r.stdout
    assert not agents.exists() and not (tmp_path / "ctl.log").exists()
    r, agents = _sh(["--uninstall"], tmp_path)
    assert r.returncode == 0 and not agents.exists() and not (tmp_path / "ctl.log").exists()


def test_install_yes_writes_plist_and_bootstraps(tmp_path):
    r, agents = _sh(["--yes"], tmp_path)
    assert r.returncode == 0, r.stderr
    plist = (agents / "com.mediagent.openai-usage-report.plist").read_text()
    assert "@PYTHON@" not in plist and "@REPO_ROOT@" not in plist and str(tmp_path / "python") in plist
    assert "<integer>12</integer>" in plist and "--send" in plist
    assert "bootstrap" in (tmp_path / "ctl.log").read_text()
    r, _ = _sh(["--uninstall", "--yes"], tmp_path)
    assert r.returncode == 0 and not (agents / "com.mediagent.openai-usage-report.plist").exists()


def test_install_yes_without_python_refuses(tmp_path):
    r, agents = _sh(["--yes"], tmp_path, python_exists=False)
    assert r.returncode == 1 and not agents.exists()


def test_unknown_arg_rejected(tmp_path):
    r, _ = _sh(["--bogus"], tmp_path)
    assert r.returncode == 2


def test_timedelta_import_used():  # 시험 파일 import 정리용 보호(ruff F401 방지)
    assert timedelta(days=1).days == 1


# ---- --as-of / --date / --week-of ----

def test_as_of_changes_reference_and_excludes_later_buckets():
    f = FakeFetch([(200, {"data": sample(), "has_more": False})])
    code, out, _ = run(["--as-of", "2026-11-19"], f, now=NOW)  # 어제 = 11/18(수), 주 = 11/16~11/22
    assert code == 0
    lines = out.split("\n")
    assert lines[2] == "ISO 47/53(11/16~11/22) Total $3.00"
    assert lines[3] == "WED(11/18) $3.00" and lines[4] == "---"  # 어제 하루만. 11/23 이후 버킷은 기준일 이후라 제외
    assert "11/23)" not in out and "0.75" not in out
    assert f"start_time={int(utc_day(11, 16).timestamp())}" in f.calls[0][0]
    assert f"end_time={int(utc_day(11, 19).timestamp())}" in f.calls[0][0]


def test_date_option_lines_and_missing():
    f = FakeFetch([(200, {"data": sample(), "has_more": False})])
    code, out, _ = run(["--date", "2026-11-23", "--date", "2026-11-18", "--date", "2026-11-20"], f)
    assert code == 0
    assert out.index("WED(2026/11/18) $3.00") < out.index("FRI(2026/11/20) 집계 없음") < out.index("MON(2026/11/23) $0.75")
    assert "(수)" not in out and "-11-" not in out  # 한글 요일·하이픈 날짜는 없다
    assert out.startswith(rep.PREFIX + "\n")
    assert f"start_time={int(utc_day(11, 18).timestamp())}" in f.calls[0][0]


def test_week_of_uses_same_format_as_daily_report():
    f = FakeFetch([(200, {"data": sample(), "has_more": False})])
    code, out, _ = run(["--week-of", "2026-11-18"], f)  # 수요일 -> 11/16(월)~11/22(일), 끝난 주라 7줄 모두
    assert code == 0 and "합계" not in out and "주간" not in out and "진행 중" not in out
    assert out.split("\n")[:12] == [rep.PREFIX, "2026 (UTC)", "ISO 47/53(11/16~11/22) Total $3.00",
                                    "MON(11/16) $0.00", "TUE(11/17) $0.00", "WED(11/18) $3.00", "THU(11/19) $0.00",
                                    "FRI(11/20) $0.00", "SAT(11/21) $0.00", "SUN(11/22) $0.00", "---", ""]
    assert f"start_time={int(utc_day(11, 16).timestamp())}" in f.calls[0][0]


def test_week_of_in_progress_week_stops_at_yesterday():
    f = FakeFetch([(200, {"data": sample(), "has_more": False})])
    _, out, _ = run(["--week-of", "2026-11-24"], f)  # 11/23(월)~11/29(일), 오늘(11/24) 포함 주 -> 어제(11/23)까지
    lines = out.split("\n")
    assert lines[:4] == [rep.PREFIX, "2026 (UTC)", "ISO 48/53(11/23~11/29) Total $0.75", "MON(11/23) $0.75"]
    assert lines[4] == "---" and "TUE(" not in out and "11/24)" not in out and "$99" not in out  # 오늘 진행분은 제외


def test_week_of_future_week_has_header_only():
    week = [datetime(2026, 11, 30).date() + timedelta(days=i) for i in range(7)]  # 오늘(11/24)보다 뒤 주: 요일 줄 없음
    lines = rep.build_custom_messages([], [], week, NOW.date())[0].split("\n")
    assert lines == [rep.PREFIX, "2026 (UTC)", "ISO 49/53(11/30~12/06) Total $0.00"]


def test_utc_marker_on_year_line_for_daily_and_week_of_but_not_date_report():
    f = FakeFetch([(200, {"data": sample(), "has_more": False})])
    _, daily, _ = run([], f)
    _, week_of, _ = run(["--week-of", "2026-11-18"], FakeFetch([(200, {"data": sample(), "has_more": False})]))
    _, by_date, _ = run(["--date", "2026-11-18"], FakeFetch([(200, {"data": sample(), "has_more": False})]))
    assert daily.split("\n")[1] == "2026 (UTC)"
    assert week_of.split("\n")[1] == "2026 (UTC)"
    assert "UTC" not in by_date and "\n2026\n" not in by_date  # --date 보고에는 연도 줄이 없다


def test_day_abbreviations_are_uppercase_three_letters():
    assert rep.DAY_ABBR == ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def test_custom_messages_split_over_limit():
    dates = [datetime(2026, 11, 1).date() + timedelta(days=i) for i in range(20)]
    msgs = rep.build_custom_messages([], dates, [], NOW.date())
    assert len(msgs) >= 2 and all(len(m) <= rep.MAX_LEN and m.startswith(rep.PREFIX) for m in msgs)


def test_bad_date_format_exit_2():
    code, _, _ = run(["--date", "11-23"], FakeFetch([]))
    assert code == 2
