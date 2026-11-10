"""AG-04 사람 검수 도구: 검수 대상을 표(CSV)로 내보내고, 입력한 결과를 jsonl에 되돌려 넣는다.

    python evaluation/eval_set/review_tool.py export   # data/mock/review/review_{dev,test}.csv 생성
    python evaluation/eval_set/review_tool.py apply    # CSV의 입력 열을 jsonl·manifest에 반영

- 대상: human_review.sample 이 참인 문항, 골든(golden), 불량 답 견본(bad_answer_sample).
- 사람이 채우는 열(CSV 오른쪽 3~4개): 판정(OK/ERROR), 오류내용, 골든확인(Y/N, 골든 행만), 불량답수정(불량 답 행만).
- 시험셋 CSV는 로컬 전용(`data/`)이다. 시험셋은 개선(AG-13) 중에 열람하지 않는다(RFP-26-04). 검수는 정답 확인만 한다.
- apply는 human_review.status/error_found, golden_verified, 불량 답 text(수정 시)를 쓰고 manifest의 sha256·bytes를 다시 계산한다.
  빌더(build_eval_set.py)를 다시 돌리면 검수 결과가 지워지므로 검수를 시작한 뒤에는 재빌드하지 않는다.
"""

import csv
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SETS = {"dev": HERE / "dev_set.jsonl", "test": HERE / "test_set.SEALED.jsonl"}
OUT_DIR = ROOT / "data" / "mock" / "review"
MANIFEST = HERE / "manifest.json"
INPUT_COLS = ["판정", "오류내용", "골든확인", "불량답수정"]
HEAD = ["id", "구분", "그룹", "질문", "응답유형", "제품", "정답요약", "불량답", "검수이유"] + INPUT_COLS


def read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def targets(x: dict) -> bool:
    return bool(x["human_review"]["sample"] or x.get("golden") or x.get("bad_answer_sample"))


def summary(x: dict) -> str:
    items = (x.get("answer") or {}).get("items") or []
    parts = [f"{i.get('kind')}:{i.get('status')}:{'+'.join(i.get('subject') or [])}" for i in items]
    note = (x.get("answer") or {}).get("note") or ""
    return " / ".join(parts) + (f" | {note}" if note else "")


def export() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, path in SETS.items():
        rows = [x for x in read(path) if targets(x)]
        out = OUT_DIR / f"review_{name}.csv"
        if out.exists():
            print(f"이미 있음(덮어쓰지 않음): {out}")
            continue
        with open(out, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(HEAD)
            for x in rows:
                bad = (x.get("bad_answer_sample") or {}).get("text", "")
                hr = x["human_review"]
                w.writerow([x["id"], name, x["composition_group"], x["question"], x["expected_response_type"],
                            "; ".join(x.get("products") or []), summary(x), bad, " / ".join(hr["reasons"]),
                            "", "", "", ""])
        print(f"{name}: {len(rows)}행 -> {out}")


def apply() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for name, path in SETS.items():
        csv_path = OUT_DIR / f"review_{name}.csv"
        if not csv_path.exists():
            continue
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            all_rows = list(csv.DictReader(f))
        rows = read(path)
        golden_ids = {x["id"] for x in rows if x.get("golden")}
        # 판정이 있는 행, 또는 골든 행의 골든확인(Y/N)만 있는 행을 반영한다.
        filled = {r["id"]: r for r in all_rows
                  if (r.get("판정") or "").strip()
                  or (r["id"] in golden_ids and (r.get("골든확인") or "").strip().upper() in ("Y", "N"))}
        n = 0
        for x in rows:
            r = filled.get(x["id"])
            if not r:
                continue
            verdict = (r.get("판정") or "").strip().upper()
            if verdict not in ("", "OK", "ERROR"):
                raise SystemExit(f"{x['id']}: 판정은 OK 또는 ERROR (입력값: {r['판정']!r})")
            hr = x["human_review"]
            if verdict:
                hr["status"] = "검수 완료"
                hr["error_found"] = verdict == "ERROR"
                if verdict == "ERROR":
                    hr["error_note"] = (r.get("오류내용") or "").strip()
            if x.get("golden"):
                ok = (r.get("골든확인") or "").strip().upper() == "Y"
                x["golden_verified"] = ok
                if not ok:  # AG-18-01 B: 골든에서 제외하되 일반 문항으로 유지
                    x["golden"] = False
                    x["golden_excluded"] = {"reason": (r.get("오류내용") or "").strip(),
                                            "decision": "AG-18-01 B (2026-11-10)",
                                            "golden_source": x.get("golden_source")}
            fix = (r.get("불량답수정") or "").strip()
            if x.get("bad_answer_sample"):
                if fix:
                    x["bad_answer_sample"]["text"] = fix
                x["bad_answer_sample"]["status"] = "사람 검수 완료"
            n += 1
        data = "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows).encode("utf-8")
        path.write_bytes(data)
        m = manifest["sets"][name]
        m["sha256"], m["bytes"] = hashlib.sha256(data).hexdigest(), len(data)
        done = [x for x in rows if x["human_review"]["status"] == "검수 완료"]
        m["human_review_done"] = len(done)
        m["human_review_errors"] = sum(bool(x["human_review"]["error_found"]) for x in done)
        m["golden"] = sum(bool(x.get("golden")) for x in rows)
        m["golden_verified"] = sum(bool(x.get("golden_verified")) for x in rows)
        m["golden_excluded"] = sum(bool(x.get("golden_excluded")) for x in rows)
        print(f"{name}: {n}행 반영, 검수 완료 {len(done)}, 오류 {m['human_review_errors']}, 골든 확인 {m['golden_verified']}")
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("export", "apply"):
        raise SystemExit(__doc__)
    export() if sys.argv[1] == "export" else apply()
