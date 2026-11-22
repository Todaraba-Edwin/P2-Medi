"""AG-12 judge 보정(RFP-26-03) 집계 골격: 사람 라벨(CSV) vs judge 결과(JSON)의 루브릭 항목별 일치율·Cohen's κ.

    backend/.venv/bin/python evaluation/judge_calib/calib_agreement.py \
        --labels data/mock/judge_calib/calib40-labels.csv --judge data/mock/judge_calib/calib40-judge.json [--out PATH]

- **judge를 부르지 않는다.** judge 결과는 이미 저장된 JSON을 읽는다(`load_judge_results`). 호출 자리는 `JudgeScorer` 프로토콜과
  `NotCalledJudge`(항상 "not_called")만 있고, 실제 호출은 AG-11 `evaluation/judge/sonnet_judge.py`의 `SonnetJudge`(보정 실행 `calib_result`)에서 연다(비용 상한 지시서 필요).
- 사람 라벨 칸 기입 규칙(README.md): `pass`/`fail`(또는 `P`/`F`, `Y`/`N`, `1`/`0`, `○`/`×`), J1은 `뒷받침안됨/전체주장`(예: `0/4` → pass,
  `1/4` → fail) 또는 pass/fail. `N/A`·빈 칸은 집계에서 뺀다(빈 칸은 "라벨 미완료"로 따로 센다).
- judge 결과 JSON 형식(RFP-26 §7.5 공통 출력 스키마를 문항별로 묶은 것):
    {"meta": {"judge_model": "claude-sonnet-5-5", "rubric_versions": {"J3": "J3@v1", ...}},
     "items": {"dev-096": {"J3": {"rubric": "J3@v1", "items": {"R1": {"pass": true, "reason": "...", "evidence": []}, ...},
                                  "overall_pass": true},
                           "J1": {"claims": [{"id": 1, "text": "...", "supported": true, "evidence": ["c1"]}, ...], "faithfulness": 1.0}}}}
  J1은 `claims`에서 "unsupported 0개 → pass"로 이진화한다(사람 J1 칸과 같은 정의). judge 오류(`status: "error"`)는 집계에서 빼고 수를 보고한다.
- 집계: 항목(열)마다 n·일치 k·일치율·Wilson 95%·Cohen's κ·2×2 표(사람 pass/fail × judge pass/fail), 루브릭(J1·J3·J4·J5)별 합산,
  전체 합산, 불일치 사례 목록(문항 ID·항목·사람·judge·judge 이유). 잠정 기준 일치율 ≥ 0.85·κ ≥ 0.6(RFP-26 §7.3 2번, 측정 뒤 조정)을
  항목별·루브릭별로 표시하되, n이 작으면(≤ 8) 유의성을 주장하지 않는다(PJ2-RFP.md 9.1절 5번, `eval_metrics.kn`의 claim 문구 재사용).
- κ가 정의되지 않는 경우(한쪽이 전부 같은 값이라 pe = 1)는 `None`으로 두고 이유를 적는다.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
for p in (str(HERE.parent), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import eval_metrics as M  # noqa: E402
from select_calib40 import ALL_RUBRIC_COLS, NA, RUBRIC_COLS  # noqa: E402

AGREE_MIN = 0.85  # RFP-26 §7.3 잠정 기준(근거 자료 없는 잠정값, 측정 뒤 조정)
KAPPA_MIN = 0.6
JUDGE_MODEL = "claude-sonnet-5-5"  # RFP-26-01 고정
AGREEMENT_VERSION = "calib-agreement@v1"

_PASS = {"pass", "p", "y", "yes", "1", "true", "○", "o", "통과"}
_FAIL = {"fail", "f", "n", "no", "0", "false", "×", "x", "실패"}


# --------------------------------------------------------------------------- judge 인터페이스(호출 안 함)

class JudgeScorer(Protocol):
    model_id: str

    def score_items(self, items: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
        """`calib40-items.jsonl` 행들 → {문항 ID: {루브릭 ID: §7.5 출력}}. 실제 구현은 AG-11 `evaluation/judge/sonnet_judge.py`의 `SonnetJudge`."""
        ...


class NotCalledJudge:
    """자리 표시. 어떤 호출도 하지 않고 모든 문항을 `not_called`로 돌려준다."""

    model_id = JUDGE_MODEL
    called = 0

    def score_items(self, items: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
        return {str(it["id"]): {r: {"rubric": None, "status": "not_called"} for r in it.get("rubrics") or []} for it in items}


# --------------------------------------------------------------------------- 라벨 읽기

def parse_cell(value: str | None) -> bool | None:
    """셀 → True(pass)/False(fail)/None(N/A·빈 칸). J1의 `k/n`(뒷받침안됨/전체주장)은 k == 0이면 pass."""
    v = (value or "").strip()
    if not v or v.upper() == NA:
        return None
    low = v.lower()
    if low in _PASS:
        return True
    if low in _FAIL:
        return False
    if "/" in v:
        k, _, n = v.partition("/")
        try:
            ki, ni = int(k.strip()), int(n.strip())
        except ValueError as e:
            raise ValueError(f"J1 칸은 '뒷받침안됨/전체주장' 정수 형식이어야 한다: {v!r}") from e
        if ki < 0 or ni < 0 or ki > ni:
            raise ValueError(f"J1 칸 값이 범위를 벗어났다: {v!r}")
        if ni == 0:
            return None  # 주장이 없으면 J1을 채점하지 않는다
        return ki == 0
    raise ValueError(f"알 수 없는 라벨 값: {v!r} (pass/fail, P/F, Y/N, 1/0, k/n)")


def read_labels(path: Path) -> tuple[dict[str, dict[str, bool]], dict[str, list[str]]]:
    """CSV → ({id: {항목: bool}}, {id: [비어 있는(미완료) 항목]})."""
    labels: dict[str, dict[str, bool]] = {}
    unfilled: dict[str, list[str]] = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            iid = row["id"]
            labels[iid] = {}
            for col in ALL_RUBRIC_COLS:
                raw = row.get(col)
                if raw is None:
                    continue
                if not raw.strip():
                    unfilled.setdefault(iid, []).append(col)
                    continue
                val = parse_cell(raw)
                if val is not None:
                    labels[iid][col] = val
    return labels, unfilled


# --------------------------------------------------------------------------- judge 결과 읽기

def load_judge_results(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "items" not in data:
        raise SystemExit("judge 결과 JSON에 items가 없다")
    return data


def judge_to_labels(judge: Mapping[str, Any]) -> tuple[dict[str, dict[str, bool]], dict[str, dict[str, str]], list[dict[str, str]]]:
    """judge 출력 → 사람 라벨과 같은 열 이름의 bool. 반환: (labels, reasons, errors)."""
    labels: dict[str, dict[str, bool]] = defaultdict(dict)
    reasons: dict[str, dict[str, str]] = defaultdict(dict)
    errors: list[dict[str, str]] = []
    for iid, per_rubric in (judge.get("items") or {}).items():
        for rid, out in (per_rubric or {}).items():
            if not isinstance(out, dict):
                continue
            if out.get("status") in ("error", "not_called"):
                errors.append({"id": iid, "rubric": rid, "status": str(out.get("status"))})
                continue
            if rid == "J1":
                claims = out.get("claims")
                if not claims:
                    continue
                unsupported = [c for c in claims if not c.get("supported")]
                labels[iid]["J1(뒷받침안됨/전체주장)"] = not unsupported
                reasons[iid]["J1(뒷받침안됨/전체주장)"] = "; ".join(str(c.get("text", ""))[:80] for c in unsupported) or "모든 주장 뒷받침"
            elif rid in RUBRIC_COLS:
                for r_key, r_val in (out.get("items") or {}).items():
                    col = f"{rid}_{r_key}"
                    if col in RUBRIC_COLS[rid] and isinstance(r_val, dict) and r_val.get("pass") is not None:
                        labels[iid][col] = bool(r_val["pass"])
                        reasons[iid][col] = str(r_val.get("reason") or "")
    return dict(labels), dict(reasons), errors


# --------------------------------------------------------------------------- 일치율·κ

def cohen_kappa(a: int, b: int, c: int, d: int) -> float | None:
    """2×2 표(a: 둘 다 pass, b: 사람 pass·judge fail, c: 사람 fail·judge pass, d: 둘 다 fail)의 Cohen's κ. pe = 1이면 None."""
    n = a + b + c + d
    if n == 0:
        return None
    po = (a + d) / n
    pe = ((a + b) * (a + c) + (c + d) * (b + d)) / (n * n)
    if pe >= 1.0:
        return None
    return (po - pe) / (1 - pe)


