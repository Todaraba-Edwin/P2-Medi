"""운영자 전용 카카오톡 "나에게 보내기" 알림(DevOps, 2026-11-24). 서버 준비(warmup) 단계 완료를 알린다.

- best-effort: 별도 데몬 스레드에서 보내고(타임아웃 3초) **모든 예외를 삼킨다**. 서버 기동·`/health`·요청을 막거나 실패시키지 않는다.
  실패는 경고 로그 한 줄에 예외 **종류 이름**만 남긴다(토큰·응답 본문·URL 쿼리는 남기지 않는다).
- 스위치: `KAKAO_REST_API_KEY`·`KAKAO_REFRESH_TOKEN`이 모두 있고 `MEDIAGENT_NOTIFY`가 꺼짐(0·false·off)이 아닐 때만 켠다. 아니면 `from_settings`가 None.
- 흐름: refresh token → access token(`kauth.kakao.com/oauth/token`) → 메모 API(`kapi.kakao.com/v2/api/talk/memo/default/send`, 텍스트 템플릿).
  응답에 새 refresh token이 오면(남은 유효기간 1개월 미만일 때만 옴) 로컬 파일(`data/mock/kakao_refresh_token.local`, `data/`는 .gitignore)에 저장한다.
- 메시지는 단계 이름·초·개수만 담는다(사용자·질문·약명·IP 없음).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import REPO_ROOT, reveal

logger = logging.getLogger(__name__)

TOKEN_ENDPOINT = "https://kauth.kakao.com/oauth/token"  # noqa: S105 - 공개 URL
MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
TIMEOUT_SECONDS = 3.0
TOKEN_FILE = REPO_ROOT / "data" / "mock" / "kakao_refresh_token.local"
_LINK = "https://developers.kakao.com"  # 텍스트 템플릿의 link 칸용 자리값(알림 클릭 대상 없음)

# 전송 함수: (url, headers, form) -> (HTTP 상태, JSON 본문 dict). 시험은 가짜로 주입한다.
SendFn = Callable[[str, dict[str, str], dict[str, str]], tuple[int, dict[str, Any]]]


def _post_form(url: str, headers: dict[str, str], form: dict[str, str]) -> tuple[int, dict[str, Any]]:
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(url, data=data, method="POST",  # noqa: S310 - 고정 https URL
                                 headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8", **headers})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310 - 고정 https URL
        return resp.status, json.loads(resp.read() or b"{}")


def notify_enabled(settings: Any) -> bool:
    return getattr(settings, "mediagent_notify", True) is True


class KakaoNotifier:
    def __init__(self, rest_api_key: str, refresh_token: str, client_secret: str | None = None, *,
                 send: SendFn | None = None, token_file: Path | None = None) -> None:
        self._key = rest_api_key
        self._secret = client_secret
        self._send = send or _post_form
        self._token_file = token_file
        self._refresh = refresh_token
        self._lock = threading.Lock()
        self.threads: list[threading.Thread] = []

    @classmethod
    def from_settings(cls, settings: Any, *, send: SendFn | None = None,
                      token_file: Path | None = TOKEN_FILE) -> KakaoNotifier | None:
        if not notify_enabled(settings):
            return None
        key = reveal(getattr(settings, "kakao_rest_api_key", None))
        refresh = reveal(getattr(settings, "kakao_refresh_token", None))
        if not key or not refresh:
            return None
        saved = _read_saved(token_file)
        return cls(key, saved or refresh, reveal(getattr(settings, "kakao_client_secret", None)), send=send, token_file=token_file)

    def notify(self, text: str) -> threading.Thread:
        """백그라운드로 보내고 바로 돌아온다. 예외는 밖으로 나가지 않는다."""
        thread = threading.Thread(target=self._safe_send, args=(text,), daemon=True, name="kakao-notify")
        self.threads.append(thread)
        thread.start()
        return thread

    def _safe_send(self, text: str) -> None:
        try:
            self.send_now(text)
        except Exception as exc:  # noqa: BLE001 - best-effort. 종류 이름만 남긴다
            logger.warning("kakao notify failed: %s", type(exc).__name__)

    def send_now(self, text: str) -> None:
        """동기 전송(프로브 스크립트·시험용). 실패하면 예외(메시지에 값 없음)."""
        with self._lock:
            access = self._access_token()
        template = json.dumps({"object_type": "text", "text": text[:200], "link": {"web_url": _LINK, "mobile_web_url": _LINK}},
                              ensure_ascii=False)
        status, body = self._send(MEMO_URL, {"Authorization": f"Bearer {access}"}, {"template_object": template})
        if status != 200 or body.get("result_code") != 0:
            raise RuntimeError(f"memo send rejected (HTTP {status})")

    def _access_token(self) -> str:
        form = {"grant_type": "refresh_token", "client_id": self._key, "refresh_token": self._refresh}
        if self._secret:
            form["client_secret"] = self._secret
        status, body = self._send(TOKEN_ENDPOINT, {}, form)
        token = body.get("access_token")
        if status != 200 or not isinstance(token, str) or not token:
            raise RuntimeError(f"token refresh rejected (HTTP {status})")
        new_refresh = body.get("refresh_token")
        if isinstance(new_refresh, str) and new_refresh:
            self._refresh = new_refresh
            _save(self._token_file, new_refresh)
        return token


def _read_saved(path: Path | None) -> str | None:
    try:
        return (path.read_text().strip() or None) if path else None
    except OSError:
        return None


def _save(path: Path | None, token: str) -> None:
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(token)
    except OSError as exc:
        logger.warning("kakao refresh token save failed: %s", type(exc).__name__)


__all__ = ["MEMO_URL", "TOKEN_ENDPOINT", "KakaoNotifier", "notify_enabled"]
