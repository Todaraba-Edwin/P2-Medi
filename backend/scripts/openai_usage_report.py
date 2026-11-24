"""OpenAI 사용 비용 일일 보고(DevOps, 2026-11-24). 독립 운영 스크립트이며 서비스 경로(`app/`)가 읽지 않는다.

실행(backend/에서): `.venv/bin/python scripts/openai_usage_report.py [--dry-run | --send] [--days N] [--notify-failure]`
- 기본은 `--dry-run`: 메시지를 화면에 출력만 한다(카카오 호출 0).
- `--send`: 카카오톡 "나에게 보내기"로 보낸다(`KakaoNotifier.send_now` 재사용). 카카오 설정이 없으면 보내지 않고 종료코드 2.
- 원천: OpenAI 관리자 키(`OPENAI_ADMIN_KEY`, `Settings`)의 Costs API `GET /v1/organization/costs`(`bucket_width=1d`, `group_by=line_item`).
  키 값은 출력·로그에 남기지 않는다(예외는 종류 이름만).
- 날짜 경계는 Asia/Seoul. 일 버킷은 시작 시각(`start_time`)의 서울 날짜로 귀속하고, 아직 끝나지 않은 버킷(오늘 진행분)은 제외한다.
  (OpenAI 일 버킷이 UTC 기준일인지는 문서에 명시가 없어 확인하지 못했다. 그래도 귀속 규칙은 위 한 가지로 고정한다.)
- 잔여 크레딧: 공개 API를 확인하지 못해 메시지에 넣지 않는다.
추가 인자: `--as-of YYYY-MM-DD`(기준일), `--date YYYY-MM-DD`(반복 가능, 일별 한 줄), `--week-of YYYY-MM-DD`(월~일 주간 합계).
종료코드: 0 성공, 2 설정 없음(관리자 키 또는 카카오), 3 API 오류, 4 카카오 전송 실패.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.kakao_notify import KakaoNotifier  # noqa: E402
from app.config import REPO_ROOT, get_settings, reveal  # noqa: E402
from app.security.redact import install_excepthook  # noqa: E402

COSTS_URL = "https://api.openai.com/v1/organization/costs"
KST = ZoneInfo("Asia/Seoul")
PREFIX = "[MediAgent-Can-I-PPiyak]"
MAX_LEN = 200  # 카카오 텍스트 템플릿 길이(KakaoNotifier.send_now도 200자로 자른다)
TIMEOUT_SECONDS = 15.0
RETRIES = 1
TOP_N = 3
LOG_FILE = REPO_ROOT / "logs" / "openai_usage_report.log"

# 요청 함수: (url, headers) -> (HTTP 상태, JSON dict). 시험은 가짜로 주입한다.
FetchFn = Callable[[str, dict[str, str]], tuple[int, dict[str, Any]]]


class ReportError(Exception):
    """보고 실패. `kind`는 원인 종류 이름만(값·응답 본문 없음)."""

    def __init__(self, kind: str, exit_code: int = 3) -> None:
        super().__init__(kind)
        self.kind = kind
        self.exit_code = exit_code


def _http_get(url: str, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310 - 고정 https URL
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:  # 상태만 돌려준다(본문은 읽지 않는다)
        return exc.code, {}


@dataclass(frozen=True)
class Bucket:
    day: date  # 시작 시각의 서울 날짜
    total: float
    items: dict[str, float]  # line_item -> USD


def build_url(start: datetime, end: datetime) -> str:
    query = [("start_time", int(start.timestamp())), ("end_time", int(end.timestamp())), ("bucket_width", "1d"),
             ("group_by", "line_item"), ("limit", 180)]
    return f"{COSTS_URL}?{urllib.parse.urlencode(query)}"


def fetch_buckets(admin_key: str, start: datetime, end: datetime, *, fetch: FetchFn | None = None) -> list[dict[str, Any]]:
    """Costs API를 `next_page`가 없을 때까지 읽는다. 실패는 ReportError(kind)로만 나간다."""
    fetch = fetch or _http_get
    headers = {"Authorization": f"Bearer {admin_key}", "Accept": "application/json"}
    base = build_url(start, end)
    pages: list[dict[str, Any]] = []
    page: str | None = None
    for _ in range(20):  # 무한 루프 방지
        url = base if page is None else f"{base}&{urllib.parse.urlencode({'page': page})}"
        body = _get_with_retry(fetch, url, headers)
        pages.extend(b for b in body.get("data", []) if isinstance(b, dict))
        page = body.get("next_page") if body.get("has_more") else None
        if not page:
            return pages
    raise ReportError("pagination_overflow")


def _get_with_retry(fetch: FetchFn, url: str, headers: dict[str, str]) -> dict[str, Any]:
    kind = "unknown"
    for _ in range(RETRIES + 1):
        try:
            status, body = fetch(url, headers)
        except TimeoutError:
            kind = "timeout"
            continue
        except urllib.error.URLError as exc:
            kind = "timeout" if isinstance(exc.reason, TimeoutError) else "network_error"
            continue
        except (OSError, ValueError) as exc:
            kind = type(exc).__name__
            continue
        if status == 200:
            if not isinstance(body, dict):
                raise ReportError("bad_response")
            return body
        kind = f"http_{status}"
        if status < 500 and status != 429:
            break  # 4xx(429 제외)는 재시도해도 같다
    raise ReportError(kind)


def parse_buckets(raw: list[dict[str, Any]], now: datetime) -> list[Bucket]:
    """일 버킷을 서울 날짜로 귀속하고, 끝나지 않은 버킷은 뺀다. 같은 날짜가 둘이면 합친다."""
    days: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    seen: set[date] = set()
    for b in raw:
        try:
            start = datetime.fromtimestamp(int(b["start_time"]), KST)
            end_ts = int(b.get("end_time") or 0)
        except (KeyError, TypeError, ValueError):
            raise ReportError("bad_response") from None
        if end_ts and end_ts > now.timestamp():
            continue  # 진행 중인 버킷
        d = start.date()
        seen.add(d)
        for r in b.get("results", []) or []:
            amount = (r.get("amount") or {}) if isinstance(r, dict) else {}
            if str(amount.get("currency", "usd")).lower() != "usd":
                raise ReportError("unexpected_currency")
            try:
                value = float(amount.get("value") or 0)
            except (TypeError, ValueError):
                raise ReportError("bad_response") from None
            days[d][str(r.get("line_item") or "(기타)")] += value
    return [Bucket(d, sum(days[d].values()), dict(days[d])) for d in sorted(seen)]


def fmt_usd(v: float) -> str:
    return f"${v:,.2f}"  # 사용자 지정 양식: 항상 소수 둘째 자리(0.005 미만은 $0.00)


def _short_item(name: str, limit: int = 26) -> str:
    return name if len(name) <= limit else name[: limit - 1] + "…"


DAY_ABBR = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _week_block(by_day: dict[date, Bucket], monday: date, last: date) -> list[str]:
    """한 ISO 주의 보고 줄들(접두 제외): `YYYY`, `ISO 현재/전체(월~일) Total $X`, 월요일부터 `last`까지 `DDD(MM/DD) $X`."""
    iso_year, iso_week, _ = monday.isocalendar()
    sunday = monday + timedelta(days=6)
    total_weeks = date(iso_year, 12, 28).isocalendar().week  # 12/28은 항상 그 해의 마지막 ISO 주에 속한다
    span = [monday + timedelta(days=i) for i in range((last - monday).days + 1)]
    week_total = sum(by_day[d].total for d in span if d in by_day)
    lines = [f"{iso_year}", f"ISO {iso_week}/{total_weeks}({monday:%m/%d}~{sunday:%m/%d}) Total {fmt_usd(week_total)}"]
    for d in span:
        lines.append(f"{DAY_ABBR[d.weekday()]}({d:%m/%d}) {fmt_usd(by_day[d].total) if d in by_day else '$0.00'}")
    return lines


def build_messages(buckets: list[Bucket], today: date, days: int = 7) -> list[str]:
    """일일 보고(사용자 지정 형식, 2026-11-24). 어제가 속한 ISO 주의 월요일부터 어제까지 일별 비용과 그 합계를 한 건으로 보낸다.

    ```
    [접두]
    YYYY
    ISO current/total(MM/DD~MM/DD) Total $0.00
    DDD(MM/DD) $0.00
    ```
    ISO 8601 주 기준(월요일 시작, 첫 목요일이 든 주가 1주)이다. `total`은 그 해의 ISO 총 주 수(52 또는 53), 괄호는 그 주의 월~일이다.
    어제가 월요일이면 그 주는 어제 하루만 담는다. `days`는 옛 인자(호환용)라 쓰지 않는다."""
    yday = today - timedelta(days=1)
    monday = yday - timedelta(days=yday.weekday())
    lines = [PREFIX] + _week_block({b.day: b for b in buckets}, monday, yday)
    text = "\n".join(lines)
    return [text if len(text) <= MAX_LEN else text[: MAX_LEN - 1] + "…"]


def _parse_date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError("YYYY-MM-DD 형식이어야 한다") from None


WEEKDAYS = "월화수목금토일"


def build_custom_messages(buckets: list[Bucket], dates: list[date], week_days: list[date], today: date) -> list[str]:
    """`--date`(일자별 한 줄)·`--week-of`(그 주 보고)용 메시지. 일일 보고와 같은 양식이고 200자를 넘으면 여러 건으로 나눈다."""
    by_day = {b.day: b for b in buckets}
    lines: list[str] = []
    for d in sorted(set(dates)):
        lines.append(f"{DAY_ABBR[d.weekday()]}({d:%Y/%m/%d}) {fmt_usd(by_day[d].total) if d in by_day else '집계 없음'}")
    if week_days:
        last = min(week_days[-1], today - timedelta(days=1))  # 진행 중인 주는 어제까지만
        lines.extend(_week_block(by_day, week_days[0], last))
    return _split(lines)


def _split(lines: list[str]) -> list[str]:
    """줄을 접두와 함께 200자 이하 메시지들로 나눈다(줄 하나가 길면 자른다)."""
    msgs: list[str] = []
    cur = PREFIX
    for line in lines:
        line = line[: MAX_LEN - len(PREFIX) - 2]
        if len(cur) + 1 + len(line) > MAX_LEN:
            msgs.append(cur)
            cur = PREFIX
        cur += "\n" + line
    msgs.append(cur)
    return msgs


def _pack(lines: list[str]) -> str:
    text = "\n".join(lines)
    if len(text) > MAX_LEN and len(lines) > 3:  # 길면 추이 줄(셋째)을 먼저 뺀다
        text = "\n".join(lines[:2] + lines[3:])
    return text if len(text) <= MAX_LEN else text[: MAX_LEN - 1] + "…"


def _log(path: Path | None, line: str) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now(KST):%Y-%m-%d %H:%M:%S} {line}\n")
    except OSError:
        pass


def run(argv: list[str] | None = None, *, settings: Any = None, fetch: FetchFn | None = None, notifier: KakaoNotifier | None = None,
        now: datetime | None = None, log_path: Path | None = LOG_FILE, out: Any = None, err: Any = None) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="화면에 출력만(기본)")
    mode.add_argument("--send", action="store_true", help="카카오톡으로 전송")
    ap.add_argument("--days", type=int, default=7, help="최근 N일 합계·추이(기본 7, 1~31)")
    ap.add_argument("--notify-failure", action="store_true", help="실패하면 '보고 실패(원인 종류)' 한 줄을 카카오로 알린다")
    ap.add_argument("--as-of", type=_parse_date, default=None, metavar="YYYY-MM-DD", help="기준일(기본 오늘, 서울). 전날·최근 N일·월 누적의 기준")
    ap.add_argument("--date", type=_parse_date, action="append", default=[], metavar="YYYY-MM-DD", help="그 날짜의 일별 비용만 보고(여러 번 가능)")
    ap.add_argument("--week-of", type=_parse_date, default=None, metavar="YYYY-MM-DD", help="그 날짜가 속한 주(월~일)의 합계")
    try:
        args = ap.parse_args(argv)
    except SystemExit:
        return 2
    if not 1 <= args.days <= 31:
        print("--days는 1~31", file=err)
        return 2
    settings = settings if settings is not None else get_settings()
    now = now or datetime.now(KST)
    if notifier is None and (args.send or args.notify_failure):
        notifier = KakaoNotifier.from_settings(settings)

    def fail(kind: str, code: int) -> int:
        print(f"보고 실패: {kind}", file=err)
        _log(log_path, f"fail kind={kind}")
        if args.notify_failure and notifier is not None and kind != "kakao_send_failed":
            with contextlib.suppress(Exception):  # 알림 실패는 삼킨다
                notifier.send_now(f"{PREFIX} OpenAI 비용 보고 실패({kind})")
        return code

    admin_key = reveal(getattr(settings, "openai_admin_key", None))
    if not admin_key:
        return fail("admin_key_missing", 2)
    if args.send and notifier is None:
        return fail("kakao_not_configured", 2)

    now_kst = now.astimezone(KST)
    today = args.as_of or now_kst.date()
    if args.as_of:  # 과거 재현: 기준일 정오에 돌린 것처럼 본다(그 뒤 버킷은 아직 없는 것으로 취급)
        now_kst = datetime(today.year, today.month, today.day, 12, tzinfo=KST)
    midnight = datetime(today.year, today.month, today.day, tzinfo=KST)
    custom = bool(args.date or args.week_of)
    week_days: list[date] = []
    if custom:
        needed = list(args.date)
        if args.week_of:
            monday = args.week_of - timedelta(days=args.week_of.weekday())
            week_days = [monday + timedelta(days=i) for i in range(7)]
            needed += week_days
        first, last = min(needed), max(needed) + timedelta(days=1)
        window_start = datetime(first.year, first.month, first.day, tzinfo=KST)
        window_end = max(midnight, datetime(last.year, last.month, last.day, tzinfo=KST))
    else:
        y = today - timedelta(days=1)
        wk = y - timedelta(days=y.weekday())
        window_start = datetime(wk.year, wk.month, wk.day, tzinfo=KST)
        window_end = midnight
    try:
        buckets = parse_buckets(fetch_buckets(admin_key, window_start, window_end, fetch=fetch), now_kst)
    except ReportError as exc:
        return fail(exc.kind, exc.exit_code)
    if custom:
        messages = build_custom_messages(buckets, args.date, week_days, today)
    else:
        messages = build_messages(buckets, today, args.days)
    if not args.send:
        for m in messages:
            print(m, file=out)
            print("---", file=out)
        _log(log_path, f"ok mode=dry-run messages={len(messages)}")
        return 0
    try:
        for m in messages:
            notifier.send_now(m)  # type: ignore[union-attr]
    except Exception as exc:  # noqa: BLE001 - 종류 이름만
        print(f"보고 실패: kakao_send_failed({type(exc).__name__})", file=err)
        _log(log_path, f"fail kind=kakao_send_failed exc={type(exc).__name__}")
        return 4
    _log(log_path, f"ok mode=send messages={len(messages)}")
    print(f"전송 완료({len(messages)}건)", file=out)
    return 0


def main() -> int:
    install_excepthook()
    return run()


if __name__ == "__main__":
    sys.exit(main())
