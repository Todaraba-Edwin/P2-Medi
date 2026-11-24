"""FE-17 U-30-1(요약 문장 중복, 2026-11-24) 개발 보조 문항 코드 채점. LLM·judge·네트워크·원격 DB 호출 0.

개발셋 150문항(`dev_set.jsonl`)·`manifest.json`·시험셋(`*.SEALED.jsonl`)·안전 핵심 40문항은 건드리지 않고, 보조 문항 `eval_set/dev_aux_u30.jsonl`(manifest 미등록)을
코드로 채점한다. **평가 러너·지표 정의 코드(`eval_runner.py`·`eval_metrics.py`)는 고치지 않는** 별도 모듈이다(9장 지표·judge와 무관한 개발 확인용).

- 관측: 실제 Router·그래프·도구 본문에 **가짜 모델**을 붙인다. 가짜 도구 선택 모델은 Router가 정리한 약만 `check_contraindications`로 부르고, 가짜 요약 모델은 문항의
  `fake_sentences`(모델이 중복을 낸 것처럼 만든 문장)를 그대로 돌려준다. 그래서 이 채점은 **문장 중복 제거 코드 경로**를 보며 실제 모델이 중복을 얼마나 내는지는 보지 못한다.
- 채점(문항마다 `Check` 목록, judge 없음): `not_listed_sentences_le_max`(요약에 남은 "금기 목록에 없음" 계열 문장 수 ≤ 기준), `n_dropped`(지운 문장 수),
  `keeps_classes`(약사 확인·안전 단정 금지 뜻은 지운 뒤에도 남음), `no_new_text`(요약 문장이 가짜 모델 문장의 부분집합), `summary_safe`(용량 숫자·가부·권유 없음, 기존 `unsafe_reason`).
- 스위치 `summary_dedupe`를 끈 구성은 이전 동작(중복 문장이 그대로 나옴)을 재현해야 한다.

사용(저장소 루트, 메인 venv):
    backend/.venv/bin/python evaluation/dev_aux_u30.py [--dict-path data/mock/dict/drug_dict.json] [--out-md OUT.md]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT / "backend"), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sealed_guard  # noqa: E402

AUX_PATH = ROOT / "evaluation" / "eval_set" / "dev_aux_u30.jsonl"
SCHEMA = "dev-aux-u30@v1"
KINDS = ("dup_pair", "nodup_pair", "three_drugs", "text_only")
DEFAULT_DICT_PATHS = (ROOT / "data" / "mock" / "dict" / "drug_dict.json", Path("/Users/edwin/develop/P2-Medi/data/mock/dict/drug_dict.json"))


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str = ""


def load_aux(path: str | Path = AUX_PATH) -> list[dict[str, Any]]:
    """보조 문항을 읽는다. 시험셋(`*.SEALED.jsonl`)은 열기 전에 거절한다. 형식이 틀리면 `ValueError`."""
    sealed_guard.check_access(path, allow_sealed=False)
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    if len({r.get("id") for r in rows}) != len(rows):
        raise ValueError("문항 id 중복")
    for r in rows:
        ok = (r.get("set") == "dev_aux_u30" and r.get("kind") in KINDS and r.get("question") and isinstance(r.get("expected"), dict)
              and isinstance(r.get("fake_sentences"), list) and r["fake_sentences"] and isinstance(r.get("n_drugs"), int))
        if not ok:
            raise ValueError(f"보조 문항 형식 오류: {r.get('id')}")
    return rows


def find_dict_path(explicit: str | Path | None = None) -> Path:
    for p in ([Path(explicit)] if explicit else list(DEFAULT_DICT_PATHS)):
        if p.exists():
            return p
    raise FileNotFoundError("사전 파일(drug_dict.json)을 찾지 못했다: --dict-path로 알려 준다")


def _empty_conn() -> sqlite3.Connection:
    from app.db import loaders

    c = sqlite3.connect(":memory:")
    loaders.apply_schema(c)
    return c


def _sentences(row: Mapping[str, Any]) -> list[Any]:
    from app.agent.answer_schema import Sentence

    return [Sentence(text=s["text"], evidence_ids=list(s.get("evidence_ids") or []), claim_type=s["claim_type"]) for s in row["fake_sentences"]]


# --------------------------------------------------------------------------- 관측
def observe_text_only(row: Mapping[str, Any], *, dedupe: bool = True) -> dict[str, Any]:
    """그래프 없이 문장 목록에 직접 적용한다(사용자 사례 원문 같은 사전 밖 약 이름 문항)."""
    from app.agent.summary_dedupe import dedupe_sentences

    sents = _sentences(row)
    res = dedupe_sentences(sents, n_drugs=row["n_drugs"]) if dedupe else None
    kept = res.sentences if res else sents
    return {"summary": " ".join(s.text for s in kept), "n_dropped": len(res.dropped) if res else 0, "n_entities": row["n_drugs"]}


def observe_graph(row: Mapping[str, Any], dd: Any, *, dedupe: bool = True) -> dict[str, Any]:
    """질문 하나를 실제 그래프로 끝까지 돌린다(LLM 0). 도구 선택 모델은 Router가 RESOLVED로 정리한 약만 부른다."""
    from langchain_core.messages import AIMessage

    from app.agent.graph.build import build_graph, run_question
    from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call
    from app.agent.graph.wiring import build_deps, build_tool_context
    from app.agent.router import route_input

    pre = route_input(row["question"], dd, None)
    drugs = [{"item_seq": e.item_seq} for e in pre.entities if e.status == "RESOLVED" and e.item_seq]
    script = [AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": drugs}, "chk")]), AIMessage("조회를 마쳤다")] if drugs else [AIMessage("조회 없음")]
    ctx = build_tool_context(dd, mode="eval", api_enabled=False, conn_factory=_empty_conn)
    draft = {"sentences": [s.model_dump() for s in _sentences(row)]}
    deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=script), summary_model=ScriptedSummary([draft]), system_prompt="보조 문항 채점용",
                      summary_dedupe=dedupe)
    state = run_question(build_graph(deps), row["question"])
    ev = [e for e in state.get("events") or [] if e.get("event") == "SUMMARY_DEDUPE"]
    return {"summary": (state.get("answer") or {}).get("summary") or "", "n_dropped": sum(int(e.get("dropped") or 0) for e in ev),
            "n_entities": len(state.get("entities") or []), "end_reason": state.get("end_reason")}


# --------------------------------------------------------------------------- 채점
def score(row: Mapping[str, Any], obs: Mapping[str, Any]) -> list[Check]:
    from app.agent.sentence_filter import unsafe_reason
    from app.agent.summary_dedupe import NOT_LISTED, classes_of

    x, summary = row["expected"], obs["summary"]
    fake_texts = [s["text"] for s in row["fake_sentences"]]
    kept = [t for t in fake_texts if t in summary]            # 가짜 모델 문장 중 요약에 남은 것(글자 그대로 들어가므로 부분 문자열 일치)
    n_nl = sum(NOT_LISTED in classes_of(t) for t in kept)
    before = set().union(*(classes_of(t) for t in fake_texts))
    after = set().union(*(classes_of(t) for t in kept)) if kept else set()
    leftover = summary
    for t in kept:
        leftover = leftover.replace(t, "")
    return [
        Check("entities_match_n_drugs", obs["n_entities"] == row["n_drugs"], f"{obs['n_entities']}/{row['n_drugs']}"),
        Check("not_listed_sentences_le_max", n_nl <= x["max_not_listed_sentences"], f"{n_nl}/{x['max_not_listed_sentences']}"),
        Check("n_dropped", obs["n_dropped"] == x["n_dropped"], f"{obs['n_dropped']}/{x['n_dropped']}"),
        Check("keeps_classes", set(x["keep_classes"]) <= after and after == before, f"before={sorted(before)} after={sorted(after)}"),
        Check("no_new_text", not leftover.strip(), f"남는 글자 {len(leftover.strip())}자"),
        Check("summary_safe", unsafe_reason(summary) is None, str(unsafe_reason(summary))),
    ]


def score_row(row: Mapping[str, Any], dd: Any | None, *, dedupe: bool = True) -> list[Check]:
    obs = observe_text_only(row, dedupe=dedupe) if row["kind"] == "text_only" else observe_graph(row, dd, dedupe=dedupe)
    return score(row, obs)


def run_all(rows: list[dict[str, Any]], dd: Any | None) -> dict[str, Any]:
    """`summary_dedupe` 켬/끔으로 모든 문항을 채점해 문항별·검사별 통과 수를 모은다. 끔은 중복이 있는 문항에서 일부 검사가 통과하지 못하는 것이 정상이다(이전 동작)."""
    report: dict[str, Any] = {"schema": SCHEMA, "n_rows": len(rows), "configs": {}}
    for name, dedupe in (("dedupe_on", True), ("dedupe_off", False)):
        per_row = {r["id"]: [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in score_row(r, dd, dedupe=dedupe)] for r in rows}
        by_check: dict[str, list[int]] = {}
        for cs in per_row.values():
            for c in cs:
                k = by_check.setdefault(c["name"], [0, 0])
                k[0] += bool(c["passed"])
                k[1] += 1
        report["configs"][name] = {"rows": per_row, "checks": {k: {"k": v[0], "n": v[1]} for k, v in by_check.items()},
                                   "rows_all_pass": sum(all(c["passed"] for c in cs) for cs in per_row.values()), "n_rows": len(per_row)}
    return report


def render_md(rep: Mapping[str, Any], dict_version: str) -> str:
    lines = ["# FE-17 U-30-1 개발 보조 문항 코드 채점 (dev_aux_u30)", "",
             f"- 스키마 `{rep['schema']}`, 문항 {rep['n_rows']}개, 사전 `{dict_version}`, LLM·judge 호출 0(가짜 모델 코드 경로)", "",
             "| 구성 | 문항 모두 통과(k/n) | 통과하지 못한 검사 |", "|---|---|---|"]
    for name, c in rep["configs"].items():
        failing = ", ".join(f"{k} {v['k']}/{v['n']}" for k, v in c["checks"].items() if v["k"] != v["n"]) or "모두 통과"
        lines.append(f"| {name} | {c['rows_all_pass']}/{c['n_rows']} | {failing} |")
    lines += ["", "소표본이라 유의성을 주장하지 않는다(PJ2-RFP.md 9.1절). 이 채점은 코드 경로 확인이며 실제 모델이 중복을 얼마나 내는지는 보지 못한다."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--aux", default=str(AUX_PATH))
    ap.add_argument("--dict-path")
    ap.add_argument("--out-md")
    a = ap.parse_args(argv)
    from app.tools.drug_dict import DrugDict

    dd = DrugDict.load(find_dict_path(a.dict_path))
    rep = run_all(load_aux(a.aux), dd)
    md = render_md(rep, str(dd.version))
    print(md)
    if a.out_md:
        Path(a.out_md).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out_md).write_text(md, encoding="utf-8")
    on = rep["configs"]["dedupe_on"]
    return 0 if on["rows_all_pass"] == on["n_rows"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
