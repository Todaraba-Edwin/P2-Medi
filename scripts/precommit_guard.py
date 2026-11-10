#!/usr/bin/env python3
"""pre-commit 가드(BE-15, RFP-29-01 A, H14). 커밋하려는 파일 경로·내용을 검사해 막는다.

막는 것: `.env`·`.env.*`(`.env.example` 제외), 로컬 전용 폴더(data/, P2-doc/report/, tickets/issues/, logs/) 아래 파일,
비밀 패턴(`sk-…`, `serviceKey=값`, `postgres://사용자:비번@…`, JWT)이 든 텍스트, 5MB 넘는 파일.
사용: pre-commit이 스테이징된 파일 경로를 인자로 넘긴다. 값은 출력하지 않고 경로·사유만 낸다.
"""

import re
import sys
from pathlib import Path

LOCAL_ONLY_PREFIXES = ("data/", "P2-doc/report/", "tickets/issues/", "logs/")
MAX_BYTES = 5 * 1024 * 1024
PATTERNS = {
    "OpenAI형 키(sk-)": re.compile(rb"sk-[A-Za-z0-9_\-]{20,}"),
    "serviceKey 값": re.compile(rb"(?i)servicekey=[A-Za-z0-9%+/=_\-]{12,}"),
    "DB 연결 문자열": re.compile(
        # 비밀번호 자리가 자리표시([…]·<…>·{…}·${…}·$VAR·***·password·비밀번호·xxx·your…)이면 통과, 실제 값 모양이면 차단
        rb"(?i)postgres(?:ql)?://[^\s:@/]+:(?![\[<{$*]|x{3,}|your|password|\xeb\xb9\x84\xeb\xb0\x80\xeb\xb2\x88\xed\x98\xb8)[^\s@]+@"
    ),
    "JWT": re.compile(rb"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
}
SELF = "scripts/precommit_guard.py"


def check(path_str: str, root: Path) -> list[str]:
    rel = path_str.replace("\\", "/")
    problems = []
    name = rel.rsplit("/", 1)[-1]
    if (name == ".env" or name.startswith(".env.")) and name != ".env.example":
        problems.append("환경 파일(.env)은 커밋하지 않는다")
    if rel.startswith(LOCAL_ONLY_PREFIXES):
        problems.append("로컬 전용 폴더(data/·P2-doc/report/·tickets/issues/·logs/)는 커밋하지 않는다")
    path = root / rel
    if path.is_file():
        if path.stat().st_size > MAX_BYTES:
            problems.append("5MB를 넘는 파일은 커밋하지 않는다")
        elif rel != SELF and not rel.startswith("backend/tests/"):  # 시험은 가짜 비밀 문자열을 쓴다
            data = path.read_bytes()
            for label, pat in PATTERNS.items():
                if pat.search(data):
                    problems.append(f"비밀 패턴 감지: {label}")
    return problems


def main(argv: list[str]) -> int:
    root = Path.cwd()
    failed = False
    for arg in argv:
        for problem in check(arg, root):
            print(f"BLOCK {arg}: {problem}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
