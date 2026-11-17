"""AG-11 측정 결과 파일의 동결 항목 점검(PJ2-RFP.md 9.6절 "측정 기간 동결", RFP-34-04 A). 모델·도구·네트워크 호출 0.

`eval_runner`가 쓴 결과 JSON이 "무엇으로 잰 결과인가"를 다시 확인할 수 있는 항목을 모두 담고 있는지 본다. 값이 맞는지(정답인지)는 보지 않고,
**항목이 있는지와 서로 어긋나지 않는지**만 본다. 측정 전 dry-run(가짜 모델·가짜 judge)과 본 측정 결과 모두에 쓴다.

점검 항목(`FREEZE_ITEMS`):
  세트 sha256·manifest 일치, 세트 판, 비교 조건, 에이전트 모델, 프롬프트 묶음·파일 해시, 그래프 버전(조건과 맞는지), 하네스 소스 해시,
  `harness@v1` 조건표(조건 일치), 사전 판(`--dict-version`과 일치), 코퍼스 출처·지문, 오탈자 보정 스위치(조건과 맞는지),
  호출 상한·LLM 설정(온도·추론 설정·출력 토큰 상한)·검색 방식·파일별 기준일(`run_settings`), 경로 채점 규칙·패턴 버전, 평가 모드, judge 모델·루브릭 버전·judge 프롬프트 sha256(`--require-judge`일 때), Ragas 계산 규칙 버전.

사용(저장소 루트):
    backend/.venv/bin/python evaluation/freeze_check.py logs/eval/RESULT.json [...] [--dict-version be10-dict-s1-1055d3576876] [--require-judge]
    backend/.venv/bin/python evaluation/freeze_check.py A.json B.json --same   # 두 결과가 같은 동결 값으로 잰 것인지(조건·보정 스위치·그래프 제외)
종료 코드: 0 = 모두 통과, 1 = 빠지거나 어긋난 항목 있음.

측정 기간 동결(`freeze_diff`): `eval_runner --baseline 이전결과.json`이 실행 전에 이번 실행 설정과 이전 측정 결과의 동결 값(`FROZEN_KEYS`)을 비교하고,
다르면 `--freeze-diff-reason "이유"` 없이는 시작하지 않는다(RFP-29 H16, RFP-34-04 A). 에이전트 쪽 수정(프롬프트·ReAct 그래프·하네스 소스)은
동결 대상이 아니다(수정마다 버전이 결과에 기록된다).
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

EXPECTED_DICT_VERSION = "be10-dict-s1-1055d3576876"  # AG-11 고정 사전 판(2026-11-17 정합성 점검)
JUDGE_MODEL = "claude-sonnet-5-5"  # RFP-26-01 고정
HARNESS_VERSION = "harness@v1"
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
# 조건 → 기대하는 오탈자 보정 스위치(None = 조건이 정하지 않음: C2는 기본 켬이지만 비교용으로 끌 수 있다)
TYPO_BY_CONDITION: dict[str, bool | None] = {"C1": False, "C1+": True, "C2": None}
# 조건 → 그래프 버전 글자의 머리(C2는 ReAct 그래프 소스 해시, C1·C1+는 파이프라인 규칙 버전)
GRAPH_PREFIX: dict[str, str] = {"C1": "c1-pipeline@", "C1+": "c1plus-pipeline@", "C2": "graph-src@"}
FREEZE_ITEMS = ("set_sha256", "set_manifest_match", "set_version", "condition", "model", "prompt", "graph", "harness_src", "harness_table",
                "dict_version", "corpus", "typo_correction", "call_limit", "run_settings", "trajectory_rule", "patterns", "eval_mode", "judge_model",
                "judge_rubrics", "judge_prompt_sha256", "ragas_version")
# 측정 기간(기준선 AG-11 ~ 최종 재측정 AG-14) 동안 바뀌면 안 되는 값(9.6절: 평가 세트 해시·judge 모델·루브릭·지표·모델 ID·호출 상한, + 사전·코퍼스·
# LLM 설정). C1·C1+ 규칙(파이프라인 버전)은 같은 조건끼리 비교할 때만 본다(`freeze_diff`).
FROZEN_KEYS = ("set_sha256", "set_version", "model", "call_limit", "run_settings", "dict_version", "corpus", "trajectory_rule", "patterns",
               "judge_model", "judge_rubrics", "judge_prompt_sha256", "ragas_version")
PIPELINE_CONDITIONS = ("C1", "C1+")
JUDGE_ITEMS = ("judge_model", "judge_rubrics", "judge_prompt_sha256", "ragas_version")
# `--same` 비교에서 조건마다 달라도 되는 항목(조건 자체와 조건이 정하는 값)
VARY_BY_CONDITION = ("condition", "graph", "harness_table", "typo_correction")


def _row(item: str, ok: bool, value: Any, why: str = "") -> dict[str, Any]:
    return {"item": item, "ok": bool(ok), "value": value, "why": why}


def freeze_values(result: dict[str, Any]) -> dict[str, Any]:
    """결과 파일에서 동결 항목 값을 꺼낸다(없으면 None). 비교(`--same`)와 점검이 같은 값을 본다."""
    m = result.get("meta") or {}
    v = m.get("versions") or {}
    j = m.get("judge") or {}
    prompt = v.get("prompt") or {}
    harness = m.get("harness") or {}
    typo = m.get("typo_correction") or {}
    corpus = v.get("corpus") or {}
    return {
        "set_sha256": m.get("set_sha256"), "set_manifest_match": m.get("match"), "set_version": m.get("set_version"),
        "condition": m.get("condition"), "model": (v.get("model") or {}).get("agent") if isinstance(v.get("model"), dict) else v.get("model"),
        "prompt": {"set": prompt.get("set") or m.get("prompt_set"), "files": prompt.get("files")} if prompt else None,
        "graph": v.get("graph"), "harness_src": v.get("harness"),
        "harness_table": {k: harness.get(k) for k in ("version", "condition", "baseline", "selection_limits")} if harness else None,
        "dict_version": (v.get("dict") or {}).get("version"),
        "corpus": {k: corpus.get(k) for k in ("source", "n_chunks", "sha256")} if corpus else None,
        "typo_correction": {k: typo.get(k) for k in ("enabled", "notice_status", "min_score", "min_gap")} if typo else None,
        "call_limit": (m.get("run_settings") or {}).get("call_limit"),
        "run_settings": {k: v for k, v in (m.get("run_settings") or {}).items() if k != "call_limit"} or None,
        "trajectory_rule": m.get("trajectory_rule"), "patterns": m.get("patterns"), "eval_mode": m.get("eval_mode_env"),
        "judge_model": j.get("model"), "judge_rubrics": j.get("rubrics"), "judge_prompt_sha256": j.get("prompt_sha256"), "ragas_version": j.get("ragas"),
    }


def check_result(result: dict[str, Any], *, dict_version: str | None = EXPECTED_DICT_VERSION, require_judge: bool = False,
                 require_manifest_match: bool = True) -> list[dict[str, Any]]:
    """결과 하나의 동결 항목 점검표. 각 행은 `{item, ok, value, why}`다. judge 항목은 `require_judge`일 때만 필수다(아니면 값이 없어도 통과)."""
    fv = freeze_values(result)
    cond = fv["condition"]
    rows: list[dict[str, Any]] = []

    def add(item: str, ok: bool, why: str = "") -> None:
        rows.append(_row(item, ok, fv[item], "" if ok else why))

    add("set_sha256", isinstance(fv["set_sha256"], str) and bool(_SHA64.match(fv["set_sha256"])), "세트 파일 sha256이 없다")
    add("set_manifest_match", fv["set_manifest_match"] is True or not require_manifest_match, "세트 해시가 manifest와 다르거나 대조하지 못했다")
    add("set_version", bool(fv["set_version"]), "세트 판이 없다")
    add("condition", cond in GRAPH_PREFIX, f"연결된 비교 조건이 아니다: {cond!r}")
    add("model", bool(fv["model"]), "에이전트 모델 ID가 없다")
    p = fv["prompt"] or {}
    add("prompt", bool(p.get("set")) and bool(p.get("files")), "프롬프트 묶음 이름·파일 해시가 없다")
    g = fv["graph"]
    add("graph", isinstance(g, str) and cond in GRAPH_PREFIX and g.startswith(GRAPH_PREFIX[cond]), f"그래프 버전이 조건 {cond}와 맞지 않는다: {g!r}")
    add("harness_src", isinstance(fv["harness_src"], str) and fv["harness_src"].startswith("harness-src@"), "하네스 소스 해시가 없다")
    h = fv["harness_table"] or {}
    add("harness_table", h.get("version") == HARNESS_VERSION and h.get("condition") == cond and bool(h.get("baseline")),
        f"`{HARNESS_VERSION}` 조건표가 없거나 조건이 다르다")
    add("dict_version", bool(fv["dict_version"]) and (dict_version is None or fv["dict_version"] == dict_version),
        f"사전 판이 기대값({dict_version})과 다르다")
    c = fv["corpus"] or {}
    add("corpus", bool(c.get("source")) and isinstance(c.get("sha256"), str) and bool(_SHA64.match(c["sha256"])) and c.get("n_chunks") is not None,
        "코퍼스 출처·지문이 없다")
    t = fv["typo_correction"] or {}
    want = TYPO_BY_CONDITION.get(cond)
    add("typo_correction", isinstance(t.get("enabled"), bool) and (want is None or t["enabled"] is want) and t.get("min_score") is not None,
        f"오탈자 보정 스위치 기록이 없거나 조건 {cond}와 다르다")
    add("call_limit", isinstance(fv["call_limit"], int) and fv["call_limit"] > 0, "모델 호출 상한 기록이 없다")
    rs = fv["run_settings"] or {}
    add("run_settings", all(k in rs for k in ("llm", "retrieval", "api_enabled", "file_as_of")) and rs.get("api_enabled") is False,
        "실행 설정(LLM 설정·검색 방식·API 끔·파일별 기준일) 기록이 없거나 API가 켜져 있다")
    add("trajectory_rule", bool(fv["trajectory_rule"]), "경로 채점 규칙 버전이 없다")
    add("patterns", bool(fv["patterns"]), "평가 패턴 버전이 없다")
    add("eval_mode", str(fv["eval_mode"]) in ("1", "eval"), "평가 모드(`MEDIAGENT_EVAL=1`)로 돌린 기록이 아니다")
    add("judge_model", (fv["judge_model"] == JUDGE_MODEL) if (require_judge or fv["judge_model"]) else True, f"judge 모델이 {JUDGE_MODEL}이 아니다")
    r = fv["judge_rubrics"]
    add("judge_rubrics", (isinstance(r, dict) and set(r) == {"J1", "J2", "J3", "J4", "J5"}) if (require_judge or r) else True, "루브릭 버전(J1~J5)이 없다")
    s = fv["judge_prompt_sha256"]
    add("judge_prompt_sha256", (isinstance(s, str) and bool(_SHA64.match(s))) if (require_judge or s) else True, "judge 프롬프트 sha256이 없다")
    add("ragas_version", bool(fv["ragas_version"]) if (require_judge or fv["ragas_version"]) else True, "Ragas 계산 규칙 버전이 없다")
    assert [x["item"] for x in rows] == list(FREEZE_ITEMS)  # noqa: S101 - 점검표가 항목 목록과 같은 순서·같은 수인지(코드 불변식)
    return rows


def same_freeze(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    """두 결과가 같은 동결 값으로 잰 것인가(조건·그래프·조건표·보정 스위치는 조건마다 달라도 된다). 다른 항목만 돌려준다."""
    fa, fb = freeze_values(a), freeze_values(b)
    return [{"item": k, "a": fa[k], "b": fb[k]} for k in FREEZE_ITEMS if k not in VARY_BY_CONDITION and fa[k] != fb[k]]


def freeze_diff(planned: dict[str, Any], baseline: dict[str, Any]) -> list[dict[str, Any]]:
    """이번 실행(`planned`: 실행 전에 만든 결과 모양 `{"meta": ...}`)과 이전 측정 결과의 동결 값 차이. 비어 있으면 같은 조건으로 재는 것이다.

    judge 항목은 **양쪽 모두 judge를 붙였을 때만** 비교한다(코드 채점만 한 실행과 judge 실행을 섞어 비교하지 않는다).
    같은 고정 파이프라인 조건(C1·C1+)끼리는 파이프라인 규칙 버전(`graph`)도 본다(C1 규칙 동결)."""
    fp_, fb = freeze_values(planned), freeze_values(baseline)
    both_judge = bool(fp_["judge_model"]) and bool(fb["judge_model"])
    keys = [k for k in FROZEN_KEYS if k not in JUDGE_ITEMS or both_judge]
    if fp_["condition"] == fb["condition"] and fp_["condition"] in PIPELINE_CONDITIONS:
        keys.append("graph")
    return [{"item": k, "planned": fp_[k], "baseline": fb[k]} for k in keys if fp_[k] != fb[k]]


def format_rows(name: str, rows: Sequence[dict[str, Any]]) -> str:
    bad = [r for r in rows if not r["ok"]]
    lines = [f"[{name}] 동결 항목 {len(rows) - len(bad)}/{len(rows)} 통과"]
    for r in rows:
        val = json.dumps(r["value"], ensure_ascii=False, default=str)
        lines.append(f"  {'OK ' if r['ok'] else 'NG '} {r['item']}: {val[:110]}{'…' if len(val) > 110 else ''}" + (f"  ← {r['why']}" if r["why"] else ""))
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("results", nargs="+", type=Path, help="eval_runner 결과 JSON")
    ap.add_argument("--dict-version", default=EXPECTED_DICT_VERSION, help="기대하는 사전 판(빈 문자열이면 값만 있으면 통과)")
    ap.add_argument("--require-judge", action="store_true", help="judge 모델·루브릭·judge 프롬프트 sha256·Ragas 버전을 필수로 본다")
    ap.add_argument("--no-manifest", action="store_true", help="세트 해시와 manifest 일치를 필수로 보지 않는다(합성 세트 점검용)")
    ap.add_argument("--same", action="store_true", help="여러 결과가 같은 동결 값으로 잰 것인지도 본다(조건이 정하는 항목 제외)")
    a = ap.parse_args(argv)
    loaded = [(p, json.loads(p.read_text(encoding="utf-8"))) for p in a.results]
    failed = False
    for p, res in loaded:
        rows = check_result(res, dict_version=a.dict_version or None, require_judge=a.require_judge, require_manifest_match=not a.no_manifest)
        print(format_rows(p.name, rows))
        failed |= any(not r["ok"] for r in rows)
    if a.same and len(loaded) > 1:
        base_p, base = loaded[0]
        for p, res in loaded[1:]:
            diff = same_freeze(base, res)
            print(f"[{base_p.name} 대 {p.name}] 동결 값 {'같음' if not diff else '다름: ' + ', '.join(d['item'] for d in diff)}")
            failed |= bool(diff)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
