"""AG-12-02 A(2026-11-17): 범위 외 중단·감량·의료진 우회 문항의 `NO_STATE_ASSESSMENT`를 최상위 `required_elements`로 옮긴다.

    backend/.venv/bin/python evaluation/eval_set/fix_no_state_assessment.py --set dev [--check]
    MEDIAGENT_ALLOW_SEALED=… backend/.venv/bin/python evaluation/eval_set/fix_no_state_assessment.py --set PATH/test_set.SEALED.jsonl --allow-sealed [--check]

- 이유: 2026-11-11 AI 수정은 `fix_note`에 "required_elements에 NO_STATE_ASSESSMENT 추가"라고 적었지만 값은 세트 스키마(README §4)에 없는
  `expected.required_elements`에 들어갔다. 채점기(`eval_metrics.element_checks`)와 루브릭 J4 R5(RFP-26-07 A)는 최상위 `required_elements`만 보므로
  R5가 채점·보류 집계에 잡히지 않는다. 측정 시작 전이라 세트를 고칠 수 있다(RFP-23 §5.1). 문항 재생성은 하지 않는다(질문·정답·다른 칸 불변).
- 대상 행: `expected.required_elements`에 `NO_STATE_ASSESSMENT`가 있고 최상위 `required_elements`에는 없는 행만. 최상위 `REFUSAL_WITH_REASON`
  바로 뒤에 넣고(없으면 끝에), 스키마 밖 `expected`는 `required_elements`를 뺀 뒤 비면 키를 지운다. 바꾼 행만 다시 직렬화하고 나머지 줄은
  바이트 그대로 둔다. 다시 돌려도 바뀌는 행은 0(멱등). 최상위에 이미 있으면 `expected`만 정리한다.
- 백업·시험셋 가드·manifest sha256 갱신은 `fix_multihop_m_path.py`의 함수를 그대로 쓴다(내용·문항 ID는 시험셋이면 출력하지 않는다).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
for p in (str(HERE), str(HERE.parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import sealed_guard as G  # noqa: E402
from fix_multihop_m_path import DEV, MANIFEST, FixError, backup  # noqa: E402

ELEMENT = "NO_STATE_ASSESSMENT"
ANCHOR = "REFUSAL_WITH_REASON"
DECISION = "AG-12-02 A"
CHANGE_DATE = "2026-11-17"
CHANGE_REASON = (f"{DECISION}({CHANGE_DATE}): 범위 외 중단·감량·의료진 우회 문항의 {ELEMENT}를 expected.required_elements에서 최상위 "
                 "required_elements로 이동(J4 R5 채점 대상, RFP-26-07 A). 질문·정답·다른 칸 불변, 문항 재생성 없음")


def _needs_fix(row: dict) -> bool:
    exp = row.get("expected")
    return isinstance(exp, dict) and ELEMENT in (exp.get("required_elements") or [])


def fix_row(row: dict) -> None:
    req = list(row.get("required_elements") or [])
    if ELEMENT not in req:
        req.insert(req.index(ANCHOR) + 1 if ANCHOR in req else len(req), ELEMENT)
        row["required_elements"] = req
    exp = dict(row["expected"])
    exp.pop("required_elements", None)
    if exp:
        row["expected"] = exp
    else:
        del row["expected"]


def fix_lines(raw: bytes) -> tuple[bytes, list[str]]:
    """바꾼 바이트와 바꾼 행의 id 목록. 대상이 아닌 줄은 그대로 둔다."""
    out: list[str] = []
    changed: list[str] = []
    for line in raw.decode("utf-8").splitlines(keepends=True):
        body = line.rstrip("\n")
        if not body.strip():
            out.append(line)
            continue
        row = json.loads(body)
        if not _needs_fix(row):
            out.append(line)
            continue
        if json.dumps(row, ensure_ascii=False) != body:
            raise FixError("대상 행의 직렬화 형식이 예상과 달라 쓰지 않았다")
        fix_row(row)
        out.append(json.dumps(row, ensure_ascii=False) + line[len(body):])
        changed.append(str(row.get("id")))
    return "".join(out).encode("utf-8"), changed


def update_manifest(manifest: Path, file_name: str, data: bytes) -> str:
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


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", required=True, help="dev | 세트 파일 경로")
    ap.add_argument("--allow-sealed", action="store_true", help=f"시험셋 쓰기 허용(환경변수 {G.SEALED_ENV}도 필요)")
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--check", action="store_true", help="파일을 바꾸지 않고 바뀔 행 수만 출력")
    ap.add_argument("--backup-dir", type=Path, help="백업을 둘 폴더(기본: 세트 파일과 같은 폴더)")
    a = ap.parse_args(argv)
    path = DEV if a.set == "dev" else Path(a.set)
    sealed = G.check_access(path, allow_sealed=a.allow_sealed)
    raw = G.read_bytes(path, allow_sealed=a.allow_sealed)
    data, changed = fix_lines(raw)
    ids = "" if sealed else f" ids={','.join(changed) or '-'}"
    label = "test(sealed)" if sealed else path.name
    if a.check or not changed:
        print(f"{label}: 바뀔 행 {len(changed)}{ids} (쓰지 않음) sha256={hashlib.sha256(raw).hexdigest()}")
        return 0
    bak = backup(path, a.backup_dir)
    path.write_bytes(data)
    key = update_manifest(a.manifest, path.name, data)
    print(f"{label}: 바뀐 행 {len(changed)}{ids} sha256={hashlib.sha256(data).hexdigest()} bytes={len(data)} manifest[{key}] 갱신, 백업 {bak.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
