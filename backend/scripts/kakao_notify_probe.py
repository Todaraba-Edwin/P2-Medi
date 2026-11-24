"""카카오톡 "나에게 보내기" 실제 전송 점검(운영자용). `--yes` 없이는 아무것도 보내지 않는다.

실행(backend/에서): `python scripts/kakao_notify_probe.py --yes`
키 값은 환경변수 이름(`KAKAO_REST_API_KEY`·`KAKAO_REFRESH_TOKEN`·선택 `KAKAO_CLIENT_SECRET`)으로만 읽고 출력하지 않는다.
`.env`는 `Settings`가 읽는다(이 스크립트는 파일을 열지 않는다). 결과는 성공/실패와 예외 종류 이름만 출력한다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.kakao_notify import KakaoNotifier  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.security.redact import install_excepthook  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--yes", action="store_true", help="실제로 카카오 API를 호출한다(없으면 설정 상태만 출력)")
    args = ap.parse_args()
    install_excepthook()  # S-05
    settings = get_settings()
    notifier = KakaoNotifier.from_settings(settings)
    if notifier is None:
        print("비활성: KAKAO_REST_API_KEY·KAKAO_REFRESH_TOKEN이 비었거나 MEDIAGENT_NOTIFY가 꺼짐")
        return 2
    if not args.yes:
        print("설정 확인됨(키 이름 기준). 실제 전송하려면 --yes")
        return 0
    try:
        notifier.send_now("[MediAgent-Can-I-PPiyak] 알림 시험 메시지")
    except Exception as exc:  # noqa: BLE001
        print(f"전송 실패: {type(exc).__name__}")
        return 1
    print("전송 성공")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
