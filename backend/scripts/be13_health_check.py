"""BE-13 배포 점검: 배포된 백엔드의 외부 응답을 확인한다(LLM·DB 호출 0, 비밀값 없음).

점검 3가지(모두 모델·DB를 부르지 않는 요청):
  1) `GET /health` → 200 `{"status": "ok"}`
  2) `GET /openapi.json` → 200, `ChatResponse`·`ChatEvent` 스키마가 들어 있다(프런트 타입 생성 입력, FE-01-11 A)
  3) `POST /chat` 빈 질문 → 422 `INVALID_REQUEST`(요청 검증이 그래프 앞에서 막는다: 모델·DB 호출 없음)
+ 주소가 `https://`가 아니면 경고(브라우저 → 백엔드 직접 호출은 HTTPS가 필요하다. Next rewrites 프록시면 서버 간 호출이라 http도 된다)

사용: `backend/.venv/bin/python backend/scripts/be13_health_check.py https://api.example.com [--timeout 10]`
종료 코드: 0 = 모두 통과, 1 = 실패 항목 있음, 2 = 주소 형식 오류. **실제 배포 주소 호출은 배포 뒤에만**(이 스크립트를 만든 2026-11-18에는 실행하지 않았다).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse

import httpx

SCHEMA_NAMES = ("ChatResponse", "ChatEvent")


def check(base: str, *, client: httpx.Client) -> list[dict[str, Any]]:
    """점검 결과 행 `{item, ok, detail}`. 응답 본문은 상태·키 이름만 본다(값을 출력하지 않는다)."""
    base = base.rstrip("/")
    rows: list[dict[str, Any]] = []

    def run(item: str, fn: Any) -> None:
        try:
            ok, detail = fn()
        except httpx.HTTPError as e:
            ok, detail = False, f"연결 실패: {type(e).__name__}"
        rows.append({"item": item, "ok": bool(ok), "detail": detail})

    def health() -> tuple[bool, str]:
        r = client.get(f"{base}/health")
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else None
        return r.status_code == 200 and body == {"status": "ok"}, f"HTTP {r.status_code}"

    def openapi() -> tuple[bool, str]:
        r = client.get(f"{base}/openapi.json")
        names = set(((r.json() or {}).get("components") or {}).get("schemas") or {}) if r.status_code == 200 else set()
        missing = [n for n in SCHEMA_NAMES if n not in names]
        return r.status_code == 200 and not missing, f"HTTP {r.status_code}" + (f", 빠진 스키마 {missing}" if missing else "")

    def invalid_chat() -> tuple[bool, str]:
        r = client.post(f"{base}/chat", json={"question": ""})
        code = (r.json() or {}).get("code") if r.status_code == 422 else None
        return r.status_code == 422 and code == "INVALID_REQUEST", f"HTTP {r.status_code}, code {code}"

    run("GET /health → 200 {status: ok}", health)
    run("GET /openapi.json → ChatResponse·ChatEvent 스키마", openapi)
    run("POST /chat 빈 질문 → 422 INVALID_REQUEST(모델·DB 호출 없음)", invalid_chat)
    return rows


def main(argv: Sequence[str] | None = None, *, transport: httpx.BaseTransport | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("base_url", help="배포된 백엔드 주소(예: https://api.example.com)")
    ap.add_argument("--timeout", type=float, default=10.0)
    a = ap.parse_args(argv)
    u = urlparse(a.base_url)
    if u.scheme not in ("http", "https") or not u.netloc:
        print("주소는 http(s)://호스트 형식이어야 한다")
        return 2
    if u.scheme != "https":
        print("경고: https가 아니다(브라우저 직접 호출이면 HTTPS 필요, Next rewrites 프록시면 서버 간 호출이라 허용)")
    with httpx.Client(timeout=a.timeout, transport=transport, follow_redirects=False) as client:
        rows = check(a.base_url, client=client)
    for r in rows:
        print(f"{'OK' if r['ok'] else 'NG'}  {r['item']}  ({r['detail']})")
    return 0 if all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