def _table(pairs: list[tuple[bool, bool]]) -> dict[str, int]:
    t = {"a_pass_pass": 0, "b_human_pass_judge_fail": 0, "c_human_fail_judge_pass": 0, "d_fail_fail": 0}
    for h, j in pairs:
        key = "a_pass_pass" if h and j else "b_human_pass_judge_fail" if h else "c_human_fail_judge_pass" if j else "d_fail_fail"
        t[key] += 1
    return t


def _stats(pairs: list[tuple[bool, bool]]) -> dict[str, Any]:
    t = _table(pairs)
    n = len(pairs)
    k = t["a_pass_pass"] + t["d_fail_fail"]
    kappa = cohen_kappa(t["a_pass_pass"], t["b_human_pass_judge_fail"], t["c_human_fail_judge_pass"], t["d_fail_fail"])
    agree = M.kn(k, n)
    passes = (agree["rate"] is not None and agree["rate"] >= AGREE_MIN and kappa is not None and kappa >= KAPPA_MIN)
    return {"agreement": agree, "kappa": None if kappa is None else round(kappa, 4),
            "kappa_note": None if kappa is not None or n == 0 else "κ 정의 불가(한쪽 라벨이 모두 같은 값, pe=1)",
            "table": t, "meets_provisional": passes if n else None}


