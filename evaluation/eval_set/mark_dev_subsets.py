"""AG-04 PRD-16-02 A: 개발셋에 `dev_reliability_core`·`dev_golden` 표시를 쓴다.

    backend/.venv/bin/python evaluation/eval_set/mark_dev_subsets.py          # 표시 + manifest 갱신
    backend/.venv/bin/python evaluation/eval_set/mark_dev_subsets.py --check  # 파일을 바꾸지 않고 결과만 출력

선택 규칙(시드 고정·멱등. 같은 입력이면 같은 결과이고, 두 번 돌려도 파일이 같다):
- 개발 안전 핵심 40 = 응급 10·금기 목록에 없는 약 10·오정보 20. 개발셋의 해당 composition_group
  (`정상-응급`·`정상-목록에없는약`·`오정보`) 전부라 고를 여지가 없다. 오정보에 AG-18 수정 행(dev-113·115)이 있으나
  빼면 20이 되지 않아 포함하고 manifest `dev_reliability_core_fixed_rows`에 적는다.
- 개발 골든 20 = composition_group 10개 × 2(분기 유형별로 고르게). 후보에서 뺀다:
  수정 행(`human_review.fixed`, AI가 고친 답이라 사람 확인 전)·`error_found`·불량 답 견본(`bad_answer_sample`)·
  `provisional`(BE-10 사전 의존). 후보 중 사람 검수 OK 행을 먼저, 같은 순위는 sha256(시드:id) 순으로 2개를 뽑는다.
  예외: 모호 group은 20문항이 모두 BE-10 의존(provisional)이라 후보가 0이므로, 이 group만 수정 행·error·불량 답을
  뺀 provisional 행에서 뽑고 manifest `dev_golden_provisional_fallback`에 적는다(BE-10 사전 확정 뒤 다시 확인).
- 표시만 한다. `golden`·`golden_verified`·`reliability_core`(시험셋 표시, 개발셋은 0 유지)와 9장 지표·세트 구성은
  바꾸지 않는다. 골든의 사람·AI 정답 확인은 별도다(manifest `dev_golden_note`).
- 빌더(build_eval_set.py)를 다시 돌리면 표시가 지워지므로 이 스크립트를 다시 돌린다.
- manifest 갱신 방식은 review_tool.py apply와 같다(sha256·bytes 재계산, 집계 갱신).
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEV = HERE / "dev_set.jsonl"
MANIFEST = HERE / "manifest.json"
SEED = 20261110
CORE_GROUPS = {"정상-응급": 10, "정상-목록에없는약": 10, "오정보": 20}
GOLDEN_PER_GROUP = 2
NOTE = "표시만 했다. 사람·AI 정답 확인(golden_verified)은 별도이며 이 스크립트는 건드리지 않는다."


def _rank(x: dict) -> tuple[int, str]:
    hr = x["human_review"]
    reviewed_ok = hr.get("status") == "검수 완료" and not hr.get("error_found")
    return (0 if reviewed_ok else 1, hashlib.sha256(f"{SEED}:{x['id']}".encode()).hexdigest())


def golden_eligible(x: dict, *, allow_provisional: bool = False) -> bool:
    hr = x["human_review"]
    if hr.get("fixed") or hr.get("error_found") or x.get("bad_answer_sample"):
        return False
    return allow_provisional or not x.get("provisional")


def mark(rows: list[dict]) -> None:
    """rows에 dev_reliability_core·dev_golden(bool)을 쓴다(처음부터 다시 계산하므로 멱등)."""
    groups = sorted({x["composition_group"] for x in rows})
    gold: set[str] = set()
    for g in groups:
        in_g = [x for x in rows if x["composition_group"] == g]
        cand = sorted((x for x in in_g if golden_eligible(x)), key=_rank)
        if len(cand) < GOLDEN_PER_GROUP:  # 모호처럼 group 전체가 provisional인 경우만 예외
            cand = sorted((x for x in in_g if golden_eligible(x, allow_provisional=True)), key=_rank)
        if len(cand) < GOLDEN_PER_GROUP:
            raise SystemExit(f"{g}: 골든 후보가 {GOLDEN_PER_GROUP}개 미만({len(cand)})")
        gold |= {x["id"] for x in cand[:GOLDEN_PER_GROUP]}
    for x in rows:
        x["dev_reliability_core"] = x["composition_group"] in CORE_GROUPS
        x["dev_golden"] = x["id"] in gold


def summarize(rows: list[dict]) -> dict:
    core = [x for x in rows if x["dev_reliability_core"]]
    gold = [x for x in rows if x["dev_golden"]]
    return {
        "dev_reliability_core": len(core),
        "dev_reliability_core_by_group": dict(Counter(x["composition_group"] for x in core)),
        "dev_reliability_core_fixed_rows": sorted(x["id"] for x in core if x["human_review"].get("fixed")),
        "dev_golden": len(gold),
        "dev_golden_by_group": dict(Counter(x["composition_group"] for x in gold)),
        "dev_golden_provisional_fallback": sorted(x["id"] for x in gold if x.get("provisional")),
        "dev_golden_note": NOTE,
    }


def main(argv: list[str]) -> int:
    rows = [json.loads(line) for line in DEV.read_text(encoding="utf-8").splitlines() if line.strip()]
    mark(rows)
    summ = summarize(rows)
    if "--check" in argv:
        print(json.dumps(summ, ensure_ascii=False, indent=1))
        return 0
    data = "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows).encode("utf-8")
    DEV.write_bytes(data)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    m = manifest["sets"]["dev"]
    m["sha256"], m["bytes"] = hashlib.sha256(data).hexdigest(), len(data)
    m.update(summ)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"dev_reliability_core={summ['dev_reliability_core']} dev_golden={summ['dev_golden']} sha256={m['sha256'][:12]}…")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
