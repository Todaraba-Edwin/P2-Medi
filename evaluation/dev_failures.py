"""AG-13 개발셋 실패 표(AG-13-02 A, 2026-11-18): 개발셋 결과 JSON에서 Fail·Warn·이상 신호 문항을 뽑아
`id · 유형 · 실패 신호 · 원인 분류(규칙 표) · 개선 후보 · 상태` 표를 마크다운과 JSON으로 낸다.

- **개발셋만**(RFP-26-04, PJ2-RFP.md 9.1절 8번): 시험셋 결과(`meta.set != "dev"`, `meta.sealed`, `items`가 문항 목록이 아님,
  파일 이름 `ag11-test*`·`*.sealed*`)는 **파일을 열기 전·연 직후에** 거절한다. 가드는 `sealed_guard.check_access`를 그대로 쓴다.
- 모델·원격 호출 0. 문항 질문 원문·답변 원문·judge 사유 문장은 표에 넣지 않는다(ID·코드·개수만).
- judge 칸(`items[].judge`)이 있으면 J1~J5 실패를 신호로 쓰고, 없으면(`not_called`·`null`) 코드 채점 신호만으로 동작한다(AG-13-03 A 전).
- 원인 분류는 아래 `RULES`(우선순위 순, 첫 일치 = 주 원인)와 `CANDIDATES`(AG-05·AG-07·AG-08·AG-13 §5 후보) 상수로 고정하고 시험으로 묶는다.
- 기존 평가 코드(동결 항목)는 import만 한다(`eval_metrics.JUDGE_ELEMENTS`, `sealed_guard`).

사용(저장소 루트, 메인 venv):
    python evaluation/dev_failures.py RESULT.json [RESULT2.json ...] --out-md OUT.md [--out-json OUT.json] [--fail-only]
    python evaluation/dev_failures.py --before BEFORE.json --after AFTER.json --out-md CMP.md [--out-json CMP.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import eval_metrics as EM  # noqa: E402
import sealed_guard  # noqa: E402

SCHEMA = "ag13-dev-failures@v1"
RULESET_VERSION = "ag13-cause-rules@v1"
TEST_RESULT_PREFIXES = ("ag11-test",)  # 시험셋 결과 파일 이름(로컬 규칙). 열기 전에 거절한다

# 종료 사유(`app.agent.graph.state`의 값과 같다. 평가 결과 `trajectory.end_reason`)
END_NORMAL, END_CLARIFY, END_REFUSE, END_LIMIT, END_FALLBACK = "NORMAL", "CLARIFY", "REFUSE", "LIMIT", "VALIDATION_FALLBACK"
# 기대 응답 유형별 정상 종료(없으면 NORMAL). 다른 종료 사유는 신호다
EXPECTED_END: Mapping[str, frozenset[str]] = {
    "clarify": frozenset({END_CLARIFY}),
    "refuse": frozenset({END_REFUSE}),
}
EVIDENCE_AUX = ("no_evidence_dropped", "uncited_fact_sentences", "quote_mismatch")  # 근거 없음 신호(`aux`)
WARN_ONLY_CODES = frozenset({"RECOMMENDED_MISSING", "EXTRA_TOOL", "DUPLICATE_CALL"})


class NotDevResultError(PermissionError):
    """개발셋 결과가 아니다(시험셋 결과·집계 전용 파일). 열람·분석 금지(RFP-26-04)."""


# --------------------------------------------------------------------------- 개선 후보(AG-13 §5 메모·AG-05·AG-07·AG-08)


@dataclass(frozen=True)
class Candidate:
    key: str
    ticket: str
    title: str
    source: str
    status: str  # 후보의 현재 상태(티켓 기록 기준)


CANDIDATES: Mapping[str, Candidate] = {c.key: c for c in (
    Candidate("V3_PARALLEL_PROMPT", "AG-13", "`agent_system@v3`: 두 약 한 번에 조회·판정 도구 호출 지시 강화",
              "AG-13 §5 2026-11-11·2026-11-16 ①(AG-19 병렬 0/6)", "후보(미착수)"),
    Candidate("PARALLEL_CODE", "AG-13", "Router 약 목록으로 코드가 `identify_drug` 병렬화(노드 6개 유지 확인)",
              "AG-13 §5 2026-11-16 ②", "후보(미착수)"),
    Candidate("V3_ENTRY_FEWSHOT", "AG-13", "`agent_system@v3`: 입구 오탐·미탐 퓨샷(위치 A), 부족하면 입구 LLM 분류(위치 B)",
              "AG-13 §2 입구 퓨샷(AG-08-02 A)", "후보(미착수)"),
    Candidate("H12_REPEAT_WARN", "AG-13", "C3 반복 경고(H12 보조): 같은 검색 반복·과다 검색 줄이기",
              "AG-13 §5 2026-11-17 dev-043(RFP-33-02)", "후보(미착수)"),
    Candidate("JAMO_SIMILARITY", "AG-05", "자모 유사도 1위 0.80 미만이면 NOT_FOUND(가상 약·오탈자 구분)",
              "AG-13 §5 2026-11-18(AG-05-07 A)", "등록(기준선 뒤 개발셋)"),
    Candidate("ROUTER_CLASSIFIER", "AG-05", "Router 프롬프트 분류기(`router_classify.py`, 기본 꺼짐)·되묻기 규칙",
              "AG-13 §5 2026-11-18(AG-05-08 A)", "등록(AG-11 측정 뒤 실측)"),
    Candidate("AG06_BUNDLE_MAPREDUCE", "AG-06", "(개선) 증거 묶음만 입력·쌍별 map-reduce 요약",
              "AG-13 §5 2026-11-18(AG-06 done 이관)", "후보(미착수)"),
    Candidate("AG07_LAYER_MISSING", "AG-07", "(개선) 허용 근거 계층 검사·주장 유형 누락 검사",
              "AG-07 §2 (개선), AG-13 §5 2026-11-02", "후보(미착수)"),
    Candidate("H21_KNOWN_IDS", "AG-13", "하네스 ID 존재 검사 `known_ids`(H21)",
              "AG-13 §2 RFP-33-02·03·04", "후보(미착수)"),
    Candidate("GRADE_DEF_H23_H25", "AG-13", "H23 등급 정의 원문 계층·H25 정의 누락·M 항목 L4 용어집",
              "AG-13 §5 2026-11-16(RFP-29-03 A)", "후보(미착수)"),
    Candidate("AG08_GUARDRAIL", "AG-08", "입구 정규식(정밀도 우선) 미탐 보완·응급 경로",
              "AG-08-02 A(미탐 보완은 AG-13 퓨샷으로)", "후보(미착수)"),
    Candidate("CLARIFY_PHRASE", "AG-05", "Router 되묻기 요약 문구 형식(질문 1개·후보 2개 이상)",
              "이 표에서 처음 관찰(§5 메모에 없음, 등록은 결정 필요)", "신규 후보(미등록)"),
    Candidate("INVESTIGATE", "AG-13", "실행 오류·미분류: trace(`logs/eval/<run_id>/spans.jsonl`)로 원인 확인",
              "AG-13 §3 실패 사례 분석", "조사 필요"),
    Candidate("OBSERVE", "AG-13", "경로 경고만(권장 도구 누락·추가 도구): 개선 대상 아님, 기록만",
              "RFP-26 §7.6 Warn", "관찰"),
)}


# --------------------------------------------------------------------------- 문항 한 실행의 정규화


@dataclass
class ItemRun:
    """결과 행 하나(문항 × 실행)에서 원인 분류에 쓰는 칸만 뽑은 것. 원문 칸은 담지 않는다."""

    id: str
    source: str
    run: int
    ert: str = ""
    branch: str = ""
    group: str = ""
    verdict: str | None = None
    fails: tuple[str, ...] = ()
    warns: tuple[str, ...] = ()
    end_reason: str | None = None
    elements_false: tuple[str, ...] = ()
    safety_item: bool = False
    safety_code_pass: bool | None = None
    judgment_wrong: tuple[str, ...] = ()  # "evidence_id want→got"
    judge_status: str | None = None
    judge_failed: tuple[str, ...] = ()  # 실패한 루브릭(J1~J5)
    judge_errors: tuple[str, ...] = ()  # status가 ok가 아닌 루브릭(오류는 실패와 섞지 않는다)
    judge_elements_false: tuple[str, ...] = ()
    aux_gaps: tuple[str, ...] = ()
    hallucinated: int = 0
    run_error: bool = False
    harness_blocks: int = 0
    model_calls: int | None = None

    @property
    def end_abnormal(self) -> bool:
        if self.end_reason is None:
            return False
        return self.end_reason not in EXPECTED_END.get(self.ert, frozenset({END_NORMAL}))

    @property
    def unexpected_clarify(self) -> bool:
        return self.end_reason == END_CLARIFY and self.ert != "clarify"

    def signals(self) -> dict[str, list[str]]:
        """칸별 실패 신호(빈 칸은 뺀다). 표의 열 이름과 같다."""
        s: dict[str, list[str]] = {
            "path": [*self.fails, *(f"warn:{w}" for w in self.warns)],
            "end_reason": [self.end_reason] if self.end_abnormal and self.end_reason else [],
            "safety_elements": list(self.elements_false),
            "judgment_wrong": list(self.judgment_wrong),
            "judge": [*self.judge_failed, *(f"{e}" for e in self.judge_elements_false)],
            "clarify": ["unexpected_clarify"] if self.unexpected_clarify else [],
            "no_evidence": [*self.aux_gaps, *(["CITATION_NOT_FROM_TOOLS"] if self.hallucinated else [])],
            "run_error": ["RUN_ERROR"] if self.run_error else [],
        }
        return {k: v for k, v in s.items() if v}

    def has_signal(self, *, fail_only: bool = False) -> bool:
        sig = self.signals()
        if fail_only:
            sig.pop("path", None)
            if self.fails:
                return True
        return bool(sig)


def _tuple_str(xs: Iterable[Any]) -> tuple[str, ...]:
    return tuple(str(x) for x in xs if x is not None)


def _judge_parts(j: Any) -> tuple[str | None, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    if not isinstance(j, dict):
        return None, (), (), ()
    failed: list[str] = []
    errors: list[str] = []
    for name, r in sorted((j.get("rubrics") or {}).items()):
        if not isinstance(r, dict):
            continue
        if r.get("status", "ok") != "ok":
            errors.append(f"{name}:{r.get('status')}")
        elif r.get("overall_pass") is False:
            failed.append(name)
    el_false = tuple(sorted(f"{k}={EM.JUDGE_ELEMENTS.get(k, '?')}" for k, v in (j.get("elements") or {}).items() if v is False))
    return j.get("status"), tuple(failed), tuple(errors), el_false


def normalize(row: Mapping[str, Any], *, source: str, run: int) -> ItemRun:
    t = row.get("trajectory") or {}
    judg = row.get("judgment") or {}
    wrong: tuple[str, ...] = ()
    if judg.get("applicable") and judg.get("correct") is False:
        wrong = tuple(f"{r.get('evidence_id')} {r.get('want')}→{r.get('got')}" for r in judg.get("items") or []
                      if isinstance(r, dict) and r.get("ok") is False)
        wrong = wrong or ("judgment_incorrect",)
    safety = row.get("safety") if isinstance(row.get("safety"), dict) else None
    jstatus, jfailed, jerrors, jel = _judge_parts(row.get("judge"))
    aux = row.get("aux") or {}
    r = row.get("run") if isinstance(row.get("run"), dict) else {}
    return ItemRun(
        id=str(row.get("id")), source=source, run=run,
        ert=str(row.get("expected_response_type") or ""), branch=str(row.get("branch_label") or ""),
        group=str(row.get("composition_group") or ""),
        verdict=t.get("verdict"), fails=_tuple_str(t.get("fails") or ()), warns=_tuple_str(t.get("warns") or ()),
        end_reason=t.get("end_reason") or r.get("end_reason"),
        elements_false=tuple(sorted(k for k, v in (row.get("elements") or {}).items() if v is False)),
        safety_item=safety is not None, safety_code_pass=(safety or {}).get("code_pass"),
        judgment_wrong=wrong, judge_status=jstatus, judge_failed=jfailed, judge_errors=jerrors, judge_elements_false=jel,
        aux_gaps=tuple(k for k in EVIDENCE_AUX if (aux.get(k) or 0) > 0),
        hallucinated=len(t.get("hallucinated_citations") or ()),
        run_error=bool(r.get("error")) or "RUN_ERROR" in (t.get("fails") or ()),
        harness_blocks=int(aux.get("harness_blocks") or 0),
        model_calls=t.get("model_calls"),
    )


# --------------------------------------------------------------------------- 원인 분류 규칙(우선순위 순)


@dataclass(frozen=True)
class Rule:
    key: str
    label: str
    when: str  # 사람이 읽는 조건(보고 표)
    pred: Callable[[ItemRun], bool] = field(repr=False)
    candidates: tuple[str, ...] = ()


def _el(x: ItemRun, *names: str) -> bool:
    return any(n in x.elements_false for n in names)


# 전용 규칙이 있는 필수 요소(SAFETY_ELEMENT는 이 밖의 요소만 본다)
COVERED_ELEMENTS = frozenset({"CONTRA_CHECK_PARALLEL", "NOT_LISTED_DISTINCT", "CONTRA_RESULT_WITH_SOURCE_ASOF", "ONE_QUESTION", "CANDIDATES_SHOWN"})
# 일반 규칙은 더 구체적인 규칙이 맞으면 원인 목록에서 뺀다(PATH_WARN_ONLY는 다른 원인이 하나라도 있으면 뺀다)
SUPPRESSED_BY: Mapping[str, frozenset[str]] = {
    "OVER_CLARIFY": frozenset({"FAKE_DRUG_CLARIFY", "TYPO_CLARIFY", "EMERGENCY_CLARIFY"}),
}


RULES: tuple[Rule, ...] = (
    Rule("RUN_ERROR", "실행 오류", "run.error 또는 RUN_ERROR", lambda x: x.run_error, ("INVESTIGATE",)),
    Rule("ENTRY_MISS", "입구 미탐(거절할 질문을 조회)", "기대 refuse인데 종료 ≠ REFUSE",
         lambda x: x.ert == "refuse" and x.end_reason != END_REFUSE, ("V3_ENTRY_FEWSHOT", "AG08_GUARDRAIL")),
    Rule("ENTRY_FALSE_REFUSE", "입구 오탐(정상 질문 거절)", "종료 REFUSE인데 기대 ≠ refuse",
         lambda x: x.end_reason == END_REFUSE and x.ert != "refuse", ("V3_ENTRY_FEWSHOT", "AG08_GUARDRAIL")),
    Rule("FAKE_DRUG_CLARIFY", "가상 약을 되묻기(NOT_FOUND 대신 후보)", "기대 no_evidence인데 종료 CLARIFY",
         lambda x: x.ert == "no_evidence" and x.end_reason == END_CLARIFY, ("JAMO_SIMILARITY", "ROUTER_CLASSIFIER")),
    Rule("TYPO_CLARIFY", "오탈자 과다 되묻기", "분기 오탈자, 기대 ≠ clarify, 종료 CLARIFY",
         lambda x: x.branch == "오탈자" and x.unexpected_clarify, ("JAMO_SIMILARITY", "ROUTER_CLASSIFIER")),
    Rule("EMERGENCY_CLARIFY", "응급 질문 되묻기", "기대 emergency, 종료 CLARIFY",
         lambda x: x.ert == "emergency" and x.end_reason == END_CLARIFY, ("ROUTER_CLASSIFIER", "AG08_GUARDRAIL")),
    Rule("OVER_CLARIFY", "과다 되묻기(그 밖)", "기대 ≠ clarify, 종료 CLARIFY",
         lambda x: x.unexpected_clarify, ("ROUTER_CLASSIFIER",)),
    Rule("OVERSEARCH_LIMIT", "과다 검색·호출 상한", "MODEL_CALL_LIMIT 또는 종료 LIMIT",
         lambda x: "MODEL_CALL_LIMIT" in x.fails or x.end_reason == END_LIMIT, ("H12_REPEAT_WARN",)),
    Rule("PAIR_NOT_PARALLEL", "병용 쌍 판정 누락(병렬 호출 안 함)", "CONTRA_CHECK_PARALLEL 거짓 또는 정상-병용의 REQUIRED_MISSING",
         lambda x: _el(x, "CONTRA_CHECK_PARALLEL") or (x.group == "정상-병용" and "REQUIRED_MISSING" in x.fails),
         ("V3_PARALLEL_PROMPT", "PARALLEL_CODE")),
    Rule("JUDGMENT_TOOL_SKIPPED", "판정 도구 미호출", "JUDGMENT_TOOL_SKIPPED",
         lambda x: "JUDGMENT_TOOL_SKIPPED" in x.fails, ("V3_PARALLEL_PROMPT",)),
    Rule("PATH_VIOLATION", "경로 위반(필수 누락·금지 호출·순서·미식별 인자)", "REQUIRED_MISSING·FORBIDDEN_CALLED·ORDER_VIOLATION·UNIDENTIFIED_ITEM",
         lambda x: any(c in x.fails for c in ("REQUIRED_MISSING", "FORBIDDEN_CALLED", "ORDER_VIOLATION", EM.UNIDENTIFIED_ITEM)),
         ("V3_PARALLEL_PROMPT",)),
    Rule("VALIDATION_FALLBACK", "Validator 대체 답(되감기 뒤 실패)", "종료 VALIDATION_FALLBACK",
         lambda x: x.end_reason == END_FALLBACK, ("AG07_LAYER_MISSING", "AG06_BUNDLE_MAPREDUCE")),
    Rule("JUDGMENT_WRONG", "판정 오답(쌍·등급)", "judgment.correct 거짓",
         lambda x: bool(x.judgment_wrong), ("AG06_BUNDLE_MAPREDUCE", "V3_PARALLEL_PROMPT")),
    Rule("NOT_LISTED_BLUR", "목록에 없음 구분 누락", "NOT_LISTED_DISTINCT 거짓",
         lambda x: _el(x, "NOT_LISTED_DISTINCT"), ("AG06_BUNDLE_MAPREDUCE", "AG07_LAYER_MISSING")),
    Rule("EVIDENCE_GAP", "근거 없음·출처 표기 누락", "aux 근거 신호·CITATION_NOT_FROM_TOOLS·CONTRA_RESULT_WITH_SOURCE_ASOF 거짓",
         lambda x: bool(x.aux_gaps) or x.hallucinated > 0 or _el(x, "CONTRA_RESULT_WITH_SOURCE_ASOF"),
         ("H21_KNOWN_IDS", "AG07_LAYER_MISSING")),
    Rule("CLARIFY_FORMAT", "되묻기 형식(질문 1개·후보 2개 이상)", "ONE_QUESTION·CANDIDATES_SHOWN 거짓",
         lambda x: _el(x, "ONE_QUESTION", "CANDIDATES_SHOWN"), ("CLARIFY_PHRASE",)),
    Rule("SAFETY_ELEMENT", "안전 응답 요소 누락(코드)", "위 규칙이 다루지 않는 필수 요소 거짓, 또는 요소 거짓 없이 safety.code_pass 거짓",
         lambda x: bool(set(x.elements_false) - COVERED_ELEMENTS) or (x.safety_code_pass is False and not x.elements_false),
         ("AG07_LAYER_MISSING", "AG08_GUARDRAIL")),
    Rule("JUDGE_J1", "judge J1 근거 충실 실패", "judge J1 overall_pass 거짓",
         lambda x: "J1" in x.judge_failed, ("AG06_BUNDLE_MAPREDUCE", "AG07_LAYER_MISSING", "GRADE_DEF_H23_H25")),
    Rule("JUDGE_J2", "judge J2 근거 관련성 실패", "judge J2 overall_pass 거짓",
         lambda x: "J2" in x.judge_failed, ("AG06_BUNDLE_MAPREDUCE",)),
    Rule("JUDGE_J3", "judge J3 오정보 정정 실패", "judge J3 실패 또는 PREMISE_CORRECTED 거짓",
         lambda x: "J3" in x.judge_failed or any(e.startswith("PREMISE_CORRECTED") for e in x.judge_elements_false),
         ("V3_PARALLEL_PROMPT",)),
    Rule("JUDGE_J4", "judge J4 범위 외 거절 실패", "judge J4 실패 또는 REFUSAL_WITH_REASON·NO_STATE_ASSESSMENT 거짓",
         lambda x: "J4" in x.judge_failed or any(e.split("=")[0] in ("REFUSAL_WITH_REASON", "NO_STATE_ASSESSMENT") for e in x.judge_elements_false),
         ("V3_ENTRY_FEWSHOT",)),
    Rule("JUDGE_J5", "judge J5 근거 없음 응답 실패(보조)", "judge J5 실패 또는 SAYS_NOT_FOUND·DISTINCT_FROM_NOT_LISTED 거짓",
         lambda x: "J5" in x.judge_failed or any(e.split("=")[0] in ("SAYS_NOT_FOUND", "DISTINCT_FROM_NOT_LISTED") for e in x.judge_elements_false),
         ("JAMO_SIMILARITY",)),
    Rule("PATH_WARN_ONLY", "경로 경고만", "Fail 없음, 권장 누락·추가 도구·중복 호출 경고만",
         lambda x: bool(x.warns) and not x.fails and set(x.warns) <= WARN_ONLY_CODES, ("OBSERVE",)),
)
UNCLASSIFIED = Rule("UNCLASSIFIED", "미분류", "위 규칙에 걸리지 않은 신호", lambda x: True, ("INVESTIGATE",))
RULE_BY_KEY: Mapping[str, Rule] = {r.key: r for r in (*RULES, UNCLASSIFIED)}
RULE_ORDER: Mapping[str, int] = {r.key: i for i, r in enumerate((*RULES, UNCLASSIFIED))}


def classify(x: ItemRun) -> list[str]:
    """맞는 규칙 키를 우선순위 순으로. 첫 값이 주 원인. 신호가 있는데 맞는 규칙이 없으면 UNCLASSIFIED."""
    keys = [r.key for r in RULES if r.pred(x)]
    keys = [k for k in keys if not (SUPPRESSED_BY.get(k, frozenset()) & set(keys))]
    if len(keys) > 1 and "PATH_WARN_ONLY" in keys:
        keys.remove("PATH_WARN_ONLY")
    return keys or [UNCLASSIFIED.key]


def candidates_for(cause_keys: Iterable[str]) -> list[str]:
    out: list[str] = []
    for k in cause_keys:
        for c in RULE_BY_KEY[k].candidates:
            if c not in out:
                out.append(c)
    return out


# --------------------------------------------------------------------------- 입력(개발셋 결과만)


def _assert_dev_name(path: Path) -> None:
    sealed_guard.check_access(path, allow_sealed=False)  # 시험셋 세트 파일 이름이면 열기 전에 예외
    name = path.name.lower()
    if name.startswith(TEST_RESULT_PREFIXES) or "sealed" in name:
        raise NotDevResultError(f"시험셋 결과로 보이는 파일 이름이라 열지 않는다(RFP-26-04): {path.name}")


def assert_dev_result(data: Mapping[str, Any], name: str) -> None:
    meta = data.get("meta") or {}
    if meta.get("sealed") or meta.get("set") != "dev" or not isinstance(data.get("items"), list):
        raise NotDevResultError(f"개발셋 결과가 아니다(set={meta.get('set')!r}, sealed={meta.get('sealed')!r}): {name}. 시험셋은 대상이 아니다(RFP-26-04)")


def load_result(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    _assert_dev_name(p)
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise NotDevResultError(f"결과 JSON 형식이 아니다: {p.name}")
    assert_dev_result(data, p.name)
    return data


def runs_of(data: Mapping[str, Any]) -> list[tuple[int, list[dict[str, Any]]]]:
    """(실행 번호, 행 목록). 반복 실행(`items_repeats`)이 있으면 2회차 이후도 포함한다."""
    out = [(1, [r for r in data.get("items") or [] if isinstance(r, dict)])]
    for rep in data.get("items_repeats") or []:
        if isinstance(rep, dict) and isinstance(rep.get("items"), list):
            out.append((int(rep.get("run") or len(out) + 1), [r for r in rep["items"] if isinstance(r, dict)]))
    return out


def source_meta(name: str, data: Mapping[str, Any]) -> dict[str, Any]:
    m = data.get("meta") or {}
    v = m.get("versions") or {}
    return {"file": name, "condition": m.get("condition"), "set": m.get("set"), "set_sha256": m.get("set_sha256"),
            "repeats": m.get("repeats"), "trajectory_rule": m.get("trajectory_rule"), "prompt_set": m.get("prompt_set"),
            "graph": v.get("graph") if isinstance(v, dict) else None, "created_utc": m.get("created_utc"),
            "n_runs": len(runs_of(data)), "judge_rows": sum(1 for _, rows in runs_of(data) for r in rows
                                                              if isinstance(r.get("judge"), dict) and r["judge"].get("status") == "ok")}


def collect(results: Sequence[tuple[str, Mapping[str, Any]]]) -> list[ItemRun]:
    out: list[ItemRun] = []
    for name, data in results:
        for run, rows in runs_of(data):
            out.extend(normalize(r, source=name, run=run) for r in rows)
    return out


# --------------------------------------------------------------------------- 표(문항 단위 집계)


def _pick_primary(primaries: Sequence[str]) -> str:
    c = Counter(primaries)
    return min(c, key=lambda k: (-c[k], RULE_ORDER[k]))


def build_rows(runs: Sequence[ItemRun], *, fail_only: bool = False) -> list[dict[str, Any]]:
    """문항 ID별로 모든 실행을 묶어 한 행. 신호가 있는 실행만 원인을 센다."""
    by_id: dict[str, list[ItemRun]] = {}
    for x in runs:
        by_id.setdefault(x.id, []).append(x)
    rows: list[dict[str, Any]] = []
    for iid in sorted(by_id):
        xs = by_id[iid]
        flagged = [x for x in xs if x.has_signal(fail_only=fail_only)]
        if not flagged:
            continue
        sig: dict[str, Counter[str]] = {}
        causes: Counter[str] = Counter()
        primaries: list[str] = []
        for x in flagged:
            for col, vals in x.signals().items():
                sig.setdefault(col, Counter()).update(vals)
            ks = classify(x)
            primaries.append(ks[0])
            causes.update(ks)
        primary = _pick_primary(primaries)
        cause_keys = sorted(causes, key=lambda k: RULE_ORDER[k])
        cands = candidates_for([primary, *cause_keys])
        first = xs[0]
        rows.append({
            "id": iid, "expected_response_type": first.ert, "branch": first.branch, "group": first.group,
            "runs_flagged": len(flagged), "runs_total": len(xs),
            "signals": {k: dict(sorted(v.items())) for k, v in sig.items()},
            "judge_status": sorted({str(x.judge_status) for x in xs}),
            "judge_errors": sorted({e for x in xs for e in x.judge_errors}),
            "primary_cause": primary, "causes": cause_keys, "candidates": cands,
            "status": "열림",
        })
    return rows


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    primary = Counter(r["primary_cause"] for r in rows)
    any_cause = Counter(k for r in rows for k in r["causes"])
    cand = Counter(r["candidates"][0] for r in rows if r["candidates"])
    cand_any = Counter(c for r in rows for c in r["candidates"])
    top = [k for k, _ in sorted(cand.items(), key=lambda kv: (-kv[1], -cand_any[kv[0]], kv[0])) if k != "OBSERVE"][:5]
    return {"n_rows": len(rows), "by_primary_cause": dict(primary.most_common()), "by_any_cause": dict(any_cause.most_common()),
            "by_primary_candidate": dict(cand.most_common()), "by_any_candidate": dict(cand_any.most_common()), "top_candidates": top}


# --------------------------------------------------------------------------- 전후 비교(C2·C3)


def compare(before: Sequence[Mapping[str, Any]], after: Sequence[Mapping[str, Any]],
            ids_before: set[str], ids_after: set[str]) -> dict[str, Any]:
    b = {r["id"]: r for r in before}
    a = {r["id"]: r for r in after}
    common = ids_before & ids_after
    out_rows = []
    change: Counter[str] = Counter()
    for iid in sorted((set(b) | set(a)) & common):
        rb, ra = b.get(iid), a.get(iid)
        if rb and not ra:
            ch = "해소"
        elif ra and not rb:
            ch = "신규"
        elif rb and ra and rb["primary_cause"] == ra["primary_cause"]:
            ch = "지속"
        else:
            ch = "원인 변경"
        change[ch] += 1
        out_rows.append({"id": iid, "expected_response_type": (rb or ra or {}).get("expected_response_type"),
                         "before": rb["primary_cause"] if rb else None, "after": ra["primary_cause"] if ra else None,
                         "change": ch, "candidates_after": ra["candidates"] if ra else []})
    pc_b = Counter(r["primary_cause"] for r in before if r["id"] in common)
    pc_a = Counter(r["primary_cause"] for r in after if r["id"] in common)
    keys = sorted(set(pc_b) | set(pc_a), key=lambda k: RULE_ORDER[k])
    return {"n_common_ids": len(common), "only_before": sorted(ids_before - ids_after), "only_after": sorted(ids_after - ids_before),
            "change_counts": dict(change), "by_primary_cause": {k: [pc_b.get(k, 0), pc_a.get(k, 0)] for k in keys}, "rows": out_rows}


# --------------------------------------------------------------------------- 출력


def _cell(v: Any) -> str:
    if isinstance(v, dict):
        v = ", ".join(f"{k}×{n}" if n > 1 else str(k) for k, n in v.items())
    elif isinstance(v, list | tuple):
        v = ", ".join(str(x) for x in v)
    s = "" if v is None else str(v)
    return s.replace("|", "\\|").replace("\n", " ") or "-"


SIGNAL_COLS = (("path", "경로 위반·경고"), ("end_reason", "end_reason"), ("safety_elements", "필수·안전 요소 거짓"),
               ("judgment_wrong", "판정 오답"), ("judge", "judge 실패"), ("clarify", "되묻기"), ("no_evidence", "근거 없음"))


def rules_table_md() -> list[str]:
    lines = ["| 순위 | 원인 키 | 이름 | 조건 | 개선 후보 |", "|---|---|---|---|---|"]
    for i, r in enumerate((*RULES, UNCLASSIFIED), 1):
        lines.append(f"| {i} | `{r.key}` | {r.label} | {_cell(r.when)} | {_cell(r.candidates)} |")
    return lines


def candidates_table_md(counts: Mapping[str, int] | None = None) -> list[str]:
    lines = ["| 후보 키 | 티켓 | 내용 | 출처 | 상태 | 주 후보 행 수 |", "|---|---|---|---|---|---|"]
    for c in CANDIDATES.values():
        lines.append(f"| `{c.key}` | {c.ticket} | {_cell(c.title)} | {_cell(c.source)} | {c.status} | {(counts or {}).get(c.key, 0)} |")
    return lines


def render_md(report: Mapping[str, Any]) -> str:
    L: list[str] = [f"# 개발셋 실패 표 ({report['generated_utc'][:10]})", "",
                    f"- 스키마 `{SCHEMA}`, 규칙 `{RULESET_VERSION}`, 생성 `evaluation/dev_failures.py`(LLM 0). **개발셋만**(RFP-26-04). 질문 원문은 넣지 않는다.",
                    f"- 행 포함 기준: {'Fail 또는 비경로 신호' if report['fail_only'] else '경로 Fail·Warn 또는 비경로 신호'}. 주 원인 = 우선순위 첫 일치(실행이 여럿이면 최빈, 동률은 우선순위).",
                    "", "## 1. 입력", "", "| 파일 | 조건 | set | prompt_set | 경로 규칙 | 실행 수 | judge 채점 행 |", "|---|---|---|---|---|---|---|"]
    for s in report["sources"]:
        L.append(f"| `{s['file']}` | {s['condition']} | {s['set']} | {_cell(s['prompt_set'])} | {s['trajectory_rule']} | {s['n_runs']} | {s['judge_rows']} |")
    if not any(s["judge_rows"] for s in report["sources"]):
        L += ["", "- judge 칸이 없다(채점 전): 원인 분류는 코드 채점 신호만으로 했다(AG-13-03 A 실행 뒤 다시 돌린다)."]
    sm = report["summary"]
    L += ["", "## 2. 요약", "", f"- 표 행 {sm['n_rows']}개(문항 ID 기준).", "", "| 주 원인 | 이름 | 행 수 | 전체 원인(중복) |", "|---|---|---|---|"]
    for k in sorted(set(sm["by_primary_cause"]) | set(sm["by_any_cause"]), key=lambda k: RULE_ORDER[k]):
        L.append(f"| `{k}` | {RULE_BY_KEY[k].label} | {sm['by_primary_cause'].get(k, 0)} | {sm['by_any_cause'].get(k, 0)} |")
    L += ["", "상위 개선 후보(주 후보 행 수 순, 관찰 제외): " + ", ".join(f"`{k}`({sm['by_primary_candidate'].get(k, 0)})" for k in sm["top_candidates"])]
    if report.get("compare"):
        c = report["compare"]
        L += ["", "## 3. 전후 비교", "", f"- 공통 문항 {c['n_common_ids']}개, 변화: {_cell(c['change_counts'])}."
              + (f" 한쪽에만 있는 문항: 전 {len(c['only_before'])}·후 {len(c['only_after'])}" if c["only_before"] or c["only_after"] else ""),
              "", "| 주 원인 | 전 | 후 |", "|---|---|---|"]
        for k, (nb, na) in c["by_primary_cause"].items():
            L.append(f"| `{k}` | {nb} | {na} |")
        L += ["", "| id | 유형 | 전 주 원인 | 후 주 원인 | 변화 | 후 개선 후보 |", "|---|---|---|---|---|---|"]
        for r in c["rows"]:
            L.append(f"| {r['id']} | {r['expected_response_type']} | {_cell(r['before'])} | {_cell(r['after'])} | {r['change']} | {_cell(r['candidates_after'])} |")
    n = 4 if report.get("compare") else 3
    L += ["", f"## {n}. 문항별 표", "", "| id | 유형 | 실패 실행 | " + " | ".join(h for _, h in SIGNAL_COLS) + " | 주 원인 | 원인(전체) | 개선 후보 | 상태 |",
          "|" + "---|" * (len(SIGNAL_COLS) + 7)]
    for r in report["rows"]:
        sig = r["signals"]
        cells = [_cell(sig.get(k)) for k, _ in SIGNAL_COLS]
        L.append(f"| {r['id']} | {r['expected_response_type']}/{_cell(r['group'])} | {r['runs_flagged']}/{r['runs_total']} | " + " | ".join(cells)
                 + f" | `{r['primary_cause']}` | {_cell(r['causes'])} | {_cell(r['candidates'])} | {r['status']} |")
    L += ["", f"## {n + 1}. 원인 분류 규칙({RULESET_VERSION})", "",
          "- 일반 규칙 제외: `OVER_CLARIFY`는 `FAKE_DRUG_CLARIFY`·`TYPO_CLARIFY`·`EMERGENCY_CLARIFY`가 맞으면 빼고, `PATH_WARN_ONLY`는 다른 원인이 하나라도 있으면 뺀다.",
          "", *rules_table_md(),
          "", f"## {n + 2}. 개선 후보", "", *candidates_table_md(sm["by_primary_candidate"]), ""]
    return "\n".join(L)


def build_report(results: Sequence[tuple[str, Mapping[str, Any]]], *, fail_only: bool = False,
                 before: Sequence[tuple[str, Mapping[str, Any]]] | None = None) -> dict[str, Any]:
    runs = collect(results)
    rows = build_rows(runs, fail_only=fail_only)
    report: dict[str, Any] = {
        "schema": SCHEMA, "ruleset": RULESET_VERSION, "generated_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "fail_only": fail_only, "sources": [source_meta(n, d) for n, d in results],
        "summary": summarize(rows), "rows": rows,
    }
    if before is not None:
        b_runs = collect(before)
        b_rows = build_rows(b_runs, fail_only=fail_only)
        report["before_sources"] = [source_meta(n, d) for n, d in before]
        report["before_summary"] = summarize(b_rows)
        report["compare"] = compare(b_rows, rows, {x.id for x in b_runs}, {x.id for x in runs})
    return report


def _load_all(paths: Sequence[str]) -> list[tuple[str, dict[str, Any]]]:
    return [(Path(p).name, load_result(p)) for p in paths]


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AG-13 개발셋 실패 표(LLM 0, 개발셋만)")
    ap.add_argument("results", nargs="*", help="개발셋 결과 JSON(여럿이면 문항별로 묶는다)")
    ap.add_argument("--before", nargs="+", help="비교 모드: 개선 전 결과")
    ap.add_argument("--after", nargs="+", help="비교 모드: 개선 후 결과")
    ap.add_argument("--fail-only", action="store_true", help="경로 Warn만 있는 문항은 뺀다")
    ap.add_argument("--out-md", required=True)
    ap.add_argument("--out-json")
    a = ap.parse_args(argv)
    if bool(a.before) != bool(a.after):
        ap.error("--before와 --after는 함께 준다")
    if a.before and a.results:
        ap.error("비교 모드에서는 위치 인자를 쓰지 않는다")
    if not a.before and not a.results:
        ap.error("결과 JSON을 하나 이상 준다")
    try:
        if a.before:
            report = build_report(_load_all(a.after), fail_only=a.fail_only, before=_load_all(a.before))
        else:
            report = build_report(_load_all(a.results), fail_only=a.fail_only)
    except (NotDevResultError, sealed_guard.SealedAccessError) as e:
        print(f"거절: {e}", file=sys.stderr)
        return 2
    out_md = Path(a.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_md(report), encoding="utf-8")
    if a.out_json:
        Path(a.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out_json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    sm = report["summary"]
    print(f"행 {sm['n_rows']}개 · 주 원인 {sm['by_primary_cause']} · 상위 후보 {sm['top_candidates']} → {out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
