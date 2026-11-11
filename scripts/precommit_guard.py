#!/usr/bin/env python3
"""pre-commit 가드(BE-15, RFP-29-01 A, H14). 커밋하려는 파일 경로·내용을 검사해 막는다.

막는 것: `.env`·`.env.*`(`.env.example` 제외), 로컬 전용 폴더(data/, P2-doc/report/, tickets/issues/, logs/) 아래 파일,
봉인 시험셋(`*.SEALED.jsonl`, RFP-26-04, S-09), 비밀 패턴(`sk-…`, `serviceKey=값`, `postgres://사용자:비번@…`, JWT,
Supabase `sb_secret_`·`sb_publishable_`, Upstage `up_`, `Bearer` 토큰, libpq `password=`, Supabase 프로젝트 ref)이 든 텍스트,
5MB 넘는 파일.
`backend/tests/`는 파일 전체가 아니라 **줄 단위**로만 예외를 둔다(S-08, 2026-11-11): 줄에 `# guard: fake`가 있거나,
걸린 값이 알려진 가짜 형태(`QQQQ`·`FAKE`·`fake`·`test`·`NOT-A-REAL`·`SECRET`·`DUMMY`가 든 값, 비밀번호 8자 이하의 DB 문자열)일 때만 통과한다.
사용: pre-commit이 스테이징된 파일 경로를 인자로 넘긴다. 값은 출력하지 않고 경로·사유·줄 번호만 낸다.
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
    # S-02(2026-11-11): 마스킹(app/logging/masking.py)과 같은 형식
    "Supabase 키(sb_secret_·sb_publishable_)": re.compile(rb"\bsb_(?:secret|publishable)_[A-Za-z0-9_\-]{16,}"),
    "Upstage 키(up_)": re.compile(rb"\bup_[A-Za-z0-9]{20,}"),
    "Bearer 토큰": re.compile(rb"(?i)\bBearer\s+[A-Za-z0-9._~+/=\-]{16,}"),
    "libpq password=": re.compile(
        # libpq key=value 문자열(같은 줄에 host=·user=·dbname=·port=·sslmode= 중 하나)의 password 값. 자리표시는 통과
        rb"(?i)\b(?:host|user|dbname|port|sslmode)=\S*[^\n]*?\bpassword=(?![\[<{$*'\"]|x{3,}|your|password)[^\s'\"&;]{4,}"
        rb"|\bpassword=(?![\[<{$*'\"]|x{3,}|your|password)[^\s'\"&;]{4,}[^\n]*?\b(?:host|user|dbname|port|sslmode)="
    ),
    "Supabase 프로젝트 ref": re.compile(rb"\bpostgres\.[a-z0-9]{20}\b|\b[a-z0-9]{20}\.supabase\.(?:co|com|in)\b"),
}
# backend/tests/ 줄 단위 예외(S-08). 실제 키는 무작위라 아래 표지를 담을 가능성이 낮다.
TESTS_PREFIX = "backend/tests/"
FAKE_LINE_MARK = b"# guard: fake"
FAKE_MARKERS = (b"QQQQ", b"FAKE", b"fake", b"test", b"NOT-A-REAL", b"SECRET", b"DUMMY", b"dummy")
_DB_PW = re.compile(rb"://[^\s:@/]+:([^\s@]*)@")
SEALED_SUFFIX = ".SEALED.jsonl"
SELF = "scripts/precommit_guard.py"

# 설정 객체·환경 전체를 통째로 출력하는 코드(sec-guard). 앱·스크립트 소스(.py)에만 적용한다. 문서(.md)·시험·redact 모듈은 제외.
OUTPUT_SCOPE = ("backend/app/", "backend/scripts/", "scripts/")
OUTPUT_ALLOW = frozenset({SELF, "backend/app/security/redact.py"})
OUTPUT_PATTERNS = {
    "설정 객체 출력(print(settings…))": re.compile(rb"\bprint\(\s*f?[\"']?[^\n)]*?(?<![\w.])(?:settings|get_settings\(\))\s*[,)}]"),
    "settings repr": re.compile(rb"\brepr\(\s*(?:self\.)?(?:settings|get_settings\(\))"),
    "os.environ 전체 출력": re.compile(rb"\bprint\(\s*(?:dict\(\s*)?os\.environ\s*\)"),
    "f-string에 os.environ·settings 전체": re.compile(rb"\bprint\(f[\"'][^\n]*\{\s*(?:os\.environ|settings|get_settings\(\))\s*[}!:]"),
    "model_dump 출력·로그": re.compile(rb"\b(?:print|log\w*\.\w+|logging\.\w+)\([^\n]*\.model_dump\("),
    "redact 없는 트레이스백 출력": re.compile(rb"(?<![\w.])traceback\.print_exc\(|\btraceback\.print_exception\("),
}


def is_known_fake(line: bytes, matched: bytes) -> bool:
    """시험 파일 한 줄의 걸린 값이 알려진 가짜인가(S-08)."""
    if FAKE_LINE_MARK in line:
        return True
    if any(m in matched for m in FAKE_MARKERS):
        return True
    pw = _DB_PW.search(matched)
    return bool(pw) and len(pw.group(1)) <= 8  # 시험의 u:pw@·u:p@ 같은 짧은 자리표시(실제 DB 비밀번호는 길다)


def secret_problems(data: bytes, *, tests: bool = False) -> list[str]:
    """비밀 패턴 검사. tests=True면 줄마다 보고 알려진 가짜만 통과시킨다(줄 번호만 알리고 값은 내지 않는다)."""
    problems = []
    for label, pat in PATTERNS.items():
        if not tests:
            if pat.search(data):
                problems.append(f"비밀 패턴 감지: {label}")
            continue
        bad = [i for i, line in enumerate(data.splitlines(), 1)
               for m in pat.finditer(line) if not is_known_fake(line, m.group(0))]
        if bad:
            where = ",".join(str(i) for i in sorted(set(bad))[:5])
            problems.append(f"비밀 패턴 감지: {label} (줄 {where}; 가짜면 줄에 '# guard: fake' 또는 QQQQ 형태)")
    return problems


def check(path_str: str, root: Path) -> list[str]:
    rel = path_str.replace("\\", "/")
    problems = []
    name = rel.rsplit("/", 1)[-1]
    if (name == ".env" or name.startswith(".env.")) and name != ".env.example":
        problems.append("환경 파일(.env)은 커밋하지 않는다")
    if rel.startswith(LOCAL_ONLY_PREFIXES):
        problems.append("로컬 전용 폴더(data/·P2-doc/report/·tickets/issues/·logs/)는 커밋하지 않는다")
    if name.endswith(SEALED_SUFFIX):
        problems.append("봉인 시험셋(*.SEALED.jsonl)은 커밋하지 않는다(RFP-26-04, manifest의 sha256만 커밋)")
    path = root / rel
    if path.is_file():
        if path.stat().st_size > MAX_BYTES:
            problems.append("5MB를 넘는 파일은 커밋하지 않는다")
        elif rel != SELF:
            data = path.read_bytes()
            problems += secret_problems(data, tests=rel.startswith(TESTS_PREFIX))
            if rel.endswith(".py") and rel.startswith(OUTPUT_SCOPE) and rel not in OUTPUT_ALLOW:
                for label, pat in OUTPUT_PATTERNS.items():
                    if pat.search(data):
                        problems.append(f"설정·환경 통째 출력 패턴: {label}")
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
