"""BE-06 OpenAPI 스키마 내보내기(FE-01-11 A): 서버를 띄우지 않고 `app.openapi()`를 JSON으로 쓴다.

프런트 `openapi-typescript`의 입력이다. 결과 파일은 생성물이라 저장소에 넣지 않는다.

    cd backend && .venv/bin/python scripts/export_openapi.py              # 표준 출력
    cd backend && .venv/bin/python scripts/export_openapi.py -o /tmp/openapi.json

네트워크·DB·LLM 호출이 없다(앱 객체만 만든다). 비밀값은 스키마에 들어가지 않는다(설정 값은 스키마 대상이 아니다).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.main import app  # noqa: E402


def render() -> str:
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="FastAPI OpenAPI 스키마를 JSON으로 쓴다(서버 기동 없음)")
    ap.add_argument("-o", "--out", type=Path, default=None, help="출력 파일 경로(없으면 표준 출력)")
    args = ap.parse_args(argv)
    text = render()
    if args.out is None:
        sys.stdout.write(text)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
