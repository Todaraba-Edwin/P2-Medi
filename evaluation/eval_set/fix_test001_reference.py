"""AG-20-01 A(2026-11-18): 시험셋 test-001 `reference`에 섞인 내부 메모(`RFP-nn` 참조 표기)를 내용을 보지 않고 코드로 지운다.

    MEDIAGENT_ALLOW_SEALED=final-report-only backend/.venv/bin/python evaluation/eval_set/fix_test001_reference.py --set test --allow-sealed [--check]
    backend/.venv/bin/python evaluation/eval_set/fix_test001_reference.py --set PATH [--check]

- 이유: 2026-11-12 사용자 "삭제"(AG-11 §3 `:65`). AG-20-01 A로 **실행은 AG-14 최종 측정이 끝난 뒤**다(기준선 C2와 최종 C3을 같은 세트로 비교).
  `reference`는 Ragas Context Precision·Recall의 정답 근거라 내부 메모 글자는 빼야 한다. 문항 재생성은 하지 않는다(질문·정답·다른 칸 불변).
- 대상 행: 문항 ID가 `test-001`인 행 **하나**의 `reference` 문자열만. 그 행이 0개거나 2개 이상이면 아무것도 쓰지 않고 실패한다.
  다른 문항·다른 칸은 건드리지 않는다. 바꾼 행만 다시 직렬화하고 나머지 줄은 바이트 그대로 둔다. 다시 돌려도 바뀌는 행은 0(멱등).
- 제거 패턴(보수적, 정답 근거 문장 자체는 지우지 않는다. `REF` = `RFP-21`·`RFP-21-02`·`RFP-21 §4.6`·`RFP-21 §4.6 참조` 꼴):
  1) 메모만 든 괄호 `(REF)`·`(REF, REF)`·`(내부 메모: REF)`는 괄호째 지운다(앞 공백 포함).
  2) 다른 글자와 섞인 괄호 안에서는 `REF`와 붙은 구분 문구(`,`·`·`·`;`·`/`)만 지운다.
  3) 괄호 밖 맨 앞 `REF:`는 콜론까지, 그 밖의 `REF`는 앞 공백·구분 문구와 함께 지운다.
  제거 뒤 `reference`에 `RFP-`(대소문자 무시)가 남거나, `reference`가 비거나, 지운 글자가 `MAX_REMOVED`를 넘으면 쓰지 않고 실패한다.
- **시험셋(`*.SEALED.jsonl`)은 열람하지 않는다**(RFP-26-04): 가드(`sealed_guard`, 환경변수 + `--allow-sealed`)를 거쳐 읽고,
  문항 ID·내용은 출력·기록하지 않는다(실패 메시지에도 내용 없음). 출력은 행 수·남은 `RFP-` 수·sha256·백업 이름뿐이다.
- 백업은 `fix_multihop_m_path.backup`을 그대로 쓴다. manifest는 `file`이 같은 세트의 sha256·bytes를 다시 계산하고 변경 이력을 남긴다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (str(HERE), str(HERE.parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import sealed_guard as G
from fix_multihop_m_path import DEV, MANIFEST, FixError, backup

TEST = HERE / "test_set.SEALED.jsonl"  # build_eval_set.OUT["test"], README §1과 같은 이름(파일은 열지 않는다)
TARGET_ID = "test-001"
FIELD = "reference"
MAX_REMOVED = 120  # 메모 표기 몇 개 분량. 넘으면 패턴이 근거 문장까지 먹었다고 보고 멈춘다
DECISION = "AG-20-01 A"
CHANGE_DATE = "2026-11-18"
CHANGE_REASON = (f"{DECISION}({CHANGE_DATE}): 시험셋 {TARGET_ID} reference의 내부 메모(RFP- 참조 표기) 제거(2026-11-12 사용자 \"삭제\", "
                 "AG-14 최종 측정 뒤 적용). 질문·정답·다른 칸 불변, 문항 재생성 없음. 이전 l2-*·l3-* 결과와 섞지 않음")

# --- 메모 패턴 -------------------------------------------------------------------------------------------
_REF = r"RFP-\d+(?:-\d+)*(?:\s*§\s*\d+(?:\.\d+)*)?(?:\s*(?:참조|참고|기준|메모))?"
_SEP = r"[,，·;/]"
_OPEN, _CLOSE = r"[(（\[]", r"[)）\]]"
# 1) 메모만 든 괄호
_RE_PAREN_ONLY = re.compile(rf"\s*{_OPEN}\s*(?:내부\s*메모\s*[:：]?\s*)?{_REF}(?:\s*{_SEP}\s*{_REF})*\s*{_CLOSE}")
# 2) 섞인 괄호(괄호 안 글자에만 적용)
_RE_PAREN_ANY = re.compile(rf"{_OPEN}[^()（）\[\]]*{_CLOSE}")
_RE_IN_AFTER_SEP = re.compile(rf"\s*{_SEP}\s*{_REF}")
_RE_IN_BEFORE_SEP = re.compile(rf"{_REF}\s*{_SEP}\s*")
# 3) 괄호 밖
_RE_LEADING = re.compile(rf"^\s*{_REF}\s*[:：]\s*")
_RE_BARE = re.compile(rf"\s*(?:{_SEP}\s*)?{_REF}")
_RE_LEFTOVER = re.compile(r"RFP-", re.IGNORECASE)


def leftover(text: str) -> int:
    """`RFP-`가 남은 개수(대소문자 무시)."""
    return len(_RE_LEFTOVER.findall(text))


def _strip_in_paren(m: re.Match[str]) -> str:
    inner = m.group(0)
    inner = _RE_IN_AFTER_SEP.sub("", inner)
    return _RE_IN_BEFORE_SEP.sub("", inner)


def _strip_outside_paren(text: str) -> str:
    """괄호 밖 글자에만 3)을 적용한다. 패턴 밖 형식의 괄호 안 메모는 남겨 두어 `leftover` 검사로 실패하게 한다."""
    parts: list[str] = []
    pos = 0
    for m in _RE_PAREN_ANY.finditer(text):
        parts += [_RE_BARE.sub("", text[pos:m.start()]), m.group(0)]
        pos = m.end()
    parts.append(_RE_BARE.sub("", text[pos:]))
    return "".join(parts)


def strip_memo(text: str) -> str:
    """`text`에서 내부 메모 표기만 지운 문자열. 메모가 없으면 같은 문자열을 돌려준다."""
    out = _RE_PAREN_ONLY.sub("", text)
    out = _RE_PAREN_ANY.sub(_strip_in_paren, out)
    out = _RE_LEADING.sub("", out)
    return _strip_outside_paren(out)


def fix_row(row: dict) -> bool:
    """대상 행의 `reference`를 고친다. 바뀌었으면 True. 검사에 걸리면 내용 없는 메시지로 FixError."""
    ref = row.get(FIELD)
    if not isinstance(ref, str):
        raise FixError(f"대상 행의 {FIELD}가 문자열이 아니라 쓰지 않았다")
    new = strip_memo(ref)
    if leftover(new):
        raise FixError(f"제거 뒤에도 {FIELD}에 RFP- 표기가 {leftover(new)}개 남아 쓰지 않았다(패턴 밖 형식)")
    if not new.strip():
        raise FixError(f"제거 뒤 {FIELD}가 비어 쓰지 않았다")
    if len(ref) - len(new) > MAX_REMOVED:
        raise FixError(f"지운 글자 수가 상한 {MAX_REMOVED}를 넘어 쓰지 않았다")
    if new == ref:
        return False
    row[FIELD] = new
    return True


def fix_lines(raw: bytes) -> tuple[bytes, list[str], int]:
    """바꾼 바이트, 바꾼 행의 id 목록, 대상 행 `reference`에 남은 `RFP-` 수. 대상이 아닌 줄은 그대로 둔다."""
    lines = raw.decode("utf-8").splitlines(keepends=True)
    rows: list[dict | None] = []
    hits: list[int] = []
    for i, line in enumerate(lines):
        body = line.rstrip("\n")
        if not body.strip():
            rows.append(None)
            continue
        row = json.loads(body)
        rows.append(row)
        if row.get("id") == TARGET_ID:
            hits.append(i)
    if len(hits) != 1:
        raise FixError(f"대상 문항 ID 행이 {len(hits)}개라 쓰지 않았다(정확히 1개여야 한다)")
    i = hits[0]
    line, row = lines[i], rows[i]
    assert row is not None
    body = line.rstrip("\n")
    if json.dumps(row, ensure_ascii=False) != body:
        raise FixError("대상 행의 직렬화 형식이 예상과 달라 쓰지 않았다")
    changed: list[str] = []
    if fix_row(row):
        lines[i] = json.dumps(row, ensure_ascii=False) + line[len(body):]
        changed.append(TARGET_ID)
    return "".join(lines).encode("utf-8"), changed, leftover(row[FIELD])


def update_manifest(manifest: Path, file_name: str, data: bytes) -> str:
    """`fix_no_state_assessment.update_manifest`와 같은 동작(변경 이유 상수만 이 결정의 것)."""
    man = json.loads(manifest.read_text(encoding="utf-8"))
    key = next((k for k, v in (man.get("sets") or {}).items() if v.get("file") == file_name), None)
    if key is None:
        raise FixError(f"manifest에 {file_name} 세트가 없다")
    m = man["sets"][key]
    m["sha256"], m["bytes"] = hashlib.sha256(data).hexdigest(), len(data)
    if man.get("last_change_reason") != CHANGE_REASON:
        man.setdefault("change_history", []).append({"date": man.get("last_updated"), "reason": man.get("last_change_reason")})
        man["last_updated"], man["last_change_reason"] = CHANGE_DATE, CHANGE_REASON
    manifest.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return key


def resolve_set(name: str) -> Path:
    return {"dev": DEV, "test": TEST}.get(name) or Path(name)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", required=True, help="dev | test | 세트 파일 경로")
    ap.add_argument("--allow-sealed", action="store_true", help=f"시험셋 쓰기 허용(환경변수 {G.SEALED_ENV}도 필요)")
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--check", action="store_true", help="파일을 바꾸지 않고 바뀔 행 수만 출력")
    ap.add_argument("--backup-dir", type=Path, help="백업을 둘 폴더(기본: 세트 파일과 같은 폴더)")
    a = ap.parse_args(argv)
    path = resolve_set(a.set)
    sealed = G.check_access(path, allow_sealed=a.allow_sealed)  # 시험셋이면 허용 없이는 열기 전에 막는다
    label = "test(sealed)" if sealed else path.name
    raw = G.read_bytes(path, allow_sealed=a.allow_sealed)
    try:
        data, changed, left = fix_lines(raw)
    except FixError as e:
        print(f"{label}: 실패, 쓰지 않음 — {e}", file=sys.stderr)
        return 1
    ids = "" if sealed else f" ids={','.join(changed) or '-'}"
    if a.check or not changed:
        print(f"{label}: 바뀔 행 {len(changed)}{ids} RFP- 남음 {left} (쓰지 않음) sha256={hashlib.sha256(raw).hexdigest()}")
        return 0
    bak = backup(path, a.backup_dir)
    path.write_bytes(data)
    key = update_manifest(a.manifest, path.name, data)
    print(f"{label}: 바뀐 행 {len(changed)}{ids} RFP- 남음 {left} sha256={hashlib.sha256(data).hexdigest()} bytes={len(data)} "
          f"manifest[{key}] 갱신, 백업 {bak.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
