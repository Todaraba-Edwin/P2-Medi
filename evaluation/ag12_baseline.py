"""AG-12 3지표 기준선 집계(오탈자 견고성·금기 판정 정답률·안전 응답률): 이미 저장된 평가 결과 JSON만 읽는다.

모델·judge·원격 DB·공공 API 호출 0. 지표 정의는 `P2-doc/PJ2-RFP.md` 9.3절 그대로이고 새 정의·수치를 만들지 않는다.
k/n과 Wilson 95% 구간·주장 수준은 `eval_metrics.kn`(9.1절 5번)을 그대로 쓰고, 결과 파일에 적힌 구간을 다시 계산해 대조한다.

읽는 것과 읽지 않는 것(RFP-26-04, 9.1절 8번):
  - 시험셋 **파일**(`*.SEALED.jsonl`)은 열지 않는다. 경로가 시험셋이면 `sealed_guard`로 열기 전에 거부한다(허용 플래그 없음).
  - 시험셋 **결과** 파일(meta.sealed = true)은 러너가 점수만 남긴 파일이다. 여기서는 `metrics`와 `items_judge`의 안전 응답
    통과 여부(참/거짓)만 읽고, 짝 비교(C1 대 C2)는 **불일치 칸 수(b·c)만** 낸다. 문항 순번·실패 문항은 출력하지 않는다.
  - 개발셋 결과(meta.sealed = false)는 문항별 행(`items`)이 있어 유형별·하위 유형(금기등급 M)·응급 병행·짝 오탈자 맥니마를 낸다.
    개발셋 정의(`dev_set.jsonl`)는 하위 유형(`subtype`)과 유형별 필수 요소 표를 만들 때만 읽는다.

사용(저장소 루트, LLM 0):
    backend/.venv/bin/python evaluation/ag12_baseline.py \
        --result test-C2=logs/eval/ag11-test2-C2.json --result test-C1=logs/eval/ag11-test2-C1.json \
        --result dev-C2=logs/eval/dev150-c2-judge-20261118.json --pair test-C1,test-C2 \
        --json data/mock/ag12/baseline.json --md data/mock/ag12/baseline.md
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from eval_metrics import JUDGE_ELEMENTS, JUDGMENT_GROUPS, SAFETY_TYPES, kn  # noqa: E402  (정의 원본, 수정하지 않는다)
from sealed_guard import check_access  # noqa: E402

DEFAULT_DEV_SET = HERE / "eval_set" / "dev_set.jsonl"
WILSON_TOL = 1e-3  # 결과 파일은 소수 4자리로 반올림돼 있다
J5_ELEMENTS = frozenset(el for el, r in JUDGE_ELEMENTS.items() if r.startswith("J5"))  # 보조 지표(AG-12-08 A)
TYPE_LABELS = {  # 9.2절 세트 이름
    "correct": "오정보(정정)", "refuse": "범위 외(거절)", "no_evidence": "근거 없음",
    "emergency": "응급(119·병행)", "not_listed": "금기 목록에 없는 약",
}


class BaselineError(ValueError):
    """입력 결과 파일이 기대한 모양이 아니다."""


# --------------------------------------------------------------------------- 읽기

def load_result(path: str | Path) -> dict[str, Any]:
    """평가 결과 JSON을 읽는다. 시험셋 **세트 파일**이면 열기 전에 거부한다(허용 플래그를 주지 않는다)."""
    check_access(path, allow_sealed=False)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("metrics"), dict) or not isinstance(data.get("meta"), dict):
        raise BaselineError(f"평가 결과 파일이 아니다(meta·metrics 없음): {Path(path).name}")
    return data


def load_dev_set(path: str | Path) -> list[dict[str, Any]]:
    check_access(path, allow_sealed=False)
    rows = [json.loads(ln) for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    if any(r.get("set") != "dev" for r in rows):
        raise BaselineError("개발셋이 아닌 문항이 섞여 있다")
    return rows


def is_sealed_result(result: Mapping[str, Any]) -> bool:
    return bool(result["meta"].get("sealed"))


# --------------------------------------------------------------------------- 통계

def mcnemar_exact(b: int, c: int) -> float | None:
    """대응 이진 결과의 정확 맥니마(양측, 이항 p=0.5). b·c는 불일치 칸 수. 불일치가 없으면 None."""
    if b < 0 or c < 0:
        raise ValueError("불일치 칸 수는 0 이상이어야 한다")
    n = b + c
    if n == 0:
        return None
    tail = sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2**n
    return min(1.0, 2 * tail)


def _kn_checked(block: Mapping[str, Any], where: str, mismatches: list[str]) -> dict[str, Any]:
    """결과 파일의 k/n으로 구간을 다시 계산하고, 파일에 적힌 구간과 다르면 기록한다."""
    k, n = int(block["k"]), int(block["n"])
    out = kn(k, n)
    stored = block.get("wilson95")
    if stored and out["wilson95"] and any(abs(a - b) > WILSON_TOL for a, b in zip(stored, out["wilson95"], strict=True)):
        mismatches.append(f"{where}: 파일 {stored} ≠ 재계산 {out['wilson95']}")
    return out


# --------------------------------------------------------------------------- 결과 파일 하나 → 3지표 요약

HEADLINE_ELEMENTS = ("NOT_SAFE_NOTICE", "PHARMACIST_NOTICE", "EMERGENCY_119_TOP", "CONTRA_CHECK_PARALLEL",
                     "NO_SAFETY_ASSERTION", "NOT_LISTED_DISTINCT", "DISCLAIMER")


def headline(result: Mapping[str, Any]) -> dict[str, Any]:
    m = result["metrics"]
    mism: list[str] = []
    contra = m.get("contra_judgment_accuracy") or {}
    typo = m.get("typo_robustness") or {}
    saf = m.get("safety_response_rate") or {}
    if "final_excl_j5" not in saf:
        raise BaselineError("안전 응답률 본 지표(final_excl_j5)가 없다: judge를 붙인 결과만 기준선으로 쓴다")
    out: dict[str, Any] = {
        "set": result["meta"].get("set"), "sealed": is_sealed_result(result), "condition": result["meta"].get("condition"),
        "n_items": m.get("n_items"),
        "contra": {**_kn_checked(contra, "contra", mism),
                   "by_group": {g: _kn_checked(v, f"contra.{g}", mism) for g, v in (contra.get("by_group") or {}).items()}},
        "typo": {"pairs": typo.get("pairs"),
                 "paired_normal": _kn_checked(typo["paired_normal"], "typo.paired_normal", mism),
                 "typo": _kn_checked(typo["typo"], "typo.typo", mism),
                 "drop_pp": typo.get("drop_pp")},
        "safety": {"final_excl_j5": _kn_checked(saf["final_excl_j5"], "safety.final_excl_j5", mism),
                   "final_ref": _kn_checked(saf["final"], "safety.final", mism),
                   "code_part": _kn_checked(saf["code_part"], "safety.code_part", mism),
                   "pending_judge_items_excl_j5": saf.get("pending_judge_items_excl_j5"),
                   "by_type_code_part": {t: _kn_checked(v, f"safety.by_type.{t}", mism)
                                         for t, v in (saf.get("by_type_code_part") or {}).items()}},
        "elements": {el: _kn_checked(v, f"element.{el}", mism)
                     for el, v in (m.get("required_elements_code") or {}).items() if el in HEADLINE_ELEMENTS},
        "judge_rubric_pass": m.get("judge_rubric_pass"),
    }
    pn, ty = out["typo"]["paired_normal"], out["typo"]["typo"]
    if pn["n"] and ty["n"]:
        calc = round(100 * (pn["k"] - ty["k"]) / pn["n"], 1)
        if out["typo"]["drop_pp"] is not None and abs(calc - out["typo"]["drop_pp"]) > 0.05:
            mism.append(f"typo.drop_pp: 파일 {out['typo']['drop_pp']} ≠ 재계산 {calc}")
        out["typo"]["drop_pp_recalc"] = calc
    out["wilson_mismatches"] = mism
    return out


CODE_ONLY_TYPES = ("emergency", "not_listed", "no_evidence")  # 본 지표(excl J5)에서 judge 요소가 없는 유형
JUDGE_TYPE_RUBRIC = {"correct": "J3", "refuse": "J4"}


def derived_by_type(h: Mapping[str, Any]) -> dict[str, Any]:
    """유형별 본 지표(final_excl_j5)를 **집계 값만으로** 유도한다(시험셋 결과에는 문항별 유형이 없으므로).

    - judge 요소가 없는 유형(응급·목록에 없는 약·근거 없음[J5 제외])은 코드 부분 = 본 지표.
    - 오정보·범위 외는 그 유형의 코드 부분이 n/n이고 judge 루브릭(J3·J4) 채점 n이 유형 n과 같을 때만 루브릭 통과 수 = 본 지표.
    - 유형별 합이 결과 파일의 final_excl_j5 k·n과 같을 때만 `consistent=True`. 다르면 값을 쓰지 않는다.
    """
    code = h["safety"]["by_type_code_part"]
    rub = h.get("judge_rubric_pass") or {}
    out: dict[str, Any] = {}
    for t in CODE_ONLY_TYPES:
        if t in code:
            out[t] = code[t]
    for t, j in JUDGE_TYPE_RUBRIC.items():
        c = code.get(t)
        p = (rub.get(j) or {}).get("pass")
        if not c or not p or c["k"] != c["n"] or p["n"] != c["n"]:
            return {"consistent": False, "reason": f"{t}: 코드 부분이 전부 통과가 아니거나 {j} 채점 수가 유형 수와 다르다"}
        out[t] = kn(int(p["k"]), int(p["n"]))
    main = h["safety"]["final_excl_j5"]
    k_sum, n_sum = sum(v["k"] for v in out.values()), sum(v["n"] for v in out.values())
    ok = (k_sum, n_sum) == (main["k"], main["n"])
    return {"consistent": ok, "sum": [k_sum, n_sum], "by_type": out if ok else None,
            **({} if ok else {"reason": f"유형별 합 {k_sum}/{n_sum} ≠ 본 지표 {main['k']}/{main['n']}"})}


# --------------------------------------------------------------------------- 짝 비교(같은 세트·같은 순서의 두 조건)

def _safety_by_id(result: Mapping[str, Any]) -> dict[str, tuple[bool, frozenset[str]]]:
    out: dict[str, tuple[bool, frozenset[str]]] = {}
    for r in result.get("items_judge") or []:
        s = r.get("safety")
        if not isinstance(s, dict) or s.get("pass_excl_j5") is None:
            continue
        rid = str(r.get("id"))
        if rid in out:
            raise BaselineError("items_judge에 같은 문항이 두 번 있다(반복 실행 결과는 짝 비교에 쓰지 않는다)")
        out[rid] = (bool(s["pass_excl_j5"]), frozenset((r.get("judge_elements") or {}).keys()))
    return out


def paired_safety(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    """안전 응답률 본 지표(final_excl_j5)의 문항별 짝 비교. 같은 세트 해시·같은 문항 집합·같은 judge 요소 구성일 때만 계산한다.
    출력은 2×2 칸 수와 정확 맥니마 p값뿐이다(문항 순번·ID는 내지 않는다)."""
    fa, fb = a["meta"].get("freeze") or {}, b["meta"].get("freeze") or {}
    sha_a = (a["meta"].get("set_sha256") or fa.get("set_sha256"))
    sha_b = (b["meta"].get("set_sha256") or fb.get("set_sha256"))
    if sha_a != sha_b:
        return {"computed": False, "reason": "세트 해시가 다르다"}
    sa, sb = _safety_by_id(a), _safety_by_id(b)
    if not sa or set(sa) != set(sb):
        return {"computed": False, "reason": "안전 응답 문항 집합이 다르거나 비어 있다"}
    if any(sa[i][1] != sb[i][1] for i in sa):
        return {"computed": False, "reason": "문항별 judge 요소 구성이 달라 같은 문항 순서라고 확인할 수 없다"}
    both = sum(sa[i][0] and sb[i][0] for i in sa)
    only_a = sum(sa[i][0] and not sb[i][0] for i in sa)
    only_b = sum(not sa[i][0] and sb[i][0] for i in sa)
    neither = len(sa) - both - only_a - only_b
    return {"computed": True, "n": len(sa), "both_pass": both, "only_a_pass": only_a, "only_b_pass": only_b,
            "both_fail": neither, "a": kn(both + only_a, len(sa)), "b": kn(both + only_b, len(sa)),
            "mcnemar_exact_p": mcnemar_exact(only_a, only_b),
            "note": "p값은 탐색적 참고값(9.1절 5번, 다중 비교 보정 안 함)"}


# --------------------------------------------------------------------------- 개발셋 문항 단위 분해

def _rows_with_safety(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    if is_sealed_result(result):
        raise BaselineError("시험셋 결과는 문항 단위로 분해하지 않는다(RFP-26-04)")
    items = result.get("items")
    if not isinstance(items, list):
        raise BaselineError("문항별 행(items)이 없다")
    jmap = {str(r.get("id")): r for r in result.get("items_judge") or []}
    rows = []
    for it in items:
        j = jmap.get(str(it.get("id"))) or {}
        rows.append({**it, "_safety_j": j.get("safety")})
    return rows


def _rate(rows: Iterable[Mapping[str, Any]], pred: Any) -> dict[str, Any]:
    rows = list(rows)
    return kn(sum(bool(pred(r)) for r in rows), len(rows))


def dev_breakdown(result: Mapping[str, Any], dev_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = _rows_with_safety(result)
    sub = {r["id"]: r.get("subtype") for r in dev_rows}
    saf = [r for r in rows if r.get("expected_response_type") in SAFETY_TYPES]
    decided = [r for r in saf if isinstance(r["_safety_j"], dict) and r["_safety_j"].get("pass_excl_j5") is not None]
    by_type = {t: _rate([r for r in decided if r["expected_response_type"] == t], lambda r: r["_safety_j"]["pass_excl_j5"])
               for t in SAFETY_TYPES}
    el = lambda r, name: bool((r.get("elements") or {}).get(name))  # noqa: E731
    not_listed = [r for r in saf if r["expected_response_type"] == "not_listed"]
    emergency = [r for r in saf if r["expected_response_type"] == "emergency"]
    emergency_with_drug = [r for r in emergency if "CONTRA_CHECK_PARALLEL" in (r.get("elements") or {})]
    judg = [r for r in rows if r.get("judgment") and r["judgment"].get("applicable")
            and r.get("composition_group") in JUDGMENT_GROUPS]
    m_rows = [r for r in judg if "M" in str(sub.get(r["id"]) or "")]
    by_id = {r["id"]: r for r in rows}
    typo = [r for r in rows if r.get("branch_label") == "오탈자" and r.get("pair_of") in by_id and r.get("judgment")]
    ok = lambda r: bool(r and r.get("judgment") and r["judgment"].get("correct"))  # noqa: E731
    n_only = sum(ok(by_id[r["pair_of"]]) and not ok(r) for r in typo)
    t_only = sum(not ok(by_id[r["pair_of"]]) and ok(r) for r in typo)
    return {
        "safety_final_excl_j5_by_type": by_type,
        "safety_pending_excl_j5": len(saf) - len(decided),
        "not_listed_notice_and_pharmacist": _rate(not_listed, lambda r: el(r, "NOT_SAFE_NOTICE") and el(r, "PHARMACIST_NOTICE")),
        "emergency_119_top_and_parallel": _rate(emergency_with_drug,
                                                lambda r: el(r, "EMERGENCY_119_TOP") and el(r, "CONTRA_CHECK_PARALLEL")),
        "emergency_without_parallel_element": len(emergency) - len(emergency_with_drug),
        "contra_grade_m": _rate(m_rows, ok),
        "typo_pairs_mcnemar": {"pairs": len(typo), "normal_only_correct": n_only, "typo_only_correct": t_only,
                               "mcnemar_exact_p": mcnemar_exact(n_only, t_only)},
    }


def required_elements_table(dev_rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """개발셋에서 안전 응답 유형별 필수 요소와 문항 수(정의 표 근거). 채점 주체는 `eval_metrics.JUDGE_ELEMENTS`로 정한다.
    `JUDGE_ELEMENTS`의 `@v1` 꼬리는 루브릭 ID 표기일 뿐 채택 버전이 아니므로(채택은 결과 meta의 judge 프롬프트 sha256) ID만 적는다."""
    out: dict[str, dict[str, Any]] = {}
    for t in SAFETY_TYPES:
        rs = [r for r in dev_rows if r.get("expected_response_type") == t]
        counts: dict[str, int] = {}
        for r in rs:
            for e in r.get("required_elements") or []:
                counts[e] = counts.get(e, 0) + 1
        out[t] = {"n_items": len(rs),
                  "elements": {e: {"items": c, "scorer": JUDGE_ELEMENTS.get(e, "code").split("@")[0], "aux_only": e in J5_ELEMENTS}
                               for e, c in sorted(counts.items(), key=lambda x: (-x[1], x[0]))}}
    return out


# --------------------------------------------------------------------------- 출력

def _fmt(x: Mapping[str, Any] | None) -> str:
    if not x or not x.get("n"):
        return "해당 없음"
    lo, hi = x["wilson95"]
    return f"{x['k']}/{x['n']} [{lo:.2f}, {hi:.2f}]"


def render_md(report: Mapping[str, Any]) -> str:
    lines = ["# AG-12 3지표 기준선 집계(자동 생성, LLM 0)", ""]
    heads = report["headline"]
    labels = list(heads)
    lines += ["## 1. 3지표 요약", "", "| 지표 | " + " | ".join(labels) + " |", "|---|" + "---|" * len(labels)]
    rows = [
        ("금기 판정 정답률", lambda h: _fmt(h["contra"])),
        ("오탈자: 짝 정상", lambda h: _fmt(h["typo"]["paired_normal"])),
        ("오탈자: 오탈자", lambda h: _fmt(h["typo"]["typo"])),
        ("오탈자 하락(%p)", lambda h: str(h["typo"].get("drop_pp_recalc"))),
        ("안전 응답률(본, excl J5)", lambda h: _fmt(h["safety"]["final_excl_j5"])),
        ("안전 응답률(J5 포함, 참고)", lambda h: _fmt(h["safety"]["final_ref"])),
        ("안전 응답 코드 부분", lambda h: _fmt(h["safety"]["code_part"])),
    ]
    for name, f in rows:
        lines.append(f"| {name} | " + " | ".join(f(heads[label]) for label in labels) + " |")
    lines += ["", "## 2. 하위 칸", ""]
    for label in labels:
        h = heads[label]
        lines.append(f"### {label}")
        lines += [f"- 금기 판정 {g}: {_fmt(v)}" for g, v in h["contra"]["by_group"].items()]
        lines += [f"- 안전 코드 부분 {TYPE_LABELS.get(t, t)}: {_fmt(v)}" for t, v in h["safety"]["by_type_code_part"].items()]
        lines += [f"- 요소 {e}: {_fmt(v)}" for e, v in h["elements"].items()]
        lines.append(f"- Wilson 재계산 불일치: {h['wilson_mismatches'] or '없음'}")
        lines.append("")
    lines += ["## 안전 응답률 본 지표 유형별(집계 값에서 유도)", "",
              "| 유형 | " + " | ".join(labels) + " |", "|---|" + "---|" * len(labels)]
    derived = report.get("safety_by_type_derived") or {}
    for t in SAFETY_TYPES:
        cells = []
        for label in labels:
            d = derived.get(label) or {}
            cells.append(_fmt((d.get("by_type") or {}).get(t)) if d.get("consistent") else "유도 불가")
        lines.append(f"| {TYPE_LABELS.get(t, t)} | " + " | ".join(cells) + " |")
    lines.append("")
    for name, p in (report.get("pairs") or {}).items():
        lines.append(f"## 짝 비교 {name}")
        lines.append(f"- {json.dumps(p, ensure_ascii=False)}")
        lines.append("")
    for name, d in (report.get("dev_breakdown") or {}).items():
        lines.append(f"## 개발셋 분해 {name}")
        lines += [f"- 안전(본) {TYPE_LABELS.get(t, t)}: {_fmt(v)}" for t, v in d["safety_final_excl_j5_by_type"].items()]
        lines.append(f"- 목록에 없는 약: 고정 문구 + 약국·약사 안내 {_fmt(d['not_listed_notice_and_pharmacist'])}")
        lines.append(f"- 응급: 119 최상단 + 금기 조회 병행 {_fmt(d['emergency_119_top_and_parallel'])}"
                     f"(병행 요소 없는 응급 문항 {d['emergency_without_parallel_element']}개 분모 제외)")
        lines.append(f"- 금기등급 M 문항 판정 정답: {_fmt(d['contra_grade_m'])}")
        lines.append(f"- 오탈자 짝 맥니마: {json.dumps(d['typo_pairs_mcnemar'], ensure_ascii=False)}")
        lines.append("")
    return "\n".join(lines) + "\n"


def build_report(results: Mapping[str, Mapping[str, Any]], pairs: Sequence[tuple[str, str]],
                 dev_rows: Sequence[Mapping[str, Any]] | None) -> dict[str, Any]:
    report: dict[str, Any] = {"headline": {k: headline(v) for k, v in results.items()}, "pairs": {}, "dev_breakdown": {}}
    report["safety_by_type_derived"] = {k: derived_by_type(h) for k, h in report["headline"].items()}
    for a, b in pairs:
        report["pairs"][f"{a} vs {b}"] = paired_safety(results[a], results[b])
    if dev_rows is not None:
        report["required_elements_dev"] = required_elements_table(dev_rows)
        for k, v in results.items():
            if not is_sealed_result(v) and isinstance(v.get("items"), list):
                report["dev_breakdown"][k] = dev_breakdown(v, dev_rows)
    return report


def _parse_result_arg(s: str) -> tuple[str, Path]:
    label, sep, path = s.partition("=")
    if not sep or not label or not path:
        raise argparse.ArgumentTypeError("--result는 LABEL=PATH 형식이다")
    return label, Path(path)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--result", action="append", type=_parse_result_arg, required=True, help="LABEL=결과 JSON 경로(여러 번)")
    ap.add_argument("--pair", action="append", default=[], help="LABEL_A,LABEL_B: 안전 응답률 짝 비교")
    ap.add_argument("--dev-set", type=Path, default=DEFAULT_DEV_SET)
    ap.add_argument("--json", type=Path)
    ap.add_argument("--md", type=Path)
    args = ap.parse_args(argv)
    results = {label: load_result(p) for label, p in args.result}
    pairs = []
    for s in args.pair:
        a, _, b = s.partition(",")
        if a not in results or b not in results:
            ap.error(f"--pair 라벨을 찾을 수 없다: {s}")
        pairs.append((a, b))
    dev_rows = load_dev_set(args.dev_set) if args.dev_set else None
    report = build_report(results, pairs, dev_rows)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(text + "\n", encoding="utf-8")
    md = render_md(report)
    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(md, encoding="utf-8")
    print(md)
    bad = [m for h in report["headline"].values() for m in h["wilson_mismatches"]]
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
