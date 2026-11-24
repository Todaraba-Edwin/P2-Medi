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


def test_messages_yesterday_week_month():
    buckets = rep.parse_buckets(sample(), NOW)
    msgs = rep.build_messages(buckets, NOW.date(), 7)
    first = msgs[0]
    assert first.startswith(rep.PREFIX)
    assert "11/23 $0.75" in first
    assert "7일 합계 $3.75 (11/17~11/23)" in first  # 11/18 3.0 + 11/23 0.75
    assert "11월 누적 $4.75" in first  # 11/1 1.0 포함
    assert "0.00/3.00/0.00/0.00/0.00/0.00/0.75" in first
    assert "gpt-6-luna, input_tokens $2.50" in msgs[1]
    assert all(len(m) <= rep.MAX_LEN for m in msgs)


def test_month_cumulative_does_not_leak_previous_month():
    raw = [bucket(kst_day(10, 31), {"x": 50.0}), bucket(kst_day(11, 2), {"x": 2.0})]
    msgs = rep.build_messages(rep.parse_buckets(raw, NOW), NOW.date(), 7)
    assert "11월 누적 $2.00" in msgs[0]


def test_seoul_boundary_attribution():
    # 2026-11-22 15:00 UTC == 2026-11-23 00:00 KST: 서울 11/23로 귀속
    start = int(datetime(2026, 11, 22, 15, tzinfo=UTC).timestamp())
    raw = [{"start_time": start, "end_time": start + 86400, "results": [{"line_item": "a", "amount": {"value": 1.5, "currency": "usd"}}]}]
    assert [b.day.isoformat() for b in rep.parse_buckets(raw, NOW)] == ["2026-11-23"]
    # UTC 날짜로 보면 11/22이지만 서울 기준 11/23
    assert datetime.fromtimestamp(start, UTC).date().isoformat() == "2026-11-22"


def test_request_window_is_seoul_midnight_and_params():
    f = FakeFetch([(200, {"data": [], "has_more": False})])
    code, _, _ = run(["--days", "7"], f)
    assert code == 0
    url, headers = f.calls[0]
    end = int(kst_day(11, 24).timestamp())
    assert f"end_time={end}" in url and "bucket_width=1d" in url and "group_by=line_item" in url and "limit=180" in url
    assert f"start_time={int(kst_day(11, 1).timestamp())}" in url  # 월초가 7일 전보다 앞
    assert headers["Authorization"] == f"Bearer {ADMIN}"


def test_pagination_followed():
    f = FakeFetch([(200, {"data": [bucket(kst_day(11, 22), {"a": 1.0})], "has_more": True, "next_page": "CURSOR1"}),
                   (200, {"data": [bucket(kst_day(11, 23), {"a": 2.0})], "has_more": False, "next_page": None})])
    code, out, _ = run([], f)
    assert code == 0 and len(f.calls) == 2 and "page=CURSOR1" in f.calls[1][0]
    assert "11/23 $2.00" in out


@pytest.mark.parametrize(("value", "text"), [(0.0, "$0.00"), (1234.5, "$1,234.50"), (0.0004, "$0.000"), (0.004, "$0.004"), (12.346, "$12.35")])
def test_fmt_usd(value, text):
    assert rep.fmt_usd(value) == text


def test_message_length_split_and_cap():
    raw = [bucket(kst_day(11, d), {f"very-long-model-name-number-{i}, input_tokens": 1.0 for i in range(5)}) for d in range(1, 24)]
    msgs = rep.build_messages(rep.parse_buckets(raw, NOW), NOW.date(), 31)
    assert len(msgs) == 2 and all(len(m) <= rep.MAX_LEN for m in msgs)
    assert "추이" not in msgs[0]  # 31일 추이는 길어 줄여진다
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
    assert code == 0 and len(n.sent) == 2


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
    code, out, _ = run(["--as-of", "2026-11-19"], f, now=NOW)
    assert code == 0
    assert "11/18 $3.00" in out and "11월 누적 $4.00" in out  # 11/23 이후 버킷은 기준일 이후라 제외
    assert f"end_time={int(kst_day(11, 19).timestamp())}" in f.calls[0][0]


def test_date_option_lines_and_missing():
    f = FakeFetch([(200, {"data": sample(), "has_more": False})])
    code, out, _ = run(["--date", "2026-11-23", "--date", "2026-11-18", "--date", "2026-11-20"], f)
    assert code == 0
    assert out.index("2026-11-18(수) $3.00") < out.index("2026-11-20(금) 집계 없음") < out.index("2026-11-23(월) $0.75")
    assert f"start_time={int(kst_day(11, 18).timestamp())}" in f.calls[0][0]


def test_week_of_monday_to_sunday():
    f = FakeFetch([(200, {"data": sample(), "has_more": False})])
    code, out, _ = run(["--week-of", "2026-11-18"], f)  # 수요일 -> 11/16(월)~11/22(일)
    assert code == 0 and "주간 11/16~11/22 합계 $3.00" in out and "수3.00" in out and "진행 중" not in out
    assert f"start_time={int(kst_day(11, 16).timestamp())}" in f.calls[0][0]
    f = FakeFetch([(200, {"data": sample(), "has_more": False})])
    _, out, _ = run(["--week-of", "2026-11-24"], f)  # 11/23(월)~11/29(일): 오늘 포함 주
    assert "주간 11/23~11/29 합계 $0.75 진행 중 주 포함" in out


def test_custom_messages_split_over_limit():
    dates = [datetime(2026, 11, 1).date() + timedelta(days=i) for i in range(20)]
    msgs = rep.build_custom_messages([], dates, [], NOW.date())
    assert len(msgs) >= 2 and all(len(m) <= rep.MAX_LEN and m.startswith(rep.PREFIX) for m in msgs)


def test_bad_date_format_exit_2():
    code, _, _ = run(["--date", "11-23"], FakeFetch([]))
    assert code == 2
