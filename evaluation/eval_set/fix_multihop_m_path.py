"""AG-04-07 A(2026-11-17): 이미 만든 평가 세트에서 `multihop_m` 기대 경로의 `search_notice` required를 뺀다.

    backend/.venv/bin/python evaluation/eval_set/fix_multihop_m_path.py --set dev [--check]
    MEDIAGENT_ALLOW_SEALED=… backend/.venv/bin/python evaluation/eval_set/fix_multihop_m_path.py --set PATH/test_set.SEALED.jsonl --allow-sealed [--check]

- 이유: 1·2등급 정의는 코드가 답에 붙이므로(RFP-29-03 A, `grade_defs`) `search_notice`를 required로 두면 모델이 같은 원문을 중복 호출해야만
  Pass가 된다. 빌더(`build_eval_set.py` `path("multihop_m")`)도 같은 날 고쳤다. 문항 재생성은 하지 않는다(질문·정답·다른 칸 불변).
- 대상 행: `expected_path.required`가 옛 `multihop_m` 값과 **정확히 같은** 행만. 바꾼 행만 다시 직렬화하고 나머지 줄은 바이트 그대로 둔다.
  바꿀 행이 원래 직렬화 형식(`json.dumps(ensure_ascii=False)`)과 다르면 아무것도 쓰지 않고 멈춘다. 다시 돌려도 바뀌는 행은 0(멱등).
- **시험셋(`*.SEALED.jsonl`)은 열람하지 않는다**(RFP-26-04): 가드(`sealed_guard`, 환경변수 + `--allow-sealed`)를 거쳐 읽고,
  내용·문항 ID는 출력·기록하지 않는다. 출력은 바뀐 행 수·sha256·백업 경로뿐이다. 개발셋은 바뀐 문항 ID도 출력한다.
- 쓰기 전에 원본을 백업한다(내용 출력 없음). 개발셋 등은 `<파일>.bak`(있으면 `.bak-<UTC>`), 시험셋은 `<이름>.bak-<UTC>.SEALED.jsonl`
  (`.gitignore`의 `*.SEALED.jsonl`과 열람 가드가 백업에도 걸리게). `--backup-dir`로 폴더를 바꿀 수 있다.
- manifest(`--manifest`, 기본 이 폴더의 manifest.json)에서 `file`이 같은 세트의 sha256·bytes를 다시 계산해 쓴다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import sealed_guard as G  # noqa: E402

DEV = HERE / "dev_set.jsonl"
MANIFEST = HERE / "manifest.json"
OLD_REQUIRED = ["identify_drug", "check_contraindications", "search_reason", "search_notice"]
NEW_REQUIRED = ["identify_drug", "check_contraindications", "search_reason"]
DECISION = "AG-04-07 A"
CHANGE_DATE = "2026-11-17"
CHANGE_REASON = (f"{DECISION}({CHANGE_DATE}): multihop_m 기대 경로 required에서 search_notice 제거(RFP-29-03 A, 등급 정의는 코드가 붙임). "
                 "질문·정답·다른 칸 불변, 문항 재생성 없음. 이전 l2-*·l3-* 결과와 섞지 않음")


class FixError(RuntimeError):
    """형식이 예상과 달라 쓰지 않고 멈춘다."""


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
        path = row.get("expected_path") or {}
        if path.get("required") != OLD_REQUIRED:
            out.append(line)
            continue
        if json.dumps(row, ensure_ascii=False) != body:
            raise FixError("대상 행의 직렬화 형식이 예상과 달라 쓰지 않았다")
        path["required"] = list(NEW_REQUIRED)
        out.append(json.dumps(row, ensure_ascii=False) + line[len(body):])
        changed.append(str(row.get("id")))
    return "".join(out).encode("utf-8"), changed


SEALED_SUFFIX = ".SEALED.jsonl"


def backup_path(path: Path, backup_dir: Path | None = None) -> Path:
    """백업 경로. 시험셋은 `X.bak-<UTC>.SEALED.jsonl`로 둬 `.gitignore`(`*.SEALED.jsonl`)와 열람 가드(`.sealed.`)가 그대로 걸리게 한다."""
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    folder = backup_dir or path.parent
    if path.name.endswith(SEALED_SUFFIX):
        return folder / f"{path.name[: -len(SEALED_SUFFIX)]}.bak-{stamp}{SEALED_SUFFIX}"
    bak = folder / f"{path.name}.bak"
    return folder / f"{path.name}.bak-{stamp}" if bak.exists() else bak


def backup(path: Path, backup_dir: Path | None = None) -> Path:
    bak = backup_path(path, backup_dir)
    bak.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, bak)
    return bak


def update_manifest(manifest: Path, file_name: str, data: bytes) -> str:
    man = json.loads(manifest.read_text(encoding="utf-8"))
    key = next((k for k, v in (man.get("sets") or {}).items() if v.get("file") == file_name), None)
    if key is None:
        raise FixError(f"manifest에 {file_name} 세트가 없다")
    m = man["sets"][key]
    m["sha256"], m["bytes"] = hashlib.sha256(data).hexdigest(), len(data)
    if man.get("last_change_reason") != CHANGE_REASON:
        hist = man.setdefault("change_history", [])
        hist.append({"date": man.get("last_updated"), "reason": man.get("last_change_reason")})
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
    sealed = G.check_access(path, allow_sealed=a.allow_sealed)  # 시험셋이면 허용 없이는 열기 전에 막는다
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
    print(f"{label}: 바뀐 행 {len(changed)}{ids} sha256={hashlib.sha256(data).hexdigest()} bytes={len(data)} "
          f"manifest[{key}] 갱신, 백업 {bak.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