def agreement(human: Mapping[str, Mapping[str, bool]], judge: Mapping[str, Mapping[str, bool]],
              judge_reasons: Mapping[str, Mapping[str, str]] | None = None) -> dict[str, Any]:
    """항목별·루브릭별·전체 일치율·κ와 불일치 사례. 사람과 judge 양쪽에 값이 있는 (문항, 항목)만 센다."""
    by_col: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    disagreements: list[dict[str, Any]] = []
    human_only = judge_only = 0
    for iid, cols in human.items():
        jc = judge.get(iid) or {}
        for col, h in cols.items():
            if col not in jc:
                human_only += 1
                continue
            j = jc[col]
            by_col[col].append((h, j))
            if h != j:
                disagreements.append({"id": iid, "item": col, "human": h, "judge": j,
                                      "judge_reason": ((judge_reasons or {}).get(iid) or {}).get(col, "")})
    for iid, cols in judge.items():
        judge_only += sum(1 for col in cols if col not in (human.get(iid) or {}))

    per_item = {col: _stats(by_col[col]) for col in ALL_RUBRIC_COLS if by_col.get(col)}
    per_rubric = {}
    for rid, cols in RUBRIC_COLS.items():
        pairs = [p for c in cols for p in by_col.get(c, [])]
        if pairs:
            per_rubric[rid] = _stats(pairs)
    all_pairs = [p for ps in by_col.values() for p in ps]
    return {"version": AGREEMENT_VERSION, "thresholds": {"agreement_min": AGREE_MIN, "kappa_min": KAPPA_MIN,
                                                        "note": "잠정(RFP-26 §7.3 2번). n≤8 항목은 유의성 주장 안 함"},
            "n_pairs": len(all_pairs), "human_only": human_only, "judge_only": judge_only,
            "per_item": per_item, "per_rubric": per_rubric, "overall": _stats(all_pairs) if all_pairs else None,
            "disagreements": disagreements}


def render(report: Mapping[str, Any]) -> str:
    lines = [f"쌍 {report['n_pairs']} (사람만 {report['human_only']}, judge만 {report['judge_only']})"]

    def line(name: str, s: Mapping[str, Any]) -> str:
        ag = s["agreement"]
        return (f"  {name:<24} n={ag['n']:<3} 일치 {ag['k']}/{ag['n']} = {ag['rate']}  Wilson {ag['wilson95']}  κ={s['kappa']}"
                f"  {'기준 충족' if s['meets_provisional'] else '미달'}  [{ag['claim']}]")

    lines.append("루브릭별:")
    lines.extend(line(r, s) for r, s in report["per_rubric"].items())
    lines.append("항목별:")
    lines.extend(line(c, s) for c, s in report["per_item"].items())
    if report["overall"]:
        lines.append(line("전체", report["overall"]))
    lines.append(f"불일치 {len(report['disagreements'])}건:")
    lines.extend(f"  {d['id']} {d['item']}: 사람={'pass' if d['human'] else 'fail'} judge={'pass' if d['judge'] else 'fail'} {d['judge_reason'][:80]}"
                 for d in report["disagreements"][:40])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--labels", required=True, type=Path)
    ap.add_argument("--judge", required=True, type=Path, help="저장된 judge 결과 JSON(이 스크립트는 judge를 부르지 않는다)")
    ap.add_argument("--out", type=Path, default=None, help="집계 JSON 출력 경로(기본: 라벨 CSV 옆 calib40-agreement.json)")
    a = ap.parse_args(argv)
    human, unfilled = read_labels(a.labels)
    judge = load_judge_results(a.judge)
    jl, jr, jerr = judge_to_labels(judge)
    report = agreement(human, jl, jr)
    report["unfilled_human"] = unfilled
    report["judge_errors"] = jerr
    report["judge_meta"] = judge.get("meta")
    print(render(report))
    if unfilled:
        print(f"라벨 미완료 {sum(len(v) for v in unfilled.values())}칸 ({len(unfilled)}문항)")
    if jerr:
        print(f"judge 오류·미호출 {len(jerr)}건(집계 제외)")
    out = a.out or a.labels.with_name("calib40-agreement.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"출력: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
