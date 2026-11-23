"""HTTP 요청 소요 시간 로그(BE-11 §3 "요청 소요 시간 로그", 환경변수 `MEDIAGENT_REQUEST_TIMING`, 기본 켬).

요청마다 `req METHOD 경로템플릿 상태코드 소요ms` 한 줄만 `app.request_timing` 로거에 남긴다. 느린 요청(>= 1000ms)은 WARNING `slow req`.
남기지 않는 것: 쿼리 문자열, 본문, 헤더, 토큰, 사용자 식별, 질문·검색어, 클라이언트 IP. 경로는 라우트 템플릿(`/profiles/{profile_id}`)만 쓰고,
라우트를 못 찾은 요청(404)은 숫자·UUID 같은 구간을 `{id}`로 가린 앞 3구간만 쓴다. uvicorn 접근 로그(꺼 둔 상태, PRD-17 ⑧ B)와 별개다.
순수 ASGI 미들웨어라 `/chat` 스트림을 버퍼링하지 않는다(소요는 응답이 끝날 때까지).
"""

from __future__ import annotations

import logging
import re
import time

logger = logging.getLogger("app.request_timing")
SLOW_MS = 1000.0
_ID_LIKE = re.compile(r"^(\d+|[0-9a-fA-F-]{16,})$")


def path_label(scope: dict) -> str:
    route = scope.get("route")
    template = getattr(route, "path", None)
    if isinstance(template, str) and template:
        return template
    segs = [s for s in str(scope.get("path", "")).split("/") if s][:3]
    return "/" + "/".join("{id}" if _ID_LIKE.match(s) else s for s in segs)


class RequestTimingMiddleware:
    def __init__(self, app, enabled: bool = True) -> None:
        self.app = app
        self.enabled = enabled

    async def __call__(self, scope, receive, send):
        if not self.enabled or scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        status = 0

        async def _send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            ms = (time.perf_counter() - start) * 1000.0
            line = f"{scope.get('method', '-')} {path_label(scope)} {status or 500} {ms:.0f}ms"
            if ms >= SLOW_MS:
                logger.warning("slow req %s", line)
            else:
                logger.info("req %s", line)
