"""W3-2 서버 개선 후보(AG-13-41·45·46) 개발 보조 문항 코드 채점(2026-11-24). LLM·judge·네트워크·원격 DB 호출 0.

9.8절 "개발셋 실패 사례 근거"를 채우려는 별도 보조 문항 `eval_set/dev_aux_w32.jsonl`(개발셋 150·`manifest.json`·시험셋·안전 핵심 40문항 불변, manifest 미등록)을
코드로 채점한다. **평가 러너·지표 정의 코드(`eval_runner.py`·`eval_metrics.py`)는 고치지 않고** import만 하지 않는 새 보조 모듈이다(9장 지표와 무관한 개발 확인용).

- 문항 종류 `kind`: `time_expression`(AG-13-41: 시각·횟수 표현이 약 이름으로 오인되는 사례), `control_unchanged`(보호 짝: 스위치를 켜도 Router 결과가 같아야 한다),
  `confirmed_selection`(AG-13-45·46: 되묻기에서 고른 약 `confirmed_item_seqs`가 든 서비스형 입력).
- 관측(`observe_*`)은 **실제 Router·실제 그래프·실제 도구 본문**에 가짜 모델(규칙대로 부르는 `compliant`, 비선택 후보를 섞는 `leaky`, 선택 쌍을 빼는 `skip`)을 붙여 만든다.
  판정 DB는 빈 SQLite(구조만), 공공 API 병기는 끔이다. 그래서 이 채점은 **코드 경로**(엔티티·인자·근거 항목·응답 칸)를 보며 실제 모델의 동작을 대신하지 않는다.
- 채점은 문항마다 `Check(name, passed, detail)` 목록이다. 정답은 문항 파일의 `expected`(코드가 산출·고정한 값)이고 judge를 쓰지 않는다.
- 요약 문장 안전 검사는 기존 코드를 그대로 쓴다: `sentence_filter.unsafe_reason`(= `DOSE_NUMBER`·`_DECISION_PATTERNS`·AG-13-40 출구 Sensor).

사용(저장소 루트, 메인 venv):
    backend/.venv/bin/python evaluation/dev_aux_w32.py [--dict-path data/mock/dict/drug_dict.json] [--out-md OUT.md] [--out-json OUT.json]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
for _p in (str(ROOT / "backend"), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sealed_guard  # noqa: E402

AUX_PATH = ROOT / "evaluation" / "eval_set" / "dev_aux_w32.jsonl"
SCHEMA = "dev-aux-w32@v1"
DEFAULT_DICT_PATHS = (ROOT / "data" / "mock" / "dict" / "drug_dict.json", Path("/Users/edwin/develop/P2-Medi/data/mock/dict/drug_dict.json"))
SWITCHES = ("router_time_noise", "redose_on_clarify", "identify_arg_check", "confine_confirmed_args", "summary_router_pairs",
            "merge_unconfirmed_lines", "display_name_fix")
ALL_OFF = {k: False for k in SWITCHES}
KINDS = ("time_expression", "control_unchanged", "confirmed_selection")
# 시각·횟수 표현이 도구 인자 약 이름 자리에 들어갔는지(코드 규칙, 일반화 정규식 + 레거시 시각·수량). `app.agent.nondrug_tokens`를 그대로 쓴다
FAKE_ANSWER = {"sentences": [{"text": "조회한 결과를 정리했어요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}]}


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str = ""


# --------------------------------------------------------------------------- 로드
def load_aux(path: str | Path = AUX_PATH) -> list[dict[str, Any]]:
    """보조 문항을 읽는다. 시험셋(`*.SEALED.jsonl`)은 열기 전에 거절한다. 형식이 틀리면 `ValueError`."""
    sealed_guard.check_access(path, allow_sealed=False)
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [r.get("id") for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError("문항 id 중복")
    for r in rows:
        if r.get("set") != "dev_aux_w32" or r.get("kind") not in KINDS or not r.get("question") or not isinstance(r.get("expected"), dict):
            raise ValueError(f"보조 문항 형식 오류: {r.get('id')}")
    return rows


def find_dict_path(explicit: str | Path | None = None) -> Path:
    for p in ([Path(explicit)] if explicit else list(DEFAULT_DICT_PATHS)):
        if p.exists():
            return p
    raise FileNotFoundError("사전 파일(drug_dict.json)을 찾지 못했다: --dict-path로 알려 준다")


def _graph_profile(profile: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not profile:
        return None
    out: dict[str, Any] = {}
    if profile.get("pregnant") is not None:
        out["pregnant"] = bool(profile["pregnant"])
    age = profile.get("age")
    if isinstance(age, dict) and age.get("value") is not None and age.get("unit") == "세":
        out["age_years"] = float(age["value"])
    return out or None


def _entities(res: Any) -> list[tuple[str, str, str | None]]:
    return [(e.raw, e.status, e.item_seq) for e in res.entities]


# --------------------------------------------------------------------------- 관측: Router 단독
def observe_router(row: Mapping[str, Any], dd: Any, *, time_noise: bool = True) -> dict[str, Any]:
    from app.agent import router as R

    res = R.route_input(row["question"], dd, _graph_profile(row.get("profile")), confirmed_item_seqs=row.get("confirmed_item_seqs"), time_noise=time_noise)
    return {"entities": _entities(res), "ambiguous": res.ambiguous, "clarify": res.clarify.model_dump() if res.clarify else None,
            "branch": res.branch_label, "redose_question": res.redose_question, "intake_question": res.intake_question, "dump": res.model_dump()}


# --------------------------------------------------------------------------- 관측: 그래프(가짜 모델)
def _empty_conn() -> sqlite3.Connection:
    from app.db import loaders

    c = sqlite3.connect(":memory:")
    loaders.apply_schema(c)
    return c


def _other_candidates(dd: Any, row: Mapping[str, Any], mine: set[str]) -> list[str]:
    """고른 약과 이름이 비슷한 **비선택 후보**의 품목기준코드(U-26: 같은 이름 조각을 사전에서 다시 찾으면 나오는 다른 제품)."""
    out: list[str] = []
    for pick in row.get("confirmed_item_seqs") or []:
        name = pick.get("input_name") if isinstance(pick, dict) else None
        if not name:
            continue
        cands = [c for c in dd.lookup_name(name, top_k=10).candidates if c.item_seq and c.item_seq not in mine and c.item_seq not in out]
        out.extend(c.item_seq for c in sorted(cands, key=lambda c: c.code_status != "linked") if c.item_seq not in out)  # 판정할 수 있는 후보가 먼저(S7 모양)
    return out


def _script(res_entities: list[dict[str, Any]], model: str, dd: Any, row: Mapping[str, Any]) -> list[Any]:
    """가짜 도구 선택 모델의 호출 순서(LLM 0).
    - `compliant`: Router가 정리한 약만(확정·정상 약은 `item_seq`로, 못 찾은 이름은 `identify_drug`) 부른다.
    - `leaky`: 위에 비선택 후보 하나를 판정 호출에 더 섞는다(U-26 S4 모양).
    - `skip`: 확정한 약 중 마지막 하나를 빼고 비선택 후보로 바꿔 부른다(U-26 S7 모양: 선택 쌍을 한 번도 조회하지 않음)."""
    from langchain_core.messages import AIMessage

    from app.agent.graph.fakes import tool_call

    msgs: list[Any] = []
    drugs: list[dict[str, Any]] = []
    for i, e in enumerate(res_entities):
        if e.get("status") == "RESOLVED" and e.get("item_seq"):
            drugs.append({"item_seq": e["item_seq"]})
        else:
            msgs.append(AIMessage("", tool_calls=[tool_call("identify_drug", {"name": str(e.get("raw"))}, f"id{i}")]))
    others = _other_candidates(dd, row, {d["item_seq"] for d in drugs})
    if model == "leaky" and drugs and others:
        drugs.append({"item_seq": others[0]})
    if model == "skip" and len(drugs) >= 2 and others:
        drugs = [*drugs[:-1], {"item_seq": others[0]}]
    if drugs:
        msgs.append(AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": drugs, "pregnancy": True}, "chk")]))
    msgs.append(AIMessage("조회를 마쳤다"))
    return msgs


def observe_graph(row: Mapping[str, Any], dd: Any, *, switches: Mapping[str, bool] | None = None, model: str = "compliant") -> dict[str, Any]:
    """질문 하나를 실제 그래프로 끝까지 돌려 채점에 필요한 값만 모은다(LLM 0, 가짜 모델)."""
    from langchain_core.messages import AIMessage

    from app.agent.graph.build import build_graph, run_question
    from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel
    from app.agent.graph.wiring import build_deps, build_tool_context

    sw = dict(switches or {})
    pre = observe_router(row, dd, time_noise=sw.get("router_time_noise", True))
    ents = [e for e in pre["dump"]["entities"]]
    ctx = build_tool_context(dd, mode="eval", api_enabled=False, conn_factory=_empty_conn)
    tm = ScriptedToolModel(script=_script(ents, model, dd, row) if not pre["ambiguous"] else [AIMessage("조회 없음")])
    deps = build_deps(dd, ctx, tool_model=tm, summary_model=ScriptedSummary([FAKE_ANSWER]), system_prompt="보조 문항 채점용", **sw)
    state = run_question(build_graph(deps), row["question"], _graph_profile(row.get("profile")), row.get("confirmed_item_seqs"))
    calls = [tc for m in state.get("messages", []) for tc in (getattr(m, "tool_calls", None) or [])]
    return {"state": state, "tool_calls": calls, "router": pre}


# --------------------------------------------------------------------------- 채점
def _tool_name_args(calls: Iterable[Mapping[str, Any]]) -> list[str]:
    """도구 호출 인자에서 약 이름 자리 값(`identify_drug.name`·`drugs[].name`)."""
    out: list[str] = []
    for tc in calls:
        a = tc.get("args") or {}
        if tc.get("name") == "identify_drug" and isinstance(a.get("name"), str):
            out.append(a["name"])
        for d in a.get("drugs") or []:
            if isinstance(d, dict) and isinstance(d.get("name"), str):
                out.append(d["name"])
    return out


def _drug_keys(state: Mapping[str, Any]) -> set[str]:
    return {k for it in state.get("evidence") or [] if it.get("kind") != "identify" for k in it.get("drug_keys") or []}


def _unconfirmed_line_count(answer: Mapping[str, Any]) -> dict[str, int]:
    """약 키별 "확인 못 함" 화면 줄 수(응답 변환이 `line_groups`로 합친 뒤)."""
    group_first: dict[str, str] = {}
    for g in answer.get("line_groups") or []:
        ids = g.get("evidence_ids") or []
        for x in ids:
            group_first.setdefault(x, ids[0])
    lines: dict[str, set[str]] = {}
    for e in answer.get("entries") or []:
        if e.get("bucket") != "unconfirmed" or e.get("kind") in ("contra_pair", "dup_ingredient") or not e.get("evidence_id"):
            continue
        key = e.get("drug") or ""
        lines.setdefault(key, set()).add(group_first.get(e["evidence_id"], e["evidence_id"]))
    return {k: len(v) for k, v in lines.items()}


def score_time_expression(row: Mapping[str, Any], obs: Mapping[str, Any]) -> list[Check]:
    from app.agent import fixed_phrases as fp
    from app.agent.nondrug_tokens import is_non_drug_token

    x, st, r = row["expected"], obs["state"], obs["router"]
    resolved = [e for e in st.get("entities") or [] if e.get("status") == "RESOLVED"]
    bad_ents = [e for e in st.get("entities") or [] if e.get("status") != "RESOLVED"]
    checks = [
        Check("entities_resolved", sorted(e["item_seq"] for e in resolved) == sorted(x["resolved_item_seqs"]), f"{len(resolved)}/{len(x['resolved_item_seqs'])}"),
        Check("no_unresolved_entity", not bad_ents, f"{len(bad_ents)}건"),
        Check("n_entities", len(st.get("entities") or []) == x["n_entities"], str(len(st.get("entities") or []))),
        Check("ambiguous_false", st.get("ambiguous") is x["ambiguous"], str(st.get("ambiguous"))),
        Check("clarify_none", (st.get("clarify") is None) == (x["clarify"] is None), ""),
        Check("redose_question", r["redose_question"] is x["redose_question"], ""),
        Check("intake_question", r["intake_question"] is x["intake_question"], ""),
        Check("end_reason_not_clarify", st.get("end_reason") not in x["end_reason_not"], str(st.get("end_reason"))),
    ]
    if x.get("redose_notice"):
        checks.append(Check("redose_notice_fixed", (st.get("answer") or {}).get("redose_notice") == fp.REDOSE_NOTICE, ""))
    if x.get("no_time_token_in_tool_args"):
        names = [n for n in _tool_name_args(obs["tool_calls"]) if is_non_drug_token(n)]
        checks.append(Check("no_time_token_in_tool_args", not names, f"{len(names)}건"))
    checks.extend(_summary_checks(st))
    return checks


def _summary_checks(st: Mapping[str, Any]) -> list[Check]:
    from app.agent.sentence_filter import unsafe_reason

    a = st.get("answer") or {}
    texts = [t for t in (a.get("summary"), (a.get("result_summary") or {}).get("text")) if isinstance(t, str)]
    bad = [r for t in texts if (r := unsafe_reason(t))]
    return [Check("summary_no_dose_or_decision", not bad, ",".join(bad))]


def score_control(row: Mapping[str, Any], on: Mapping[str, Any], off: Mapping[str, Any]) -> list[Check]:
    return [Check("same_router_result_as_switch_off", on["dump"] == off["dump"], "")]


def score_confirmed(row: Mapping[str, Any], obs: Mapping[str, Any]) -> list[Check]:
    x, st = row["expected"], obs["state"]
    a = st.get("answer") or {}
    confirmed = set(x["confirmed_set"])
    resolved = {e["item_seq"] for e in st.get("entities") or [] if e.get("status") == "RESOLVED"}
    out_keys = {k for k in _drug_keys(st) if k.isdigit() and len(k) == 9 and k not in confirmed}
    checks = [
        Check("entities_resolved_confirmed_set", resolved == confirmed, f"{len(resolved & confirmed)}/{len(confirmed)}"),
        Check("n_entities", len(st.get("entities") or []) == x["n_entities"], str(len(st.get("entities") or []))),
        Check("ambiguous_false", st.get("ambiguous") is x["ambiguous"], ""),
        Check("clarify_none", (st.get("clarify") is None) == (x["clarify"] is None), ""),
        Check("no_out_of_set_items", len(out_keys) == x["out_of_set_items"], f"{len(out_keys)}건"),
    ]
    if x.get("no_false_zero_unchecked") and len(confirmed) == 2:
        # 선택 쌍(A·B)을 판정한 근거 항목(FOUND·목록에 없음)이 없는데 요약이 "확인하지 못한 짝 0건"이면 거짓 안심이다. 요약이 아예 없는 것은 안심을 지어내지 않으므로 통과
        judged = any(set(it.get("drug_keys") or []) == confirmed and it.get("status") in ("FOUND", "NOT_LISTED")
                     for it in st.get("evidence") or [] if it.get("kind") == "contra_pair")
        rs = a.get("result_summary")
        unchecked = (rs or {}).get("n_pairs_unchecked")
        checks.append(Check("no_false_zero_unchecked", judged or rs is None or (unchecked or 0) >= 1, f"judged={judged} unchecked={unchecked}"))
    mx = x.get("unconfirmed_lines_per_drug_max")
    if mx is not None:
        counts = _unconfirmed_line_count(a)
        checks.append(Check("unconfirmed_lines_per_drug", all(n <= mx for n in counts.values()), json.dumps(counts, ensure_ascii=False)))
    if x.get("summary_text_safe"):
        checks.extend(_summary_checks(st))
    return checks


def score_row(row: Mapping[str, Any], dd: Any, *, switches: Mapping[str, bool] | None = None, model: str = "compliant") -> list[Check]:
    """문항 하나를 관측하고 채점한다. `switches`는 `build_deps` 스위치(비우면 모두 켬)."""
    kind = row["kind"]
    if kind == "control_unchanged":
        on = observe_router(row, dd, time_noise=True)
        off = observe_router(row, dd, time_noise=False)
        return score_control(row, on, off)
    obs = observe_graph(row, dd, switches=switches, model=model)
    return score_time_expression(row, obs) if kind == "time_expression" else score_confirmed(row, obs)


def run_all(rows: list[dict[str, Any]], dd: Any) -> dict[str, Any]:
    """모두 켬 / 모두 끔 / (확정 문항) 비선택 후보를 섞는 가짜 모델 `leaky`로 켬·끔을 채점해 문항별·검사별 통과 수를 모은다."""
    report: dict[str, Any] = {"schema": SCHEMA, "n_rows": len(rows), "configs": {}}
    configs = {"all_on": ({}, "compliant"), "all_off": (ALL_OFF, "compliant"), "all_on_leaky": ({}, "leaky"), "all_off_leaky": (ALL_OFF, "leaky"),
               "all_on_skip": ({}, "skip"), "all_off_skip": (ALL_OFF, "skip")}
    for sw_name in SWITCHES:  # 한 번에 하나씩 켠 ablation(나머지는 모두 끔): 후보별 효과를 따로 본다
        configs[f"only_{sw_name}"] = ({**ALL_OFF, sw_name: True}, "compliant")
        configs[f"only_{sw_name}_skip"] = ({**ALL_OFF, sw_name: True}, "skip")
    for name, (sw, model) in configs.items():
        per_row: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            if model != "compliant" and r["kind"] != "confirmed_selection":
                continue
            per_row[r["id"]] = [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in score_row(r, dd, switches=sw, model=model)]
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
    lines = ["# W3-2 개발 보조 문항 코드 채점 (dev_aux_w32)", "", f"- 스키마 `{rep['schema']}`, 문항 {rep['n_rows']}개, 사전 `{dict_version}`, LLM·judge 호출 0(가짜 모델 코드 경로)", "",
             "| 구성 | 문항 모두 통과(k/n) | 검사 |", "|---|---|---|"]
    for name, c in rep["configs"].items():
        failing = ", ".join(f"{k} {v['k']}/{v['n']}" for k, v in c["checks"].items() if v["k"] != v["n"]) or "모두 통과"
        lines.append(f"| {name} | {c['rows_all_pass']}/{c['n_rows']} | 통과하지 못한 검사: {failing} |")
    lines += ["", "소표본이라 유의성을 주장하지 않는다(PJ2-RFP.md 9.1절). 이 채점은 코드 경로 확인이며 실제 모델 동작을 대신하지 않는다."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--aux", default=str(AUX_PATH))
    ap.add_argument("--dict-path")
    ap.add_argument("--out-md")
    ap.add_argument("--out-json")
    a = ap.parse_args(argv)
    from app.tools.drug_dict import DrugDict

    dd = DrugDict.load(find_dict_path(a.dict_path))
    rep = run_all(load_aux(a.aux), dd)
    md = render_md(rep, str(dd.version))
    print(md)
    if a.out_md:
        Path(a.out_md).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out_md).write_text(md, encoding="utf-8")
    if a.out_json:
        Path(a.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out_json).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
