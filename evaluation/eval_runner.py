"""AG-11 평가 러너 골격: 평가 세트 읽기(시험셋 가드) → 에이전트 실행(어댑터) → 코드 채점 지표 → k/n·Wilson 95% → 결과 JSON.

- 지표 정의는 `P2-doc/PJ2-RFP.md` 9장 그대로다(`eval_metrics.py` 머리말). judge(Claude Sonnet 5.5, 루브릭 J1~J5)와 Ragas 3지표는
  **인터페이스만** 두고 호출하지 않는다(`NotCalledJudge`). judge 요소가 남은 문항의 안전 응답 통과는 "보류"로 집계된다.
- 에이전트는 어댑터로 주입한다. `GraphAdapter`는 컴파일된 LangGraph(AG-01)를 받아 최종 상태에서 실행 기록을 뽑는다(가짜 모델을 넣은
  그래프면 LLM 호출 0). CLI 기본 에이전트 `offline-fixed`는 도구·모델 없이 코드 고정 문구 답만 만드는 연결 확인용(채점 파이프라인 점검, 측정값 아님).
- 시험셋(`*.SEALED.jsonl`)은 `sealed_guard`로 막는다. 허용돼 돌렸더라도 결과 파일에는 **점수만** 남기고 문항별 기록·실패 문항 ID는 남기지 않는다(9.1절 8번).
- 결과 파일에는 세트 버전·파일 sha256(manifest와 대조)·조건·모델·프롬프트·그래프·하네스·사전 버전·judge 모델·루브릭 버전·패턴 버전을 적는다(9.6절 동결 확인).
- 이 모듈은 원격 DB·공공 API·LLM을 부르지 않는다(어댑터가 실제 모델을 넣었을 때만 그 모델이 호출된다).

사용(저장소 루트): `backend/.venv/bin/python evaluation/eval_runner.py --set dev --agent offline-fixed [--limit N] [--out PATH]`

L2(개발 골든 스모크, AG-06-06 A): `--agent graph --subset dev_golden [--prompt-set prompt_set@vN] --max-usd X`는 서비스와 같은 부품으로
실제 그래프를 만들어 돌린다(평가 모드: API 병기 끔, LLM 캐시 끔). **실제 모델을 부르고 원격 DB를 읽으므로 비용 상한이 필수다.** judge는 붙이지 않는다.
`--prompt-set`을 주지 않으면 서비스와 같은 기본 묶음(`wiring.DEFAULT_PROMPT_SET`, 2026-11-17부터 `prompt_set@v3`, 모두 adopted)을 쓰고 결과 meta에 그 이름이 남는다.
`--allow-draft`는 draft 프롬프트가 든 묶음을 점검할 때만 붙인다(기본 L2 사용법에는 필요 없다).
비교 조건(9.5절): `--condition`은 `C2`(ReAct 그래프, 기본)와 `C1`·`C1+`(AG-16 고정 파이프라인), `C0`(LLM 단독: 같은 모델에 질문만,
원격 DB 없음)를 받는다(C1·C1+·C0는 `--agent graph`에서만). 그 밖의 값(C3는 AG-13 뒤라 미연결)은 실행 없이 거부한다(종료 코드 2). graph 에이전트 결과 meta에는 조건별 하네스 적용표 `harness`(`harness@v1`, RFP-33-03)를 적는다.
Validator 규칙 집계(AG-07-02 B): 문항별 `validator`(H22·H24 검사 코드·규칙별 건수)와 `metrics.validator_rule_counts`는 보조 기록이다(9장 지표 아님).
`--compare A.json B.json`은 두 결과를 나란히 보여 준다(회귀 경보 전용).

측정 기간 동결(9.6절, BE-08): graph 결과 meta `run_settings`에 호출 상한·LLM 설정(온도 미지정)·검색 방식·API 끔·파일별 기준일을 적는다.
`--baseline 이전결과.json`을 주면 실행 전에 동결 값(세트 해시·모델·호출 상한·사전·코퍼스·채점 규칙·judge 모델·루브릭, 같은 C1·C1+끼리는 규칙 버전)을
비교해 다르면 시작하지 않는다(종료 코드 2). 이유가 있으면 `--freeze-diff-reason "이유"`로 기록하고 실행한다. 점검은 `evaluation/freeze_check.py`.

judge(AG-11-02·05): `--judge sonnet --judge-max-usd X`는 Claude Sonnet 5.5(`evaluation/judge/sonnet_judge.py`)로 J1·J3~J5와 Ragas 3지표(J1·J2,
`ragas_metrics.py`)를 채점한다(graph 전용, **실제 호출·비용 발생**, `anthropic` SDK는 `backend[eval]`). judge 요소는 코드 채점 칸의 보류(None)만 채우고
안전 응답 통과를 다시 계산한다. 근거 청크는 그래프가 받은 순서(`run.evidence_order`)로 준다. 결과 meta `judge`에 모델·루브릭 버전·judge 프롬프트
sha256, `judge_usage`에 호출·재시도·오류율·비용이 남는다. judge 비용은 에이전트 상한(`--max-usd`)과 따로 센다. 기본(`--judge none`)은 코드 채점만이다.

오탈자 보정(AG-10): 스위치는 **비교 조건이 정한다**(`resolve_typo_correct`). C1은 항상 끔, C1+는 항상 켬, C2는 기본 켬(AG-10-04 A. 서비스 배선은
BE-06-35 A로 FE-02 반영 전까지 끔)이고 `--no-typo-correct`로만 끌 수 있다(보정 전 결과와 비교할 때). 조건과 어긋나는 플래그는 실행 없이 거부한다.
결과 meta `typo_correction`에 켰는지·고지 문구 상태·기준값이 남는다. `--ids dev-056,dev-057`은 개발셋에서 그 문항만 돌린다(시험셋에는 쓰지 못한다).

L3(개발셋 전체): `--subset` 없이 150문항 1회, `--subset dev_reliability_core --repeats 3`으로 개발 안전 핵심 40문항 3회(`pass^3`·`pass@3`·판정 일치율).
graph 에이전트 실행은 문항 오류가 3건 연속이면 멈추고 결과 `stopped`에 사유·위치를 남긴다(AG-06-09 A, 하네스 차단은 오류가 아님).
개발셋 반복 실행은 2·N회차 문항별 행을 `items_repeats`에 남긴다(AG-06-11 A, 시험셋은 점수만).
신뢰성 1회차 재사용(RFP-35-09 A, 9.4·9.7절): 본 측정을 `--save-reliability-carry`로 돌리면 결과 옆에 안전 핵심 문항 행(신뢰성 계산 칸만,
시험셋은 순번·해시만)을 남기고, 신뢰성 실행 `--subset reliability_core --repeats 3 --first-run 본측정.json`은 추가 2회만 돈다.
본 측정과 동결 값·조건·에이전트 버전·judge 유무가 다르거나 문항이 빠졌으면 시작하지 않는다(종료 코드 2).

재채점: `--rescore RESULT.json [--out PATH]`은 저장된 개발셋 결과의 실행 기록을 지금 채점기(경로 규칙 `traj@v2`, RFP-26-08 A)로 다시
채점해 새 파일로 쓴다(모델·도구 호출 0, 원본 보존). Router 기록이 없는 예전 결과는 재채점하지 않는다(종료 코드 3, 재측정 필요).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, ClassVar, Protocol

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (str(HERE), str(HERE / "judge"), str(ROOT / "backend")):
    if p not in sys.path:
        sys.path.insert(0, p)

import eval_metrics as M  # noqa: E402
import freeze_check as FZ  # noqa: E402
import ragas_metrics as RG  # noqa: E402
import sealed_guard as G  # noqa: E402
import sonnet_judge as SJ  # noqa: E402

EVAL_SET_DIR = HERE / "eval_set"
MANIFEST = EVAL_SET_DIR / "manifest.json"
SET_FILES = {"dev": EVAL_SET_DIR / "dev_set.jsonl", "test": EVAL_SET_DIR / "test_set.SEALED.jsonl"}
OUT_DIR = ROOT / "logs" / "eval"  # 로컬 전용(`logs/`는 .gitignore)
RUNNER_VERSION = "ag11-runner@v0-skeleton"
# 러너가 실제로 연결한 비교 조건(9.5절). C1(AG-16 고정 파이프라인)은 2026-11-18에 연결했다(`app.agent.pipeline.build.build_for_condition`).
# C1+(오탈자 보정 후 재검색 1회, Router의 AG-10 보정 재사용)는 2026-11-18에 연결했다(AG-16-06 A).
# C0(LLM 단독)는 2026-11-18에 연결했다(`LlmOnlyAgent`, 에이전트 코드 변경 없이 같은 모델 생성 함수만 쓴다). C3는 AG-13 개선 뒤라 연결하지 않았다.
SUPPORTED_CONDITIONS: tuple[str, ...] = ("C2", "C1", "C1+", "C0")
DEFAULT_CONDITION = "C2"
GRAPH_ONLY_CONDITIONS: tuple[str, ...] = ("C1", "C1+")  # 그래프를 실제로 만들어야 뜻이 있는 조건(offline-fixed는 조건과 무관한 연결 확인용이라 C2 표기만 허용)
C0 = "C0"
C0_VERSION = "c0-llm-only@v1"  # C0 규칙 버전(질문만, 시스템 프롬프트·도구·Router·Validator·finalize 없음). 규칙을 바꾸면 올린다
REAL_MODEL_CONDITIONS: tuple[str, ...] = (*GRAPH_ONLY_CONDITIONS, C0)  # --agent graph(실제 모델 실행)에서만 받는 조건

JUDGE_MODEL = "claude-sonnet-5-5"  # RFP-26-01 고정. 이 골격은 호출하지 않는다
RUBRIC_VERSIONS = {"J1": "J1@v1", "J2": "J2@v1", "J3": "J3@v1", "J4": "J4@v1", "J5": "J5@v1"}


# --------------------------------------------------------------------------- judge 인터페이스(호출 안 함)

class Judge(Protocol):
    model_id: str
    rubric_versions: dict[str, str]

    def score(self, item: dict[str, Any], answer: dict[str, Any], contexts: Sequence[str]) -> dict[str, Any]:
        """루브릭 J1~J5 채점. 반환: {"rubric": "J3@v1", "items": {R1: {pass, reason, evidence}}, "overall_pass": bool} (RFP-26 §7.5)."""
        ...


class NotCalledJudge:
    """judge 자리 표시. 어떤 호출도 하지 않고 `None`(보류)을 돌려준다."""

    model_id = JUDGE_MODEL
    rubric_versions = RUBRIC_VERSIONS
    called = 0

    def score(self, item: dict[str, Any], answer: dict[str, Any], contexts: Sequence[Any], **_: Any) -> dict[str, Any]:
        return {"rubric": None, "items": {}, "overall_pass": None, "status": "not_called"}


# 실제 judge(AG-11-02·05, 2026-11-18 연결): `evaluation/judge/sonnet_judge.SonnetJudge`. 전송 계층(`JudgeTransport`)을 주입해야 만들어진다
# (인자 없이 만들면 TypeError). 실제 호출은 `--judge sonnet --judge-max-usd X`로만 열린다.
SonnetJudge = SJ.SonnetJudge
JUDGE_NONE, JUDGE_SONNET = "none", "sonnet"
JUDGE_BUDGET_STOP = "JUDGE_BUDGET"  # judge 비용 상한에 닿아 그 뒤 문항의 judge 채점을 건너뜀


def is_real_judge(judge: Any) -> bool:
    """루브릭을 실제로 채점하는 judge인가(자리 표시 `NotCalledJudge`가 아니고 루브릭 단위 채점 `score_rubric`이 있다)."""
    return judge is not None and not isinstance(judge, NotCalledJudge) and hasattr(judge, "score_rubric")


def judge_contexts(rec: M.RunRecord) -> list[SJ.Context]:
    """judge·Ragas에 줄 근거 청크. 판정 항목은 최종 답의 근거 상세(`sonnet_judge.contexts_from_answer`, 보정 40문항과 같은 재료)이고
    검색 청크는 그 머리 줄에 그래프 `evidence`의 본문 원문(`RunRecord.evidence_texts`)을 붙인다.
    **순서는 그래프가 근거를 받은 순서**(`RunRecord.evidence_order`, AG-11-05 A)다. 순서 기록에 없는 청크(등급 정의 블록 등)는 뒤에 둔다.
    순서 기록이 없는 실행(예전 결과·가짜 에이전트)은 근거 상세 순서 그대로다."""
    ctx = SJ.contexts_from_answer(rec.answer)
    bodies = rec.evidence_texts or {}
    if bodies:  # 검색 청크: 근거 상세에는 머리 줄(종류·출처·기준일)만 있어 본문을 그대로 붙인다(요약·자르기 없음)
        ctx = [SJ.Context(c.id, f"{c.text}\n{bodies[c.id]}") if c.id in bodies else c for c in ctx]
    order = rec.evidence_order
    if not order:
        return ctx
    rank = {eid: i for i, eid in enumerate(order)}
    return sorted(ctx, key=lambda c: rank.get(c.id, len(rank)))  # 안정 정렬: 순서 기록에 없는 것은 원래 순서로 뒤에


def merge_judge(row: dict[str, Any], judged: dict[str, Any]) -> None:
    """judge 요소를 코드 채점 칸에 합친다(코드가 None으로 비워 둔 judge 요소만 채운다. 코드 요소는 덮지 않는다).
    안전 응답 통과(9.3절 "필수 요소 모두")는 `eval_metrics.score_item`과 같은 규칙으로 다시 계산한다."""
    els = row.get("elements") or {}
    for el, v in (judged.get("elements") or {}).items():
        if el in els and els[el] is None and v is not None:
            els[el] = bool(v)
    if row.get("safety"):
        pend = sorted(k for k, v in els.items() if v is None)
        code_pass = bool(row["safety"]["code_pass"])
        failed = not code_pass or any(v is False for v in els.values())
        row["safety"] = {"code_pass": code_pass, "pending_judge": pend, "pass": False if failed else (None if pend else True)}


# --------------------------------------------------------------------------- 에이전트 어댑터

Agent = Callable[[dict[str, Any]], M.RunRecord]


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def extract_trace(state: dict[str, Any]) -> M.RunRecord:
    """그래프 최종 상태 → 실행 기록. 도구 호출은 모델 메시지의 `tool_calls`, 근거 ID는 도구 결과(`evidence`·`known_ids`)에서."""
    calls: list[M.ToolCall] = []
    for msg in state.get("messages") or []:
        for tc in _get(msg, "tool_calls") or []:
            calls.append(M.ToolCall(str(_get(tc, "name", "")), dict(_get(tc, "args") or {})))
    ids: set[str] = set(state.get("known_ids") or ())
    order: list[str] = []  # 근거 ID를 도구가 돌려준 순서대로(AG-11-05 A: Context Precision의 검색 순위). 결과 파일에는 ID·순서만 남는다
    texts: dict[str, str] = {}  # 검색 청크 본문(요약·자르기 없음). judge에 줄 재료로 실행 중에만 든다(`RunRecord.evidence_texts`, 파일에 안 씀)
    for it in state.get("evidence") or []:
        if isinstance(it, dict):
            if it.get("evidence_id"):
                ids.add(str(it["evidence_id"]))
                if str(it["evidence_id"]) not in order:
                    order.append(str(it["evidence_id"]))
                if isinstance(it.get("text"), str) and it["text"].strip():
                    texts.setdefault(str(it["evidence_id"]), it["text"])
            for m in it.get("matches") or []:
                if isinstance(m, dict) and m.get("row_evidence_id"):
                    ids.add(str(m["row_evidence_id"]))
    clar = state.get("clarify") or {}
    opts = _get(clar, "options") or _get(clar, "candidates") or []
    return M.RunRecord(answer=dict(state.get("answer") or {}), tool_calls=calls, model_calls=int(state.get("call_count") or 0),
                       end_reason=state.get("end_reason"), tool_evidence_ids=ids, clarify_options=len(opts), evidence_order=order, evidence_texts=texts,
                       harness_warns=harness_warn_count(state),
                       **router_trace(state),  # 식별 기록(RFP-26-08 A)
                       **source_missing_counts(state),  # 보조 집계(AG-06-07 A, 9장 지표 아님)
                       **validator_rule_trace(state))  # Validator 규칙 집계(AG-07-02 B, 9장 지표 아님)


ROUTER_ENTITY_KEYS = ("status", "item_seq")  # 질문 조각(raw·normalized)은 결과 파일에 남기지 않는다


def router_trace(state: dict[str, Any]) -> dict[str, Any]:
    """Router 결과(엔티티별 상태·확정 item_seq, 되묻기 여부)와 `identify_drug` 결과의 item_seq(RFP-26-08 A).
    `ran`은 Router가 상태를 썼는지다(입구 거절로 Router 앞에서 끝나면 False). 종료 사유는 `end_reason`에 따로 있다."""
    ents = [e for e in state.get("entities") or [] if isinstance(e, dict)]
    router = {"ran": "entities" in state, "ambiguous": bool(state.get("ambiguous")),
              "entities": [{k: e.get(k) for k in ROUTER_ENTITY_KEYS} for e in ents]}
    seqs: list[str] = []
    for it in state.get("evidence") or []:
        if isinstance(it, dict) and it.get("kind") == "identify" and it.get("item_seq") and str(it["item_seq"]) not in seqs:
            seqs.append(str(it["item_seq"]))
    return {"router": router, "identify_item_seqs": seqs}


class ProfileFormatError(ValueError):
    """평가 세트 프로필을 그래프 프로필로 바꿀 수 없다(모르는 단위·키·값). 조용히 버리지 않고 실행을 멈춘다."""


_PROFILE_KEYS = frozenset({"age", "pregnant"})


def _age_years(age: Any) -> float | None:
    if age is None:
        return None
    if not isinstance(age, dict) or set(age) != {"value", "unit"}:
        raise ProfileFormatError(f"age 형식은 None 또는 {{value, unit}}이어야 한다: {type(age).__name__}")
    value, unit = age["value"], age["unit"]
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ProfileFormatError(f"age.value는 0 이상의 숫자여야 한다: {value!r}")
    if unit == "세":
        return float(value)
    if unit == "개월":
        return round(value / 12, 2)  # router `_AGE_MONTH_RE` 처리와 같은 규칙(개월/12, 소수 둘째 자리)
    raise ProfileFormatError(f"처리하지 못하는 age.unit: {unit!r}")


def to_graph_profile(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    """평가 세트 프로필 `{"age": None | {"value", "unit"}, "pregnant": bool | None}` → 그래프 `ProfileState` 입력
    `{"age_years", "pregnant"}`(값이 있는 키만). 둘 다 없으면 None. 모르는 키·단위·값은 `ProfileFormatError`."""
    if profile is None:
        return None
    if not isinstance(profile, dict):
        raise ProfileFormatError(f"profile은 dict여야 한다: {type(profile).__name__}")
    extra = set(profile) - _PROFILE_KEYS
    if extra:
        raise ProfileFormatError(f"모르는 profile 키: {sorted(extra)}")
    pregnant = profile.get("pregnant")
    if pregnant is not None and not isinstance(pregnant, bool):
        raise ProfileFormatError(f"pregnant는 bool 또는 None이어야 한다: {pregnant!r}")
    out: dict[str, Any] = {}
    age = _age_years(profile.get("age"))
    if age is not None:
        out["age_years"] = age
    if pregnant is not None:
        out["pregnant"] = pregnant
    return out or None


class GraphAdapter:
    """컴파일된 AG-01 그래프를 평가 에이전트로 쓴다. `graph`에 가짜 모델을 넣었으면 LLM 호출 0이다.
    평가 모드(API Tool 끔)는 그래프를 만들 때 `wiring.build_tool_context(mode="eval")`로 정한다(9.4절, 이 어댑터는 그래프를 만들지 않는다)."""

    def __init__(self, graph: Any, *, info: dict[str, Any] | None = None) -> None:
        self.graph = graph
        self.info = {"agent": "graph", **(info or {})}

    def __call__(self, item: dict[str, Any]) -> M.RunRecord:
        from app.agent.graph.build import run_question

        profile = to_graph_profile(item.get("profile"))  # 형식 오류는 에이전트 실패(경로 Fail)로 섞지 않고 실행을 멈춘다
        t0 = time.perf_counter()
        try:
            state = run_question(self.graph, item["question"], profile)
            rec = extract_trace(state)
        except Exception as e:  # noqa: BLE001 - 문항 하나의 실패가 전체 실행을 멈추지 않게(오류는 경로 Fail로 집계)
            rec = M.RunRecord(answer={}, error=type(e).__name__)
        rec.latency_s = round(time.perf_counter() - t0, 4)
        return rec


class OfflineFixedAgent:
    """연결 확인용: 도구·모델 없이 백엔드 `finalize`로 고정 문구 답만 만든다(응급 키워드면 119). 측정값으로 쓰지 않는다."""

    info: ClassVar[dict[str, str]] = {"agent": "offline-fixed", "note": "채점 파이프라인 연결 확인용, 측정값 아님"}

    def __call__(self, item: dict[str, Any]) -> M.RunRecord:
        from app.agent.finalize import finalize
        from app.agent.guardrail import detect_emergency

        return M.RunRecord(answer=finalize([], emergency=detect_emergency(item.get("question") or "")), end_reason="NORMAL")


# --------------------------------------------------------------------------- 실행

def sha256_file(path: Path, *, allow_sealed: bool = False) -> str:
    return hashlib.sha256(G.read_bytes(path, allow_sealed=allow_sealed)).hexdigest()


def manifest_check(path: Path, digest: str) -> dict[str, Any]:
    """평가 세트 파일 해시가 manifest와 같은가(측정 기간 동결, 9.6절). manifest 자체는 시험셋 문항을 담지 않는다."""
    try:
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"manifest": None, "match": None}
    want = next((v.get("sha256") for v in (man.get("sets") or {}).values() if v.get("file") == path.name), None)
    return {"manifest_set_version": man.get("set_version"), "manifest_sha256": want, "match": (want == digest) if want else None}


def run_eval(
    items: Sequence[dict[str, Any]],
    agent: Agent,
    *,
    sealed: bool,
    meta: dict[str, Any] | None = None,
    judge: Any = None,
    phrases: M.Phrases | None = None,
    repeats: int = 1,
    budget: CostBudget | None = None,
    skip_judge: bool = False,
    max_consecutive_errors: int | None = None,
    carry_keys_map: dict[str, str] | None = None,
    carry_out: list[dict[str, Any]] | None = None,
    first_run: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """`budget`을 주면 문항을 시작하기 전마다 누적 비용을 보고, 상한에 닿았으면 남은 문항을 건너뛴다(`skipped_cost_cap`).
    `skip_judge`면 judge 자리를 비운다(결과 `judge: null`).
    `max_consecutive_errors`를 주면 문항 오류(`is_item_error`)가 그 수만큼 연속일 때 남은 문항·회차를 건너뛰고 `stopped`에 사유·위치를 남긴다
    (AG-06-09 A). 연속 수는 회차 경계를 넘어 이어 센다. 셋 다 주지 않으면 예전 동작·결과 형식 그대로다.
    신뢰성 1회차 재사용(RFP-35-09 A): `carry_out`(목록)과 `carry_keys_map`(문항 ID → 키)을 주면 첫 회차 행 중 그 문항을 `carry_row`로 줄여 담는다.
    `first_run`(줄인 1회차 행)을 주면 실행은 2회차부터 `repeats - 1`번만 하고, 신뢰성은 1회차를 더한 `repeats`회로 계산한다
    (지표·문항별 행은 실행한 회차만, `run_index`는 2부터)."""
    first = 1 if first_run is not None else 0  # 실행하는 첫 회차의 번호(0부터)
    ph = phrases or M.Phrases.from_backend()
    judge = judge or NotCalledJudge()
    real_judge = is_real_judge(judge) and not skip_judge
    judge_stopped = False            # judge 비용 상한에 닿았다(그 뒤 문항은 judge 없이 코드 채점만)
    judge_skipped: list[str] = []
    ragas_mode = RG.MODE_REFERENCE if (meta or {}).get("condition") == "C0" else RG.MODE_RETRIEVED
    runs: list[list[dict[str, Any]]] = []
    skipped: list[str] = []
    cost_by_item: dict[str, float] = {}
    streak: list[str] = []          # 지금 이어지는 연속 오류의 종류
    err_first = err_total = 0
    stopped: dict[str, Any] | None = None
    skipped_stop: list[str] = []    # 연속 오류 중단으로 1회차에서 돌지 못한 문항
    for n_run in range(first, max(1, repeats)):
        rows = []
        for idx, it in enumerate(items):
            if stopped is not None:
                stopped["skipped"] += 1
                if n_run == first:
                    skipped_stop.append(str(it.get("id")))
                continue
            if budget is not None and budget.exhausted():
                if n_run == first:
                    skipped.append(str(it.get("id")))
                continue
            rec = agent(it)
            if max_consecutive_errors:
                if is_item_error(rec):
                    streak.append(rec.error or NO_ANSWER)
                    err_total += 1
                    err_first += n_run == first
                else:
                    streak = []
                if len(streak) >= max_consecutive_errors:
                    stopped = {"reason": STOP_CONSECUTIVE_ERRORS, "threshold": max_consecutive_errors, "run": n_run + 1, "index": idx,
                               **({} if sealed else {"item_id": it.get("id")}), "errors": list(streak), "skipped": 0}
            row = M.score_item(it, rec, ph)
            if budget is not None or repeats > 1 or first:  # 실제 그래프 실행·반복 실행에만 적는다(기본 연결 확인 실행의 결과 형식은 그대로)
                row["run_index"] = n_run + 1  # 회차(1부터, 로깅 전략의 `repeat_idx`와 같은 값, RFP-35-09)
            if rec.harness_warns is not None:
                row["harness_warns"] = int(rec.harness_warns)
            if budget is not None:  # 에이전트 몫만(judge 비용은 `judge_usage`에 따로 센다)
                row["cost_usd"] = round(budget.item_cost(), 6)
                cost_by_item[str(it.get("id"))] = round(cost_by_item.get(str(it.get("id")), 0.0) + row["cost_usd"], 6)
            if skip_judge:
                row["judge"] = None
            elif not real_judge:
                row["judge"] = judge.score(it, rec.answer, [])  # 자리 표시: 호출 없음(보류)
            elif judge_stopped or is_item_error(rec):
                row["judge"] = {"rubric": None, "rubrics": {}, "overall_pass": None, "status": "not_called",
                                "reason": JUDGE_BUDGET_STOP if judge_stopped else "RUN_ERROR"}
                if judge_stopped and n_run == first:
                    judge_skipped.append(str(it.get("id")))
            else:
                ctx = judge_contexts(rec)
                try:
                    row["judge"] = judge.score(it, rec.answer, ctx, end_reason=rec.end_reason)
                    merge_judge(row, row["judge"])
                    if RG.ragas_applicable(it):
                        # C0(정답 근거를 컨텍스트로)는 청크가 달라 J1을 다시 받는다. 그 밖은 위에서 받은 J1을 재사용한다(같은 답·같은 청크)
                        j1 = (row["judge"].get("rubrics") or {}).get("J1") if ragas_mode == RG.MODE_RETRIEVED else None
                        row["ragas"] = RG.ragas_item(judge, it, rec.answer, contexts=ctx, tool_evidence_ids=rec.tool_evidence_ids,
                                                     end_reason=rec.end_reason, mode=ragas_mode, j1=j1)
                except SJ.JudgeBudgetExceeded:
                    judge_stopped = True
                    row.setdefault("judge", {"rubric": None, "rubrics": {}, "overall_pass": None, "status": "not_called",
                                             "reason": JUDGE_BUDGET_STOP})
                    if n_run == first:
                        judge_skipped.append(str(it.get("id")))
            if not sealed:
                row["run"] = rec.to_json()
            rows.append(row)
        runs.append(rows)
    result: dict[str, Any] = {
        "meta": {
            "runner": RUNNER_VERSION, "created_utc": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sealed": sealed, "repeats": max(1, repeats), "eval_mode_env": os.environ.get("MEDIAGENT_EVAL") or os.environ.get("MEDIAGENT_MODE"),
            "judge": {"model": getattr(judge, "model_id", None), "rubrics": getattr(judge, "rubric_versions", None),
                      "status": "called" if real_judge else "not_called"},
            "patterns": M.PATTERN_VERSION, "trajectory_rule": M.TRAJ_RULE, **(meta or {}),
        },
        "metrics": M.aggregate(runs[0]),
    }
    hs = harness_summary(runs[0])
    if hs is not None:
        result["metrics"]["harness_events"] = hs
    if skip_judge:
        result["meta"]["judge"] = None
        result["judge"] = None  # judge를 붙이지 않은 실행(코드 채점만). 자리만 둔다
    elif real_judge:
        # judge 모델·루브릭 버전·judge 프롬프트 파일 sha256(9.6절 동결 확인)과 사용량·오류율. 시험셋이어도 문항 내용이 없어 그대로 남긴다
        jm = judge.meta() if hasattr(judge, "meta") else {}
        result["meta"]["judge"].update({k: jm.get(k) for k in ("prompt_file", "prompt_sha256", "prompt_status", "thinking", "max_tokens")})
        result["meta"]["judge"]["ragas"] = RG.RAGAS_VERSION
        usage = judge.usage.to_json() if hasattr(judge, "usage") else {}
        result["judge_usage"] = {**usage, "max_usd": getattr(judge, "max_usd", None), "cap_reached": judge_stopped,
                                 "skipped": len(judge_skipped) if sealed else judge_skipped}
        result["metrics"]["ragas"] = RG.aggregate_ragas([r["ragas"] for r in runs[0] if r.get("ragas")])
        left = ["J3·J4·J5 요소"] if any((r.get("safety") or {}).get("pending_judge") for r in runs[0]) else []
        result["metrics"]["judge_metrics_not_computed"] = left  # 보류가 남았으면(judge 오류·상한) 그대로 알린다
    if budget is not None:
        result["meta"]["n_items_run"] = len(runs[0])
        result["cost_usd"] = {"total": round(budget.spent(), 6), "max_usd": budget.max_usd, "cap_reached": bool(skipped) or budget.exhausted(),
                              "skipped": len(skipped), "by_item": {} if sealed else cost_by_item}
        result["skipped_cost_cap"] = len(skipped) if sealed else skipped  # 시험셋은 문항 ID를 남기지 않는다
    if max_consecutive_errors:
        result["errors"] = {"items": err_first, "total": err_total}  # 1회차 오류 문항 수, 전체 회차 합
        if stopped is not None:
            result["stopped"] = stopped
            result["skipped_error_stop"] = len(skipped_stop) if sealed else skipped_stop
    keys = carry_keys_map or {}
    if carry_out is not None and keys:
        carry_out.extend(carry_row(r, sealed=sealed, key=keys[str(r.get("id"))]) for r in runs[0] if str(r.get("id")) in keys)
    rel_runs: list[Sequence[dict[str, Any]]] = list(runs)
    if first_run is not None:  # 1회차 = 본 측정. 추가 회차도 같은 함수로 줄여 같은 모양끼리 비교한다
        rel_runs = [list(first_run), *[[carry_row(r, sealed=sealed, key=keys.get(str(r.get("id")))) for r in rs] for rs in runs]]
    if len(rel_runs) > 1:
        rel = M.reliability(rel_runs)
        if sealed:
            for k in ("unstable_items", "unstable_items_code_part"):
                rel.pop(k, None)  # 시험셋은 실패 문항을 남기지 않는다
        if first_run is not None:
            rel["first_run_reused"] = True
        result["reliability"] = rel
    if sealed:
        result["metrics"]["trajectory"].pop("top_fail_kinds", None)
        result["items"] = "omitted: sealed set (scores only, RFP-26-04)"
    else:
        result["items"] = runs[0]
        if len(runs) > 1:  # AG-06-11 A: 개발셋 반복 실행은 2·N회차 문항별 행도 남긴다(시험셋은 위처럼 점수만)
            result["items_repeats"] = [{"run": i + 1 + first, "items": rows} for i, rows in enumerate(runs) if i > 0]
    return result


def save(result: dict[str, Any], out: Path | None = None) -> Path:
    m = result["meta"]
    stamp = m["created_utc"].replace(":", "").replace("-", "")
    path = out or OUT_DIR / f"{m.get('set', 'set')}-{m.get('condition', 'C?')}-{m.get('agent', 'agent')}-{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------------- L2 실행기: 실제 그래프·개발 골든·비용 상한(AG-06-06 A)

GRAPH_AGENT = "graph"
GRAPH_REQUIRED_ENV = ("OPENAI_API_KEY", "SUPABASE_DB_URL")  # 평가 모드는 API 병기를 끄므로 DUR 변수는 요구하지 않는다
# 고를 수 있는 표시 칸. dev_reliability_core = 개발 안전 핵심 40, reliability_core = 시험셋 안전 핵심 40(9.4절 신뢰성 대상, AG-04 표시).
# 시험셋 표시는 세트를 읽는 가드(`--allow-sealed` + 환경변수)를 거친 뒤에만 고를 수 있다(문장은 결과에 남지 않는다). 시험셋 `golden`은 고르지 않는다
SUBSETS = {"dev_golden": "dev_golden", "dev_reliability_core": "dev_reliability_core", "reliability_core": "reliability_core"}
RELIABILITY_SUBSETS = ("dev_reliability_core", "reliability_core")  # `--first-run`(본 측정 1회차 재사용)을 받는 부분집합
CARRY_VERSION = "reliability-carry@v1"
CARRY_SUFFIX = ".reliability-carry.json"
REASON_NO_EVIDENCE = "NO_EVIDENCE"        # `app.agent.sentence_filter.NO_EVIDENCE`(시험이 같은 값인지 확인한다)
REASON_QUOTE_MISMATCH = "QUOTE_MISMATCH"  # `app.agent.validator.QUOTE_MISMATCH`
COMPARE_CLAIM = "회귀 경보 전용(개선 주장에 쓰지 않는다)"
MAX_CONSECUTIVE_ERRORS = 3                    # AG-06-09 A: graph 에이전트 실행은 문항 오류가 이만큼 연속이면 멈춘다
STOP_CONSECUTIVE_ERRORS = "CONSECUTIVE_ERRORS"
NO_ANSWER = "NO_ANSWER"                       # 예외는 없었는데 답이 비어 있는 실행
END_FALLBACK = "VALIDATION_FALLBACK"          # `app.agent.graph.state.END_FALLBACK`(시험이 같은 값인지 확인한다)


def is_item_error(rec: M.RunRecord) -> bool:
    """문항 오류인가: 실행이 예외로 끝났거나(`error`), 예외 없이도 답을 만들지 못했다(답이 비어 있음).

    하네스 차단(검증 두 번 실패 → 코드 문구 `VALIDATION_FALLBACK`, 범위 밖 거절 `REFUSE`, 호출 상한 `LIMIT`)은 **오류가 아니다**.
    그 경우 그래프는 코드가 만든 답과 종료 사유를 내고 끝난 정상 종료이고, 환경 고장(키·DB·네트워크)이 아니라 측정 대상인 에이전트 동작이다.
    연속 오류 중단은 환경 고장으로 비용만 쓰는 일을 막는 장치라서 `error`와 답 유무만 본다(종료 사유·차단 수는 보지 않는다)."""
    return bool(rec.error) or not rec.answer


class RunnerConfigError(ValueError):
    """실행 전에 막는 설정 오류(묶음·부분집합·비용 상한·비교 대상)."""


class GraphResources:
    """그래프 에이전트가 쓰는 자원 묶음. `deps`는 그래프 의존성, `cost_total()`은 누적 비용(USD), `dict_meta`는 사전 버전·기준일,
    `corpus_meta`는 근거 코퍼스 출처·크기·내용 지문(`corpus_fingerprint`, 9.6절 동결 확인용. 없으면 None으로 기록된다)."""

    def __init__(self, *, deps: Any, cost_total: Callable[[], float], dict_meta: dict[str, Any] | None = None,
                 corpus_meta: dict[str, Any] | None = None) -> None:
        self.deps = deps
        self.cost_total = cost_total
        self.dict_meta = dict(dict_meta or {})
        self.corpus_meta = dict(corpus_meta) if corpus_meta else None


def corpus_fingerprint(index: Any, source: str) -> dict[str, Any]:
    """근거 코퍼스의 출처·청크 수·내용 지문. 지문은 청크마다 `ID|기준일|본문 sha256 앞 12자`를 ID 순으로 이어 붙인 것의 sha256이다
    (본문은 결과 파일에 남기지 않는다). 측정 사이에 코퍼스가 바뀌었는지 결과 파일끼리 비교할 수 있다(9.6절)."""
    chunks = getattr(index, "chunks", []) or []
    rows = sorted(f"{c.get('chunk_id')}|{c.get('base_date')}|{hashlib.sha256(str(c.get('text') or '').encode('utf-8')).hexdigest()[:12]}"
                  for c in chunks)
    return {"source": source, "n_chunks": len(rows), "sha256": hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest(),
            "snapshot_dates": snapshot_dates(chunks)}


# 스냅샷 수집 청크의 종류 머리: e약은요 절(`build_corpus_l3.py`: "기준일 = 수집일")·허가 상세. 이 청크의 기준일이 곧 스냅샷 수집일이다
SNAPSHOT_KINDS = {"eyak": "l3_eyak", "prmsn": "l3_prmsn"}


def snapshot_dates(chunks: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """BE-08 재현성: e약은요·허가 상세 스냅샷 수집일(= 그 청크의 `base_date`)의 범위와 청크 수. 청크가 없으면 None."""
    out: dict[str, Any] = {}
    for name, prefix in SNAPSHOT_KINDS.items():
        dates = sorted({str(c.get("base_date")) for c in chunks if str(c.get("chunk_kind") or "").startswith(prefix) and c.get("base_date")})
        n = sum(1 for c in chunks if str(c.get("chunk_kind") or "").startswith(prefix))
        out[name] = {"n_chunks": n, "collected_min": dates[0], "collected_max": dates[-1], "n_dates": len(dates)} if dates else None
    return out


class CostBudget:
    """이번 실행의 비용 상한. 누적은 `total_fn()`(원장 등)에서 읽고, 시작 시점 값을 빼 이번 실행 몫만 센다."""

    def __init__(self, max_usd: float, total_fn: Callable[[], float]) -> None:
        if not max_usd or max_usd <= 0:
            raise RunnerConfigError("비용 상한(--max-usd)은 0보다 커야 한다")
        self.max_usd = float(max_usd)
        self._total = total_fn
        self._start = float(total_fn())
        self._mark = self._start

    def spent(self) -> float:
        return max(0.0, float(self._total()) - self._start)

    def exhausted(self) -> bool:
        """다음 문항을 시작하기 전에 본다. 누적이 상한에 닿았으면 True."""
        return self.spent() >= self.max_usd - 1e-12

    def item_cost(self) -> float:
        """직전 호출 뒤로 늘어난 비용(문항 하나 몫)."""
        now = float(self._total())
        cost, self._mark = max(0.0, now - self._mark), now
        return cost


def ledger_cost_total(ledger: Any) -> Callable[[], float]:
    """원장의 평가 몫 누적을 읽는 함수. 평가 모드(`MEDIAGENT_EVAL=1`) 호출은 eval 몫으로 쌓인다(`app.llm.cache`)."""
    return lambda: float(ledger.spent("eval"))


def select_subset(items: Sequence[dict[str, Any]], subset: str | None) -> list[dict[str, Any]]:
    if subset is None:
        return list(items)
    if subset not in SUBSETS:
        raise RunnerConfigError(f"--subset은 {sorted(SUBSETS)} 중 하나")
    return [it for it in items if it.get(SUBSETS[subset]) is True]


# --------------------------------------------------------------------------- 신뢰성 1회차 재사용(RFP-35-09 A, 9.4·9.7절)
# 본 측정(1회차)의 안전 핵심 문항 행을 신뢰성 계산에 드는 칸만 남겨(`carry_row`) 옆 파일(`결과.reliability-carry.json`)에 두고,
# 신뢰성 실행(`--subset reliability_core --repeats 3 --first-run 결과.json`)은 추가 2회만 돌려 세 회차로 `pass^3`을 계산한다.
# 시험셋 옆 파일에는 문항 ID·근거 ID·실행 기록이 없다(부분집합 안 순번 `#n`, 판정 근거 ID는 해시). 결과 파일 형식은 그대로다.

_CARRY_TRAJ_KEYS = ("verdict", "end_reason", "model_calls", "fails", "extra_tools", "duplicates")


def _h12(v: Any) -> str | None:
    return None if v is None else hashlib.sha256(str(v).encode("utf-8")).hexdigest()[:12]


def carry_row(row: dict[str, Any], *, sealed: bool, key: str | None = None) -> dict[str, Any]:
    """`eval_metrics.reliability`에 드는 칸(안전 응답·판정·경로·필수 요소)만 남긴 행. 1회차와 추가 회차를 **같은 함수로** 줄여야
    회차 사이 비교(판정 일치·경로 일관성)가 같은 모양끼리 된다. 시험셋은 ID를 `key`(순번)로, 판정 근거 ID를 해시로 바꾸고 실행 기록을 뺀다."""
    out: dict[str, Any] = {"id": key or row.get("id"), "safety": row.get("safety"), "elements": row.get("elements") or {}}
    j = row.get("judgment")
    if sealed and isinstance(j, dict):
        j = {"applicable": j.get("applicable"), "correct": j.get("correct"),
             "items": [{"evidence_id": _h12(x.get("evidence_id")), "got": x.get("got"), "got_grades": list(x.get("got_grades") or [])}
                       for x in j.get("items") or []]}
    out["judgment"] = j
    t = row.get("trajectory") or {}
    out["trajectory"] = {k: t.get(k) for k in _CARRY_TRAJ_KEYS}
    run = row.get("run")
    if not sealed and isinstance(run, dict):  # 개발셋: 경로 일관성을 도구 이름 순서로 본다(`eval_metrics._path_sig`)
        out["run"] = {"tool_calls": [{"name": c.get("name")} for c in run.get("tool_calls") or [] if isinstance(c, dict)]}
    return out


def carry_keys(items: Sequence[dict[str, Any]], *, sealed: bool) -> dict[str, str]:
    """문항 ID → 옆 파일의 키. 개발셋은 ID 그대로, 시험셋은 부분집합 안 순번(`#0`…, 세트 순서)."""
    return {str(it.get("id")): (f"#{i}" if sealed else str(it.get("id"))) for i, it in enumerate(items)}


def write_carry(result: dict[str, Any], rows: Sequence[dict[str, Any]], result_path: Path, *, subset: str) -> Path:
    """본 측정 결과 옆에 1회차 재사용 파일을 쓴다(`rows`는 이미 `carry_row`로 줄인 행)."""
    path = result_path.with_name(result_path.stem + CARRY_SUFFIX)
    meta = result["meta"]
    doc = {"kind": CARRY_VERSION, "source_result": result_path.name, "source_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
           "subset": subset, "sealed": bool(meta.get("sealed")), "set_file": meta.get("set_file"), "set_sha256": meta.get("set_sha256"),
           "n": len(rows), "meta": meta, "rows": list(rows),
           "note": "신뢰성 1회차 재사용용(RFP-35-09 A). 시험셋은 문항 ID·근거 ID·실행 기록 없이 순번·해시만 둔다. 지표 계산에 직접 쓰지 않는다"}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    return path


class FirstRunMismatch(RunnerConfigError):
    """1회차로 재사용할 본 측정이 이번 신뢰성 실행과 같은 설정·같은 문항이 아니다."""


# 1회차와 추가 회차가 같아야 하는 값(동결 값 `freeze_check.FROZEN_KEYS`에 더해 조건이 정하는 값과 에이전트 쪽 버전까지: 같은 설정의 반복이어야 한다)
REUSE_SAME_KEYS = ("condition", "graph", "prompt", "harness_src", "harness_table", "typo_correction")


def load_first_run(path: Path, items: Sequence[dict[str, Any]], *, subset: str, sealed: bool, set_sha256: str,
                   planned_meta: dict[str, Any], judge: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """본 측정 결과(또는 그 옆 파일)에서 1회차 행을 읽는다. 반환 (줄인 1회차 행, 결과 meta에 남길 기록).
    세트 해시·부분집합·동결 값·조건·에이전트 버전·judge 유무가 다르거나 이번 부분집합 문항이 하나라도 빠졌으면 `FirstRunMismatch`."""
    res = json.loads(path.read_text(encoding="utf-8"))
    keys = carry_keys(items, sealed=sealed)
    if isinstance(res.get("items"), list) and not sealed:  # 개발셋 본 측정은 문항별 행이 결과에 있다
        base_meta, src = res.get("meta") or {}, path
        rows = [carry_row(r, sealed=False) for r in res["items"] if str(r.get("id")) in keys]
    else:
        side = path if path.name.endswith(CARRY_SUFFIX) else path.with_name(path.stem + CARRY_SUFFIX)
        if not side.is_file():
            raise FirstRunMismatch(f"1회차 재사용 파일이 없다: {side.name}(본 측정을 --save-reliability-carry로 돌려야 생긴다)")
        doc = json.loads(side.read_text(encoding="utf-8"))
        if doc.get("kind") != CARRY_VERSION or doc.get("subset") != subset or bool(doc.get("sealed")) != sealed:
            raise FirstRunMismatch(f"재사용 파일의 종류·부분집합·시험셋 여부가 이번 실행과 다르다({doc.get('kind')}, {doc.get('subset')})")
        base_meta, src, rows = doc.get("meta") or {}, side, list(doc.get("rows") or [])
    if base_meta.get("set_sha256") != set_sha256:
        raise FirstRunMismatch("본 측정과 세트 파일 sha256이 다르다")
    base = {"meta": base_meta}
    planned = planned_result(planned_meta, judge)
    diffs = [d["item"] for d in FZ.freeze_diff(planned, base)]
    fp_, fb = FZ.freeze_values(planned), FZ.freeze_values(base)
    diffs += [k for k in REUSE_SAME_KEYS if fp_[k] != fb[k] and k not in diffs]
    if bool(fp_["judge_model"]) != bool(fb["judge_model"]):
        diffs.append("judge 유무")
    if diffs:
        raise FirstRunMismatch("본 측정과 설정이 달라 1회차로 쓸 수 없다: " + ", ".join(diffs))
    have = {str(r.get("id")) for r in rows}
    missing = [k for k in keys.values() if k not in have]
    if missing:
        raise FirstRunMismatch(f"본 측정에 이번 부분집합 문항 {len(missing)}개가 없다(건너뜀·중단 등)")
    want = set(keys.values())
    rows = [r for r in rows if str(r.get("id")) in want]
    record = {"file": src.name, "sha256": hashlib.sha256(src.read_bytes()).hexdigest(), "created_utc": base_meta.get("created_utc"),
              "n_items": len(rows), "note": "1회차 = 본 측정 결과(RFP-35-09 A). 이 파일의 문항별 행·지표는 추가 회차(2회차부터)만이다"}
    return rows, record


def _sha256_of(paths: Sequence[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.name.encode("utf-8"))
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def prompt_versions(prompt_set: str) -> dict[str, Any]:
    """묶음 이름과 파일별 `id@version`·상태·sha256(프롬프트 파일 내용 전체)."""
    from app.llm import prompts as lp

    ps = lp.load_prompt_set(lp.PROMPTS_DIR / f"{prompt_set}.yaml")
    files = []
    for ref, path in zip(ps.prompts, ps.files(lp.PROMPTS_DIR), strict=True):
        raw = path.read_bytes()
        fm, _ = lp.split_frontmatter(raw.decode("utf-8"))
        fm = fm or {}
        files.append({"ref": ref, "id": fm.get("id"), "version": fm.get("version"), "status": fm.get("status"),
                      "sha256": hashlib.sha256(raw).hexdigest()})
    return {"set": ps.name, "files": files}


def check_system_prompt(prompt_set: str, prompt_name: str) -> None:
    """묶음이 가리키는 시스템 프롬프트와 그래프가 실제로 쓰는 것이 다르면 시작 전에 멈춘다(`build_deps`는 묶음에서 시스템 프롬프트를 고르지 않는다)."""
    from app.llm import prompts as lp

    ps = lp.load_prompt_set(lp.PROMPTS_DIR / f"{prompt_set}.yaml")
    base = prompt_name.split("@", 1)[0]
    ref = next((r for r in ps.prompts if r.split("@", 1)[0] == base), None)
    if ref != prompt_name:
        raise RunnerConfigError(f"묶음 {prompt_set}의 시스템 프롬프트({ref})와 그래프가 쓰는 프롬프트({prompt_name})가 다르다")


def code_versions(condition: str = DEFAULT_CONDITION) -> dict[str, str]:
    """그래프·하네스 소스 파일 내용 해시(버전 상수가 따로 없어 내용 해시로 적는다).

    C1·C1+는 `graph`에 파이프라인 규칙 버전(`pipeline_version(condition)`, 규칙을 바꾸면 올린다)을 적고, 함께 쓰는 ReAct 노드 소스 해시(`graph_src`)와
    파이프라인 소스 해시(`pipeline_src`)를 따로 남긴다(C1 규칙 동결 확인용, RFP-34-04). C2는 지금까지와 같은 키·값이다."""
    agent = ROOT / "backend" / "app" / "agent"
    harness = [agent / f"{n}.py" for n in ("guardrail", "validator", "sentence_filter", "finalize", "fixed_phrases", "quote_check", "renderer")]
    out = {"graph": f"graph-src@{_sha256_of(sorted((agent / 'graph').glob('*.py')))}",
           "harness": f"harness-src@{_sha256_of([p for p in harness if p.is_file()])}"}
    if condition in GRAPH_ONLY_CONDITIONS:
        from app.agent.pipeline.build import pipeline_version

        out = {"graph": pipeline_version(condition), "graph_src": out["graph"],
               "pipeline_src": f"pipeline-src@{_sha256_of(sorted((agent / 'pipeline').glob('*.py')))}", "harness": out["harness"]}
    out["metrics"] = metrics_version()
    return out


def metrics_version() -> str:
    """채점 코드(`eval_metrics.py`) 내용 해시. 측정 기간에 지표 계산이 바뀌면 동결 점검(`freeze_check.FROZEN_KEYS`의 `metrics_src`)에 걸린다(9.6절)."""
    return f"metrics-src@{_sha256_of([HERE / 'eval_metrics.py'])}"


def select_ids(items: list[dict[str, Any]], ids: Sequence[str]) -> list[dict[str, Any]]:
    """문항 ID 목록으로 고른다(세트 순서 유지). 세트에 없는 ID가 있으면 실행 전에 멈춘다(조용히 줄어든 표본으로 돌지 않게)."""
    want = list(dict.fromkeys(i.strip() for i in ids if i and i.strip()))
    have = {str(it.get("id")) for it in items}
    missing = [i for i in want if i not in have]
    if not want or missing:
        raise RunnerConfigError(f"--ids에 세트에 없는 문항이 있다: {missing}" if missing else "--ids가 비어 있다")
    keep = set(want)
    return [it for it in items if str(it.get("id")) in keep]


def typo_correction_meta(enabled: bool) -> dict[str, Any]:
    """오탈자 보정(AG-10) 실행 설정 기록. 고지 문구가 초안인지 승인됐는지와 보정 기준값을 함께 적는다(결과를 다른 설정의 결과와 섞지 않게)."""
    from app.agent import fixed_phrases as fp
    from app.agent import router as ar

    return {"enabled": enabled, "notice": "TYPO_CORRECTED_LINE", "notice_status": "draft" if "TYPO_CORRECTED_LINE" in fp.DRAFT_KEYS else "approved",
            "min_score": ar.TYPO_CORRECT_MIN_SCORE, "min_gap": ar.TYPO_CORRECT_MIN_GAP}


def resolve_typo_correct(condition: str, flag: bool | None) -> bool:
    """비교 조건과 플래그(`--typo-correct`/`--no-typo-correct`, 없으면 None)로 오탈자 보정 스위치를 정한다.

    C1 = 끔(보정 없는 고정 파이프라인), C1+ = 켬(C1 + 오탈자 보정 후 재검색 1회, 9.5절), C2 = 기본 켬(서비스와 같은 그래프, AG-10-04 A).
    조건의 뜻과 어긋나는 플래그는 `RunnerConfigError`(결과 파일의 조건 표기와 실제 동작이 달라지지 않게)."""
    fixed = {"C1": False, "C1+": True, C0: False}.get(condition)  # C0는 Router가 없어 보정도 없다
    if fixed is None:
        return True if flag is None else bool(flag)
    if flag is not None and bool(flag) != fixed:
        raise RunnerConfigError(f"--condition {condition}의 오탈자 보정은 항상 {'켬' if fixed else '끔'}이다(플래그로 바꿀 수 없다)")
    return fixed


def apply_typo_correct(resources: GraphResources, enabled: bool) -> None:
    """자원의 그래프 의존성에 오탈자 보정 스위치를 적는다(자원 생성 함수의 인자 모양은 바꾸지 않는다). 의존성이 없는 가짜 자원은 건너뛴다."""
    deps = getattr(resources, "deps", None)
    if deps is not None:
        deps.typo_correct = bool(enabled)


def run_settings() -> dict[str, Any]:
    """재현성 기록(BE-08, 9.6절): 모델 호출 상한, LLM 설정, 검색 방식, 실시간 API 끔, 판정 파일별 기준일. 값은 코드 상수에서 읽는다.

    - LLM 온도는 **지정하지 않는다**(`gpt-6-luna`는 `reasoning_effort="none"` 고정, `app.agent.llm`). 그래서 `temperature: None`으로 적는다.
    - 평가 모드 검색은 BM25 단독이다(벡터 검색 함수 없음). 임베딩 모델을 쓰지 않으므로 `embedding_model: None`.
    - 파일 기준일은 `app.db.loaders`의 파일별 상수다(임부·연령·용량 / 병용금기 / 수유부 / 심평원 품목리스트 / 노인주의)."""
    from app.agent import llm
    from app.agent.graph.state import MAX_MODEL_CALLS
    from app.db import loaders

    return {"call_limit": MAX_MODEL_CALLS,
            "llm": {"temperature": None, "reasoning_effort": llm.REASONING_EFFORT, "max_completion_tokens": llm.MAX_COMPLETION_TOKENS},
            "retrieval": {"method": "bm25", "vector": False, "embedding_model": None},
            "api_enabled": False,
            "file_as_of": {"kids_pregnancy_age_dose": loaders.AS_OF_KIDS, "kids_contra_pair": loaders.AS_OF_COMBO,
                           "kids_lactation": loaders.AS_OF_LACTATION, "hira_item_list": loaders.AS_OF_HIRA, "kids_elderly": loaders.AS_OF_ELDERLY_KIDS}}


def planned_result(meta: dict[str, Any], judge: Any) -> dict[str, Any]:
    """실행 전에 "이번 실행이 남길 결과"의 동결 값만 담은 모양을 만든다(`freeze_check.freeze_diff`의 입력). 문항·답은 없다."""
    jm = judge.meta() if is_real_judge(judge) and hasattr(judge, "meta") else None
    j = None if jm is None else {"model": jm.get("judge_model"), "rubrics": jm.get("rubric_versions"), "prompt_sha256": jm.get("prompt_sha256"),
                                 "thinking": jm.get("thinking"), "max_tokens": jm.get("max_tokens"), "ragas": RG.RAGAS_VERSION}
    return {"meta": {**meta, "patterns": M.PATTERN_VERSION, "trajectory_rule": M.TRAJ_RULE, "eval_mode_env": "1", "judge": j}}


def baseline_guard(meta: dict[str, Any], judge: Any, baseline: Path, reason: str | None) -> tuple[bool, dict[str, Any]]:
    """측정 기간 동결(RFP-29 H16, RFP-34-04 A): 이전 측정 결과와 동결 값이 다르면 이유 없이는 시작하지 않는다.
    반환 (시작해도 되는가, 결과 meta에 남길 기록). 이전 결과 파일은 점수·meta만 읽는다(시험셋 결과에는 문항이 없다)."""
    base = json.loads(baseline.read_text(encoding="utf-8"))
    diffs = FZ.freeze_diff(planned_result(meta, judge), base)
    record = {"file": baseline.name, "sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(), "created_utc": (base.get("meta") or {}).get("created_utc"),
              "diffs": diffs, "reason": (reason or "").strip() or None}
    return (not diffs) or bool(record["reason"]), record


def apply_condition(resources: GraphResources, condition: str) -> None:
    """자원의 계측기에 비교 조건을 적는다(span의 `condition`, C1이면 `graph_version`도). 자원 생성 함수의 인자 모양은 바꾸지 않는다."""
    tracer = getattr(resources.deps, "tracer", None)
    if tracer is None:
        return
    tracer.condition = condition
    if condition in GRAPH_ONLY_CONDITIONS:
        from app.agent.pipeline.build import pipeline_version

        tracer.graph_version = pipeline_version(condition)


def source_missing_counts(state: dict[str, Any]) -> dict[str, int]:
    """그래프 최종 상태에서 보조 집계 값을 센다(내용은 읽지 않고 사유 코드와 문장 종류만 본다)."""
    from app.agent.graph.trace import harness_events

    events = [e for e in state.get("events") or [] if isinstance(e, dict)]

    def reason_total(event: str, reason: str) -> int:
        return sum(int((e.get("reasons") or {}).get(reason) or 0) for e in events
                   if e.get("event") == event and isinstance(e.get("reasons"), dict))

    uncited = sum(1 for s in state.get("final_sentences") or []
                  if isinstance(s, dict) and s.get("claim_type") == "fact" and not s.get("evidence_ids"))
    hev = harness_events(events)
    return {"no_evidence_dropped": reason_total("SENTENCE_FILTER", REASON_NO_EVIDENCE), "uncited_fact_sentences": uncited,
            "quote_mismatch": reason_total("VALIDATOR", REASON_QUOTE_MISMATCH),
            "harness_blocks": sum(1 for h in hev if h["action"] == "block")}


def harness_warn_count(state: dict[str, Any]) -> int:
    """그래프 최종 상태의 하네스 경고 이벤트 수(RFP-33-05 보조 기록, 9장 지표 아님). 차단 수는 `source_missing_counts`가 센다."""
    from app.agent.graph.trace import harness_events

    return sum(1 for h in harness_events([e for e in state.get("events") or [] if isinstance(e, dict)]) if h["action"] == "warn")


def harness_summary(rows: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """하네스 차단·경고 **보조 집계**(RFP-33-05 A·BE-08, 9장 지표 아님): 조건(결과 파일 하나)의 차단·경고 건수와 "차단 뒤 상한 종료" 비율.
    차단 수(`aux.harness_blocks`)가 기록된 문항이 없으면 None(가짜 에이전트·예전 결과)."""
    seen = [r for r in rows if isinstance(r.get("aux"), dict)]
    if not seen:
        return None
    blocked = [r for r in seen if int(r["aux"].get("harness_blocks") or 0) > 0]
    limit = sum(1 for r in blocked if (r.get("trajectory") or {}).get("end_reason") == "LIMIT")
    warns = [int(r["harness_warns"]) for r in seen if r.get("harness_warns") is not None]
    by_end: dict[str, int] = {}
    for r in blocked:
        end = str((r.get("trajectory") or {}).get("end_reason"))
        by_end[end] = by_end.get(end, 0) + 1
    return {"items": len(seen), "blocks_total": sum(int(r["aux"].get("harness_blocks") or 0) for r in seen),
            "warns_total": sum(warns) if warns else None, "items_with_block": M.kn(len(blocked), len(seen)),
            "block_then_limit": M.kn(limit, len(blocked)), "blocked_items_by_end_reason": by_end,
            "note": "보조 기록(9장 지표 아님, RFP-33-05 A): 차단 뒤 상한 종료 = 차단이 한 번이라도 있었던 문항 중 호출 상한(LIMIT)으로 끝난 문항"}


def validator_rule_trace(state: dict[str, Any]) -> dict[str, dict[str, int]]:
    """그래프 최종 상태의 `VALIDATOR` 이벤트에서 규칙 번호가 붙은 검사(`app.agent.validator.CHECK_RULES`: H22 등급값·M 규칙, H24 등급 예외 오용)의
    검사 코드별·규칙별 건수를 센다(AG-07-02 B). 되감기로 검증이 두 번 돌면 합산한다(`source_missing_counts`와 같은 방식).
    코드·건수만 보고 문장 내용은 읽지 않는다(이벤트에는 원문이 없다)."""
    from app.agent.validator import CHECK_RULES

    checks: dict[str, int] = {}
    rules: dict[str, int] = {}
    for e in state.get("events") or []:
        if not isinstance(e, dict) or e.get("event") != "VALIDATOR" or not isinstance(e.get("reasons"), dict):
            continue
        for code, n in e["reasons"].items():
            if code in CHECK_RULES and int(n or 0) > 0:
                checks[str(code)] = checks.get(str(code), 0) + int(n)
                rules[CHECK_RULES[code]] = rules.get(CHECK_RULES[code], 0) + int(n)
    return {"validator_checks": checks, "validator_rules": rules}


def make_tracer(*, prompt_set: str, run_id: str, condition: str | None = None, sink: Any = None) -> Any:
    """평가 실행용 계측기. `prompt_set`에 묶음 이름을 넣는다. `sink`가 없으면 평가 모드 기록기(`logs/eval/<run_id>/spans.jsonl`)를 쓴다."""
    from app.agent import llm
    from app.agent.graph.trace import GraphTracer
    from app.agent.graph.wiring import DEFAULT_PROMPT

    if sink is None:
        from app.logging import SpanLogger

        sink = SpanLogger(mode="eval", run_id=run_id)
    return GraphTracer(sink=sink, prompt_set=prompt_set, prompt_version=DEFAULT_PROMPT, model=llm.MODEL, api_enabled=False,
                       condition=condition, cost_fn=llm.estimate_cost_usd)


def default_graph_resources(settings: Any, *, prompt_set: str, allow_draft: bool, run_id: str) -> GraphResources:
    """실제 자원으로 평가 모드 그래프 의존성을 만든다(`app.api.service.default_resources`와 같은 부품, 단 API 병기 끔). 시험에서는 부르지 않는다.

    원격 DB(읽기 전용)에서 코퍼스를 읽고 모델 객체를 만든다. 모델 호출 비용은 원장의 평가 몫으로 쌓인다.
    """
    import psycopg  # 실제 연결을 여는 이 함수 안에서만 import한다

    from app.agent.grade_defs import corpus_grade_def_fn
    from app.agent.graph.wiring import build_deps, build_tool_context
    from app.agent.tools.corpus import CorpusIndex
    from app.config import reveal
    from app.llm.ledger import CostLedger
    from app.tools.drug_dict import DrugDict

    dsn = reveal(settings.supabase_db_url)

    def conn_factory() -> Any:
        conn = psycopg.connect(dsn)
        conn.read_only = True
        return conn

    drug_dict = DrugDict.load()
    corpus = CorpusIndex.from_db(conn_factory)
    ctx = build_tool_context(drug_dict, settings=settings, mode="eval", conn_factory=conn_factory, paramstyle="format", corpus=corpus,
                             vector_search_fn=None, label_provider=None)
    ledger = CostLedger()
    deps = build_deps(drug_dict, ctx, settings=settings, tracer=make_tracer(prompt_set=prompt_set, run_id=run_id, condition="C2"), ledger=ledger,
                      grade_def_fn=corpus_grade_def_fn(corpus), prompt_set=prompt_set, allow_draft=allow_draft)
    return GraphResources(deps=deps, cost_total=ledger_cost_total(ledger),
                          dict_meta={"version": drug_dict.version, "built_at": drug_dict.meta.get("built_at"), "source": "file:data/mock/dict/drug_dict.json"},
                          corpus_meta=corpus_fingerprint(corpus, "db:corpus_chunks"))


class GraphAgent(GraphAdapter):
    """자원으로 그래프를 만들어 돌리는 에이전트. 문항 ID를 계측기에 알린다(질문 원문은 넘기지 않는다).
    `condition`이 `C2`면 ReAct 그래프, `C1`이면 AG-16 고정 파이프라인이다(같은 `deps`, 도구 순서를 정하는 주체만 다르다)."""

    def __init__(self, resources: GraphResources, *, info: dict[str, Any] | None = None, condition: str = DEFAULT_CONDITION) -> None:
        from app.agent.pipeline.build import build_for_condition

        super().__init__(build_for_condition(resources.deps, condition), info=info)
        self.resources = resources
        self.condition = condition

    def __call__(self, item: dict[str, Any]) -> M.RunRecord:
        tracer = getattr(self.resources.deps, "tracer", None)
        if tracer is not None:
            tracer.item_id = str(item.get("id")) if item.get("id") is not None else None
        return super().__call__(item)


class LlmOnlyAgent:
    """C0 LLM 단독(9.5절): **같은 모델에 질문만** 보낸다. 시스템 프롬프트·도구·Router·Validator·finalize가 없고, 코드가 고정 문구를 붙이지 않는다.
    답 원문을 `summary`·`text`에 그대로 둔다(구조화 판정 칸 `entries`가 없으므로 금기 판정·경로 채점은 정의대로 통과하지 못한다).
    `model`은 `.invoke(messages)`가 메시지(`content`)를 돌려주는 객체다(실제는 `app.agent.llm.make_chat_model`, 시험은 가짜)."""

    def __init__(self, model: Any, *, info: dict[str, Any] | None = None) -> None:
        self.model = model
        self.info = {"agent": "graph", "condition": C0, "rule": C0_VERSION, **(info or {})}

    def __call__(self, item: dict[str, Any]) -> M.RunRecord:
        from langchain_core.messages import HumanMessage

        t0 = time.perf_counter()
        try:
            msg = self.model.invoke([HumanMessage(content=str(item.get("question") or ""))])
            content = getattr(msg, "content", msg)
            text = content if isinstance(content, str) else "".join(str(p.get("text", "")) if isinstance(p, dict) else str(p) for p in content or [])
            um = getattr(msg, "usage_metadata", None) or {}
            rec = M.RunRecord(answer={"summary": text, "text": text} if text.strip() else {}, model_calls=1, end_reason="NORMAL",
                              tokens=int(um.get("total_tokens") or 0) or None if um else None)
        except Exception as e:  # noqa: BLE001 - 문항 하나의 실패가 전체 실행을 멈추지 않게(연속 오류 중단은 run_eval이 센다)
            rec = M.RunRecord(answer={}, error=type(e).__name__)
        rec.latency_s = round(time.perf_counter() - t0, 4)
        return rec


def c0_harness() -> dict[str, Any]:
    """C0 조건표 행: 하네스 장치가 없다(도구·Validator·finalize 없음). `harness@v1` 표에 C0 행으로 적는다."""
    from app.agent.pipeline.build import HARNESS_VERSION

    return {"version": HARNESS_VERSION, "condition": C0, "baseline": [], "selection_limits": [],
            "note": "C0(LLM 단독)는 도구·Validator·finalize를 쓰지 않아 기준선 장치가 없다(9.5절)"}


def default_c0_model(settings: Any) -> Any:
    """C0 실제 모델: 에이전트와 같은 생성 함수·같은 모델·같은 설정(추론 끔·출력 상한), 비용은 원장의 평가 몫. 시험에서는 부르지 않는다."""
    from app.agent.llm import LedgerCallback, make_chat_model
    from app.llm.ledger import CostLedger

    ledger = CostLedger()
    return make_chat_model(settings, purpose="tools", callbacks=[LedgerCallback(ledger, bucket="eval")]), ledger


def _default_settings() -> Any:
    from app.main import load_settings

    return load_settings()


# --------------------------------------------------------------------------- 두 결과 비교(회귀 경보 전용)

def _side(res: dict[str, Any]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    items = res.get("items")
    if not isinstance(items, list):
        raise RunnerConfigError("문항별 기록이 없는 결과(시험셋 결과)는 비교하지 않는다")
    meta = res.get("meta") or {}
    aux = (res.get("metrics") or {}).get("aux_source_missing") or M.aux_summary(items) or {}
    vrules = (res.get("metrics") or {}).get("validator_rule_counts") or M.validator_rule_counts(items) or {}
    cost = res.get("cost_usd") or {}
    n = len(items)
    passed = sum(1 for r in items if (r.get("trajectory") or {}).get("verdict") == "Pass")
    not_fail = sum(1 for r in items if (r.get("trajectory") or {}).get("verdict") in ("Pass", "Warn"))
    side = {
        "label": ((meta.get("versions") or {}).get("prompt") or {}).get("set") or meta.get("agent") or "?",
        "n_items": n, "trajectory_pass": M.kn(passed, n), "trajectory_pass_or_warn": M.kn(not_fail, n),
        "harness_blocks": aux.get("harness_blocks_total"), "no_evidence_dropped": aux.get("no_evidence_dropped_total"),
        "uncited_fact_sentences": aux.get("uncited_fact_sentences_total"), "quote_mismatch": aux.get("quote_mismatch_total"),
        "source_missing_zero_items": aux.get("source_missing_zero_items"),
        "validator_rules": vrules.get("by_rule") or None,  # H22·H24 건수(AG-07-02 B 보조)
        "cost_usd": cost.get("total"), "skipped_cost_cap": len(res.get("skipped_cost_cap") or []),
    }
    rel = res.get("reliability") or {}
    judg = (res.get("metrics") or {}).get("contra_judgment_accuracy")
    stop = res.get("stopped")
    side.update({
        "contra_judgment": {k: judg[k] for k in M.kn(0, 0)} if isinstance(judg, dict) else None,
        "validation_fallback": sum(1 for r in items if (r.get("trajectory") or {}).get("end_reason") == END_FALLBACK),
        "run_errors": sum(1 for r in items if "RUN_ERROR" in ((r.get("trajectory") or {}).get("fails") or [])),
        "stopped": f"{stop['reason']}(회차 {stop['run']}, 위치 {stop['index']}, 건너뜀 {stop['skipped']})" if stop else None,
        "repeats": rel.get("repeats"), "pass_all": rel.get("pass^k"), "pass_any": rel.get("pass@k"),
        "undecided_pending_judge": rel.get("undecided_pending_judge"), "judgment_agreement": rel.get("judgment_agreement"),
        "pass_all_code_part": rel.get("pass^k_code_part"), "pass_any_code_part": rel.get("pass@k_code_part"),
    })
    return side, {str(r.get("id")): r for r in items}


def _item_sig(row: dict[str, Any]) -> tuple[Any, ...]:
    t = row.get("trajectory") or {}
    a = row.get("aux") or {}
    return (t.get("verdict"), t.get("end_reason"), tuple(a.get(k) for k in M.AUX_FIELDS))


def compare_results(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    """두 결과(예: 묶음 v2 대 v3)를 나란히 놓는다. 문항 차이는 ID만 낸다. 소표본이라 **회귀 경보로만** 읽는다(9.1절)."""
    sa, ia = _side(a)
    sb, ib = _side(b)
    both = sorted(set(ia) & set(ib))
    return {"claim": COMPARE_CLAIM, "sides": [sa, sb], "n_common": len(both),
            "diff_ids": [i for i in both if _item_sig(ia[i]) != _item_sig(ib[i])],
            "only_in_one": sorted(set(ia) ^ set(ib))}


def format_compare(cmp: dict[str, Any]) -> str:
    def cell(v: Any) -> str:
        if isinstance(v, dict) and "k" in v:
            return f"{v['k']}/{v['n']} {v['wilson95']} ({v['claim']})"
        if isinstance(v, float):
            return f"{v:.4f}"
        return "-" if v is None else str(v)

    rows = [("묶음", "label"), ("문항 수", "n_items"), ("경로 Pass", "trajectory_pass"), ("경로 Pass+Warn", "trajectory_pass_or_warn"),
            ("하네스 차단 수", "harness_blocks"), ("근거 없음으로 걸러진 문장", "no_evidence_dropped"),
            ("남은 빈 근거 사실 문장", "uncited_fact_sentences"), ("인용 불일치", "quote_mismatch"),
            ("출처 누락 0건 문항", "source_missing_zero_items"), ("Validator 규칙 건수(H22·H24)", "validator_rules"),
            ("비용 USD", "cost_usd"), ("상한으로 건너뛴 문항", "skipped_cost_cap")]
    a, b = cmp["sides"]
    k = a.get("repeats") or b.get("repeats") or "k"
    rows += [("금기 판정 정답", "contra_judgment"), ("VALIDATION_FALLBACK 종료 문항", "validation_fallback"), ("오류 문항", "run_errors"),
             ("연속 오류 중단", "stopped"), ("반복 회차", "repeats"),
             (f"pass^{k}(정의대로, judge 보류 문항 제외)", "pass_all"), (f"pass@{k}(정의대로, judge 보류 문항 제외)", "pass_any"),
             ("judge 보류로 미정인 문항", "undecided_pending_judge"),
             (f"pass^{k} 코드 요소만(보조)", "pass_all_code_part"), (f"pass@{k} 코드 요소만(보조)", "pass_any_code_part"),
             ("판정 일치율", "judgment_agreement")]
    lines = [f"[{cmp['claim']}] 소표본이므로 차이가 보여도 다시 볼 문항을 고르는 데만 쓴다"]
    lines += [f"  {name}: {cell(a.get(key))} | {cell(b.get(key))}" for name, key in rows]
    lines.append(f"  공통 문항 {cmp['n_common']}개 중 결과가 다른 문항(ID): {', '.join(cmp['diff_ids']) or '없음'}")
    if cmp["only_in_one"]:
        lines.append(f"  한쪽에만 있는 문항(ID): {', '.join(cmp['only_in_one'])}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- 저장된 결과 다시 채점(실행 없음, RFP-26-08 A)

class RescoreUnavailable(RunnerConfigError):
    """다시 채점할 수 없는 결과(Router 기록이 없는 예전 실행 등). 재측정이 필요하다."""


def rescore_result(result: dict[str, Any], items_by_id: dict[str, dict[str, Any]], *, set_sha256: str | None = None,
                   phrases: M.Phrases | None = None, source: str | None = None) -> dict[str, Any]:
    """저장된 개발셋 결과의 실행 기록(`run`)을 지금 채점기·지금 평가 세트로 다시 채점한 **새 결과**를 돌려준다(원본은 바꾸지 않는다).
    모델·도구는 다시 부르지 않는다. 시험셋 결과(문항별 기록 없음)와 Router 기록이 없는 실행이 섞인 결과는 `RescoreUnavailable`."""
    rows0 = result.get("items")
    if not isinstance(rows0, list):
        raise RescoreUnavailable("문항별 기록이 없는 결과(시험셋 결과)는 재채점하지 않는다")
    runs_in = [rows0, *[r.get("items") or [] for r in result.get("items_repeats") or []]]
    no_router = sum(1 for rs in runs_in for r in rs if "router" not in (r.get("run") or {}))
    if no_router:
        raise RescoreUnavailable(f"Router 기록이 없는 행 {no_router}개: {M.TRAJ_RULE}로 재채점할 수 없다(재측정 필요)")
    ph = phrases or M.Phrases.from_backend()
    runs: list[list[dict[str, Any]]] = []
    for rs in runs_in:
        out = []
        for old in rs:
            it = items_by_id.get(str(old.get("id")))
            if it is None:
                raise RescoreUnavailable(f"평가 세트에 없는 문항: {old.get('id')}")
            row = M.score_item(it, M.RunRecord.from_json(old["run"]), ph)
            for k in ("judge", "cost_usd"):  # 채점과 무관한 칸은 그대로 옮긴다
                if k in old:
                    row[k] = old[k]
            row["run"] = old["run"]
            out.append(row)
        runs.append(out)
    res = json.loads(json.dumps({k: v for k, v in result.items() if k not in ("items", "items_repeats", "metrics", "reliability")}))
    meta = res.setdefault("meta", {})
    meta["rescored"] = {"from": source, "from_created_utc": meta.get("created_utc"), "from_trajectory_rule": meta.get("trajectory_rule"),
                        "from_set_sha256": meta.get("set_sha256"), "set_sha256": set_sha256,
                        "note": "저장된 실행 기록을 다시 채점(모델·도구 호출 0). 이전 채점 결과와 섞지 않는다"}
    meta["created_utc"] = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta["trajectory_rule"] = M.TRAJ_RULE
    res["metrics"] = M.aggregate(runs[0])
    res["items"] = runs[0]
    if len(runs) > 1:
        res["reliability"] = M.reliability(runs)
        res["items_repeats"] = [{"run": i + 1, "items": rows} for i, rows in enumerate(runs) if i > 0]
    elif result.get("reliability"):
        res["reliability_not_recomputed"] = "원본에 2회차 이후 문항별 행이 없어 신뢰성을 다시 계산하지 못했다"
    return res


def rescore_file(src: Path, out: Path | None = None) -> Path:
    """`src` 결과를 개발셋으로 다시 채점해 새 파일로 쓴다. 원본 경로·이미 있는 파일에는 쓰지 않는다."""
    result = json.loads(src.read_text(encoding="utf-8"))
    set_file = (result.get("meta") or {}).get("set_file")
    if set_file != SET_FILES["dev"].name:
        raise RescoreUnavailable(f"개발셋 결과만 재채점한다(set_file={set_file})")
    dev = SET_FILES["dev"]
    items = {str(x.get("id")): x for x in G.load_jsonl(dev)}
    res = rescore_result(result, items, set_sha256=sha256_file(dev), source=src.name)
    path = out or src.with_name(f"{src.stem}-rescored-{M.TRAJ_RULE.replace('@', '-')}.json")
    if path.resolve() == src.resolve() or path.exists():
        raise RunnerConfigError(f"원본·기존 파일은 덮어쓰지 않는다: {path.name}")
    return save(res, path)


AGENTS: dict[str, Callable[[], Any]] = {"offline-fixed": OfflineFixedAgent}


class JudgeSetupError(RunnerConfigError):
    """judge를 만들 수 없다(키 없음 등). 실행 전에 종료 코드 2로 멈춘다."""


def default_judge(settings: Any, max_usd: float) -> Any:
    """실제 judge(Claude Sonnet 5.5). 키는 설정(`ANTHROPIC_API_KEY`)에서 읽어 SDK에 넘기고 어디에도 남기지 않는다. 비용은 원장의 평가 몫에 쌓인다.
    시험에서는 부르지 않는다(`judge_factory`로 가짜 전송을 넣는다)."""
    from app.config import reveal
    from app.llm.ledger import CostLedger

    key = getattr(settings, "anthropic_api_key", None)
    if not key:
        raise JudgeSetupError("judge에 필요한 환경변수가 없다: ANTHROPIC_API_KEY")
    return SJ.SonnetJudge(SJ.AnthropicTransport(api_key=reveal(key)), ledger=CostLedger(), max_usd=max_usd)


def _run_graph_cli(a: argparse.Namespace, items: list[dict[str, Any]], *, settings_fn: Callable[[], Any] | None,
                   resources_factory: Callable[..., GraphResources] | None,
                   judge_factory: Callable[[Any, float], Any] | None = None,
                   c0_model_factory: Callable[[Any], tuple[Any, Any]] | None = None) -> tuple[Any, CostBudget, dict[str, Any], Any] | None:
    """그래프 에이전트 준비(C0는 `_prepare_c0`: 모델만, 원격 DB 없음). 필수 설정이 없으면 이름만 출력하고 None(0건). 자원을 만들기 전에 묶음·draft 규칙을 확인한다.
    `--judge sonnet`이면 judge도 여기서 만든다(자원보다 먼저: 키가 없으면 원격 DB를 읽기 전에 멈춘다)."""
    from app.agent import llm
    from app.agent.graph.prompt import load_summary_instruction
    from app.agent.graph.wiring import DEFAULT_PROMPT
    from app.api.service import missing_settings

    os.environ["MEDIAGENT_EVAL"] = "1"  # 평가 모드 강제: LLM 캐시 off, 비용은 원장의 평가 몫으로
    settings = (settings_fn or _default_settings)()
    need = ("OPENAI_API_KEY",) if a.condition == C0 else GRAPH_REQUIRED_ENV  # C0는 원격 DB를 읽지 않는다
    missing = [n for n in missing_settings(settings) if n in need]
    if missing:
        print(f"필수 환경변수가 없어 실행하지 않았다(0건): {', '.join(missing)}")
        return None
    check_system_prompt(a.prompt_set, DEFAULT_PROMPT)
    load_summary_instruction(a.prompt_set, allow_draft=a.allow_draft)  # draft 묶음은 --allow-draft 없이는 여기서 멈춘다
    judge = (judge_factory or default_judge)(settings, a.judge_max_usd) if a.judge == JUDGE_SONNET else None
    if a.condition == C0:
        return _prepare_c0(a, settings, judge, c0_model_factory)
    prefix = "l2" if a.condition == DEFAULT_CONDITION else a.condition.lower().replace("+", "plus")  # C2 실행 ID는 지금까지와 같다
    run_id = f"{prefix}-{a.prompt_set.replace('@', '-')}-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}"
    resources = (resources_factory or default_graph_resources)(settings, prompt_set=a.prompt_set, allow_draft=a.allow_draft, run_id=run_id)
    apply_condition(resources, a.condition)
    apply_typo_correct(resources, a.typo_correct)
    agent = GraphAgent(resources, info={"prompt_set": a.prompt_set, "run_id": run_id, "api_enabled": False, "condition": a.condition},
                       condition=a.condition)
    versions = {"model": {"agent": llm.MODEL, "summary": llm.MODEL}, "prompt": prompt_versions(a.prompt_set), **code_versions(a.condition),
                "dict": resources.dict_meta, "corpus": getattr(resources, "corpus_meta", None)}
    del items
    total = resources.cost_total
    if judge is not None and getattr(judge, "ledger", None) is not None:
        # judge 비용도 같은 원장(평가 몫)에 쌓이므로, 에이전트 비용 상한·문항별 비용에서는 judge 몫을 뺀다(judge는 `--judge-max-usd`로 따로 막는다)
        total = lambda: resources.cost_total() - float(judge.usage.cost_usd)  # noqa: E731
    return agent, CostBudget(a.max_usd, total), versions, judge


def _prepare_c0(a: argparse.Namespace, settings: Any, judge: Any,
                c0_model_factory: Callable[[Any], tuple[Any, Any]] | None) -> tuple[Any, CostBudget, dict[str, Any], Any]:
    """C0 준비: 원격 DB·사전·코퍼스를 읽지 않는다(질문만). 버전 기록은 모델·C0 규칙·채점 코드뿐이고 프롬프트·하네스·사전·코퍼스는 해당 없음(None)."""
    from app.agent import llm

    model, ledger = (c0_model_factory or default_c0_model)(settings)
    agent = LlmOnlyAgent(model, info={"api_enabled": False, "run_id": f"c0-{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}"})
    versions = {"model": {"agent": llm.MODEL, "summary": None}, "prompt": None, "graph": C0_VERSION, "harness": None, "dict": None, "corpus": None,
                "metrics": metrics_version()}

    def total() -> float:
        spent = float(ledger.spent("eval"))
        return spent - float(judge.usage.cost_usd) if judge is not None and getattr(judge, "ledger", None) is not None else spent

    return agent, CostBudget(a.max_usd, total), versions, judge


def main(argv: Sequence[str] | None = None, *, settings_fn: Callable[[], Any] | None = None,
         resources_factory: Callable[..., GraphResources] | None = None,
         judge_factory: Callable[[Any, float], Any] | None = None,
         c0_model_factory: Callable[[Any], tuple[Any, Any]] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", default="dev", help="dev | test | 파일 경로")
    ap.add_argument("--agent", choices=sorted([*AGENTS, GRAPH_AGENT]), default="offline-fixed")
    ap.add_argument("--condition", default=DEFAULT_CONDITION,
                    help=f"비교 조건(9.5절). 연결된 값: {', '.join(SUPPORTED_CONDITIONS)} (C1·C1+·C0는 --agent graph에서만)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--allow-sealed", action="store_true", help=f"시험셋 열람 허용(환경변수 {G.SEALED_ENV}도 필요)")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--subset", choices=sorted(SUBSETS), help="표시 행만 고른다(dev_golden = 개발 골든, dev_reliability_core = 개발 안전 핵심 40)")
    ap.add_argument("--prompt-set", default=None, help="graph 에이전트의 프롬프트 묶음(기본: `wiring.DEFAULT_PROMPT_SET`, 서비스와 같은 묶음)")
    ap.add_argument("--allow-draft", action="store_true", help="draft 프롬프트가 든 묶음 허용(검토 중인 초안 점검용)")
    ap.add_argument("--max-usd", type=float, help="graph 에이전트 비용 상한(필수). 닿으면 남은 문항을 건너뛴다")
    ap.add_argument("--judge", choices=[JUDGE_NONE, JUDGE_SONNET], default=JUDGE_NONE,
                    help="judge(J1~J5·Ragas 3지표). none = 코드 채점만(기본), sonnet = Claude Sonnet 5.5 실제 호출(graph 전용, --judge-max-usd 필수)")
    ap.add_argument("--judge-max-usd", type=float, help="judge 비용 상한(--judge sonnet이면 필수). 닿으면 그 뒤 문항은 judge 없이 코드 채점만 한다")
    ap.add_argument("--baseline", type=Path, metavar="RESULT.json",
                    help="이전 측정 결과. 세트 해시·모델·호출 상한·사전·코퍼스·채점 규칙·judge 모델·루브릭이 다르면 시작하지 않는다(9.6절 동결, graph 전용)")
    ap.add_argument("--freeze-diff-reason", help="--baseline과 동결 값이 다른데도 실행할 이유(결과 meta `freeze_baseline`에 기록된다)")
    ap.add_argument("--ids", help="쉼표로 나눈 문항 ID만 돌린다(개발셋 전용, --subset 뒤에 적용). 예: dev-056,dev-057")
    ap.add_argument("--typo-correct", action=argparse.BooleanOptionalAction, default=None,
                    help="오탈자 보정 후 진행(AG-10). 기본은 조건이 정한다(C2·C1+ 켬, C1 끔). C2에서만 --no-typo-correct로 끌 수 있다(graph 전용)")
    ap.add_argument("--save-reliability-carry", action="store_true",
                    help="본 측정 결과 옆에 안전 핵심 문항의 1회차 재사용 파일(결과.reliability-carry.json)을 쓴다(graph 전용, RFP-35-09 A)")
    ap.add_argument("--first-run", type=Path, metavar="RESULT.json",
                    help="신뢰성 실행에서 본 측정 결과를 1회차로 쓰고 추가 회차만 돈다(--subset reliability_core|dev_reliability_core, --repeats 2 이상)")
    ap.add_argument("--compare", nargs=2, type=Path, metavar=("A.json", "B.json"), help="두 결과 파일을 나란히 본다(실행 없음)")
    ap.add_argument("--rescore", type=Path, metavar="RESULT.json",
                    help="저장된 개발셋 결과를 지금 채점기로 다시 채점해 새 파일로 쓴다(실행 없음, 원본 보존. --out으로 경로 지정)")
    a = ap.parse_args(argv)
    if a.rescore:
        try:
            out = rescore_file(a.rescore, a.out)
        except RescoreUnavailable as e:
            print(f"재채점 불가: {e}")
            return 3
        print(f"재채점 → {out}")
        return 0
    if a.compare:
        print(format_compare(compare_results(*(json.loads(p.read_text(encoding="utf-8")) for p in a.compare))))
        return 0
    if a.condition not in SUPPORTED_CONDITIONS:
        print(f"--condition {a.condition!r}은(는) 아직 러너에 연결되지 않았다. 지금 받는 값: {', '.join(SUPPORTED_CONDITIONS)} "
              "(C3는 AG-13 개선 뒤라 연결 전이다). 실행하지 않았다")
        return 2
    is_graph = a.agent == GRAPH_AGENT
    if a.typo_correct is not None and not is_graph:
        print(f"--typo-correct/--no-typo-correct는 --agent {GRAPH_AGENT}에서만 받는다. 실행하지 않았다")
        return 2
    if is_graph:
        try:
            a.typo_correct = resolve_typo_correct(a.condition, a.typo_correct)
        except RunnerConfigError as e:
            print(f"{e}. 실행하지 않았다")
            return 2
    if a.condition in REAL_MODEL_CONDITIONS and not is_graph:
        print(f"--condition {a.condition}은(는) --agent {GRAPH_AGENT}에서만 받는다({a.agent}는 조건과 무관한 연결 확인용이라 C2 표기만 쓴다). 실행하지 않았다")
        return 2
    if a.judge != JUDGE_NONE and not is_graph:
        print(f"--judge {a.judge}는 --agent {GRAPH_AGENT}에서만 받는다. 실행하지 않았다")
        return 2
    if a.judge != JUDGE_NONE and not (a.judge_max_usd and a.judge_max_usd > 0):
        print("--judge sonnet은 --judge-max-usd(0보다 큰 judge 비용 상한)가 있어야 시작한다. 실행하지 않았다")
        return 2
    if is_graph and not (a.max_usd and a.max_usd > 0):
        print("graph 에이전트는 --max-usd(0보다 큰 비용 상한)가 있어야 시작한다")
        return 2
    if is_graph and a.prompt_set is None:  # 기본 묶음은 서비스 배선과 한 곳(`wiring.DEFAULT_PROMPT_SET`)에서만 정한다(결과 meta에 그 이름이 남는다)
        from app.agent.graph.wiring import DEFAULT_PROMPT_SET

        a.prompt_set = DEFAULT_PROMPT_SET
    path = SET_FILES.get(a.set, Path(a.set))
    sealed = G.check_access(path, allow_sealed=a.allow_sealed)  # 시험셋이면 여기서 막힌다(파일을 열기 전)
    if a.ids and sealed:  # 파일을 읽기 전에 막는다
        print("--ids는 시험셋에 쓰지 않는다(문항 ID로 고르는 것은 열람이다). 실행하지 않았다")
        return 2
    digest = sha256_file(path, allow_sealed=a.allow_sealed)
    items = select_subset(G.load_jsonl(path, allow_sealed=a.allow_sealed), a.subset)
    if a.ids:
        try:
            items = select_ids(items, a.ids.split(","))
        except RunnerConfigError as e:
            print(f"{e}. 실행하지 않았다")
            return 2
    if a.limit:
        items = items[: a.limit]
    if a.subset and not items:  # 다른 세트의 표시(개발셋에 reliability_core 등)를 고르면 빈 표본으로 돌지 않는다
        print(f"--subset {a.subset}로 고른 문항이 0개다(이 세트에 그 표시가 없다). 실행하지 않았다")
        return 2
    if (a.first_run or a.save_reliability_carry) and not is_graph:
        print(f"--first-run·--save-reliability-carry는 --agent {GRAPH_AGENT}에서만 받는다. 실행하지 않았다")
        return 2
    if a.first_run and (a.subset not in RELIABILITY_SUBSETS or a.repeats < 2 or a.limit or a.ids):
        print(f"--first-run은 --subset {'|'.join(RELIABILITY_SUBSETS)}와 --repeats 2 이상에서만, --limit·--ids 없이 받는다. 실행하지 않았다")
        return 2
    carry_mark = (a.subset if a.subset in RELIABILITY_SUBSETS else ("reliability_core" if sealed else "dev_reliability_core")) \
        if (a.first_run or a.save_reliability_carry) else None
    carry_map = carry_keys([it for it in items if it.get(carry_mark) is True], sealed=sealed) if carry_mark else None
    versions: dict[str, Any] = {"model": None, "prompt": None, "graph": None, "harness": None, "dict": None}  # 실제 그래프 측정 때 채운다
    budget: CostBudget | None = None
    judge: Any = None
    if is_graph:
        try:
            prepared = _run_graph_cli(a, items, settings_fn=settings_fn, resources_factory=resources_factory, judge_factory=judge_factory,
                                      c0_model_factory=c0_model_factory)
        except (JudgeSetupError, SJ.JudgeError) as e:  # judge 키·SDK·프롬프트 파일 문제: 원격 자원을 만들기 전에 멈춘다
            print(f"{e}. 실행하지 않았다")
            return 2
        if prepared is None:
            return 0
        agent, budget, versions, judge = prepared
    else:
        agent = AGENTS[a.agent]()
    meta = {"set": a.set if a.set in SET_FILES else path.name, "set_file": path.name, "set_sha256": digest, **manifest_check(path, digest),
            "set_version": items[0].get("set_version") if items else None, "n_items_run": len(items), "condition": a.condition,
            "agent": a.agent, "agent_info": getattr(agent, "info", {}), "versions": versions}
    if is_graph:
        from app.agent.pipeline.build import harness_profile

        # 조건별 하네스 적용표(`harness@v1`, RFP-33-03 A·BE-08): 기준선 장치는 C1·C2 공통, 개선 단계 선택 제한 장치는 C3 ablation 행 몫이라 비어 있다
        meta.update({"subset": a.subset, "n_items_selected": len(items), "prompt_set": None if a.condition == C0 else a.prompt_set,
                     "harness": c0_harness() if a.condition == C0 else harness_profile(a.condition),
                     "typo_correction": typo_correction_meta(a.typo_correct), "run_settings": run_settings()})
        if a.baseline:
            ok, record = baseline_guard(meta, judge, a.baseline, a.freeze_diff_reason)
            if not ok:
                print(f"이전 측정({a.baseline.name})과 동결 값이 달라 시작하지 않았다(9.6절 측정 기간 동결). 다른 항목: "
                      + ", ".join(d["item"] for d in record["diffs"]) + ". 바꾼 이유가 있으면 --freeze-diff-reason \"이유\"로 기록하고 다시 실행한다")
                return 2
            meta["freeze_baseline"] = record
    elif a.baseline:
        print(f"--baseline은 --agent {GRAPH_AGENT}에서만 받는다. 실행하지 않았다")
        return 2
    first_rows: list[dict[str, Any]] | None = None
    if a.first_run:
        try:
            first_rows, meta["first_run"] = load_first_run(a.first_run, items, subset=carry_mark, sealed=sealed, set_sha256=digest,
                                                           planned_meta=meta, judge=judge)
        except (FirstRunMismatch, OSError, ValueError) as e:
            print(f"{e}. 실행하지 않았다(1회차 재사용 불가)")
            return 2
    carry: list[dict[str, Any]] | None = [] if a.save_reliability_carry else None
    res = run_eval(items, agent, sealed=sealed, meta=meta, repeats=a.repeats, budget=budget, judge=judge,
                   skip_judge=is_graph and judge is None,  # graph 실행은 --judge sonnet일 때만 judge를 붙인다(기본은 코드 채점만)
                   max_consecutive_errors=MAX_CONSECUTIVE_ERRORS if is_graph else None,
                   carry_keys_map=carry_map, carry_out=carry, first_run=first_rows)
    out = save(res, a.out)
    if carry is not None:
        print(f"  1회차 재사용 파일 → {write_carry(res, carry, out, subset=carry_mark)}(안전 핵심 {len(carry)}문항)")
    mt = res["metrics"]
    print(f"[{a.set}·{a.condition}·{a.agent}] 문항 {res['meta']['n_items_run']} → {out}")
    for name in ("contra_judgment_accuracy", "routing_accuracy"):
        v = mt[name]
        print(f"  {name}: {v['k']}/{v['n']} {v['wilson95']} ({v['claim']})")
    s = mt["safety_response_rate"]
    print(f"  safety code_part: {s['code_part']['k']}/{s['code_part']['n']}, judge 보류 {s['pending_judge_items']}문항")
    print(f"  trajectory: {mt['trajectory']['verdicts']}")
    if budget is not None:
        c = res["cost_usd"]
        print(f"  cost: ${c['total']:.4f} / 상한 ${c['max_usd']}, 상한으로 건너뛴 문항 {c['skipped']}")
        aux = mt.get("aux_source_missing")
        if aux:
            z = aux["source_missing_zero_items"]
            print(f"  보조(출처 누락 0건 문항): {z['k']}/{z['n']}, 인용 불일치 {aux['quote_mismatch_total']}, 하네스 차단 {aux['harness_blocks_total']}")
        ju = res.get("judge_usage")
        if ju:
            rg = mt.get("ragas") or {}
            print(f"  judge: 호출 {ju['calls']}(재시도 {ju['retries']}, 오류 {ju['errors']}, 오류율 {ju['error_rate']}) "
                  f"${ju['cost_usd']:.4f} / 상한 ${ju['max_usd']}" + (", 상한 도달" if ju["cap_reached"] else ""))
            print("  ragas: " + ", ".join(f"{k} {rg[k]['mean']}(n={rg[k]['n']}, 빠짐 {rg[k]['n_missing']})"
                                          for k in ("faithfulness", "context_precision", "context_recall") if k in rg))
        st = res.get("stopped")
        if st:
            print(f"  연속 오류 {st['threshold']}건으로 중단: 회차 {st['run']}, 위치 {st['index']}"
                  f"{', 문항 ' + str(st['item_id']) if st.get('item_id') else ''}, 건너뛴 실행 {st['skipped']}, 오류 종류 {st['errors']}")
        rel = res.get("reliability")
        if rel:
            pa, pc = rel["pass^k"], rel["pass^k_code_part"]
            print(f"  반복 {rel['repeats']}회: pass^k {pa['k']}/{pa['n']}(judge 보류 {rel['undecided_pending_judge']}문항 제외), "
                  f"코드 요소만 {pc['k']}/{pc['n']}, 판정 일치 {rel['judgment_agreement']['k']}/{rel['judgment_agreement']['n']}")
    return 0


if __name__ == "__main__":
    # S-05: 직접 실행할 때만 처리되지 않은 예외·logging 출력에서 키·DSN을 가린다(import만 할 때는 설치하지 않음)
    from app.security.redact import install_excepthook  # noqa: E402
    install_excepthook()
    raise SystemExit(main())
