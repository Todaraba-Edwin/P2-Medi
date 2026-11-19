"""AG-01 그래프 계측 L2(RFP-34-02, PJ2-Agent-로깅-전략.md 2장·4장). BE-15 L1 `SpanLogger`에 span을 채운다.

- 한 질문 = 한 trace. `guardrail_in` 노드가 새 trace를 열고, `finalize` 노드 뒤에 trace 머리 레코드를 한 줄 쓴다.
- span 계층: 노드 span(6노드) → 그 자식으로 도구 span(`tools` 노드 안의 도구 호출마다), 하네스 이벤트 span(노드가 낸 이벤트 중 하네스 동작인 것).
- 내용을 싣지 않는다: 질문·모델 출력·도구 결과 원문은 넘기지 않는다. `input_summary`·`output_summary`는 이름·개수·근거 ID·코드만 담는다.
  모드 필터(service에서 내용 필드 제거, 파일 없음)와 비밀 마스킹은 L1 `SpanLogger`가 한다(이 모듈은 필드만 고른다).
- 하네스 이벤트 이름은 상태 `events`의 `event` 값을 그대로 `harness_event.detail`에 쓴다(코드 이름만). 동작은 `HARNESS_ACTIONS` 표가 정한다.
- 캐시 상태: `wiring.build_deps`가 만든 실제 모델은 `graph.metered`의 `CachedToolModel`·`CachedSummary`로 감싸 `llm_cache`·원장을 거치고
  응답 메타데이터 `mediagent_cache`에 `off`·`hit`·`miss`를 적는다. 그 값을 `cache`에 쓰고, 없으면(가짜 모델) `off`다(평가 모드는 항상 off).
- 요약(구조화 출력) 호출은 `summary_call`이 같은 `model` 노드 span에 토큰·비용을 합치고 내역을 `output_summary.summary_call`에 둔다
  (2026-11-11 가산, 새 span·새 필드 없음: 노드 span 6종·경로 재구성은 그대로).
- `sink`는 `.log(**fields)`를 가진 객체(`SpanLogger` 또는 시험용 수집기). 없으면 계측하지 않는다(`GraphDeps.tracer=None`이 기본).
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

# 상태 `events`의 이벤트 이름 → 하네스 동작(로깅 전략 4장 (2) `harness_event`, AG-01 완료 조건: block·warn·flag)
HARNESS_ACTIONS: dict[str, str] = {
    "CALL_LIMIT": "block",              # H12 모델 호출 상한
    "STATE_KEY_BLOCKED": "block",       # H8 노드 몫 밖 상태 키
    "TOOL_KEY_DROPPED": "block",        # H8 도구가 쓸 수 없는 상태 키
    "ARG_SCHEMA": "block",              # H21 도구 인자 스키마 위반(도구 본문 미실행)
    "UNKNOWN_TOOL": "block",            # H21 등록되지 않은 도구
    "VALIDATION_FALLBACK": "block",     # H2 두 번째 검증 실패 → 코드 문구
    "REWIND": "rollback",               # H2 검증 실패 되감기
    "TOOL_ERROR": "warn",               # H21 도구 본문 예외
    "INJECTION_IN_TOOL_RESULT": "flag",  # H8 도구 결과 안 지시문 모양
}
BLOCK_OR_WARN = frozenset({"block", "warn", "rollback"})
_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")  # 사유 코드 모양(예: NO_EVIDENCE, CLAIM_OMITTED). 이 모양이 아닌 키는 span에 싣지 않는다


class SpanSink(Protocol):
    def log(self, **fields: Any) -> Any: ...


def harness_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """상태 이벤트 목록에서 하네스 동작인 것만 `{"rule", "action", "detail"}`로 바꾼다(내용 없음, 코드 이름만)."""
    out: list[dict[str, Any]] = []
    for e in events or []:
        if not isinstance(e, dict):
            continue
        name, rule = str(e.get("event") or ""), str(e.get("rule") or "")
        if name in HARNESS_ACTIONS:
            out.append({"rule": rule, "action": HARNESS_ACTIONS[name], "detail": name})
        elif name == "GUARDRAIL_IN":
            if e.get("emergency"):
                out.append({"rule": "H4", "action": "append", "detail": "EMERGENCY_119"})
            if e.get("route") == "REFUSE":
                out.append({"rule": "H4", "action": "block", "detail": f"REFUSE:{e.get('reason') or 'OUT_OF_SCOPE'}"})
        elif name == "SENTENCE_FILTER" and int(e.get("dropped") or 0) > 0:
            out.append({"rule": rule or "H1", "action": "warn", "detail": "SENTENCE_DROPPED"})
        elif name == "VALIDATOR" and e.get("status") == "FIXED":
            out.append({"rule": rule or "H2", "action": "warn", "detail": "VALIDATOR_FIXED"})
    return out


def _code_counts(raw: Any) -> dict[str, int]:
    """`{사유 코드: 건수}`만 옮긴다. 값이 정수가 아니거나 0 이하인 항목, 코드 모양(대문자·숫자·밑줄)이 아닌 키는 버린다(문장 원문이 섞이지 않게)."""
    if not isinstance(raw, dict):
        return {}
    return {str(k): int(n) for k, n in raw.items()
            if isinstance(k, str) and _CODE_RE.match(k) and isinstance(n, int) and not isinstance(n, bool) and n > 0}


def _check_counts(events: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """validator span의 사유 건수(AG-13-12 A). 문장 필터(`SENTENCE_FILTER`, H1)와 Validator(`VALIDATOR`, H2) 이벤트의 `reasons`를 코드별로 더하고,
    계층 검사를 켰으면(C3) `claim_gaps` 건수와 기록만 한 검사 건수(`recorded`, C3 v4)도 싣는다. 문장 원문·근거 ID는 넣지 않는다. 건수가 없으면 키를 만들지 않는다."""
    out: dict[str, dict[str, int]] = {}
    for e in events:
        if not isinstance(e, dict):
            continue
        key = {"SENTENCE_FILTER": "filter_reasons", "VALIDATOR": "validator_reasons"}.get(str(e.get("event")))
        if key is None:
            continue
        for k, n in _code_counts(e.get("reasons")).items():
            out.setdefault(key, {})[k] = out.get(key, {}).get(k, 0) + n
        if e.get("event") == "VALIDATOR":
            for k, n in _code_counts(e.get("claim_gaps")).items():
                out.setdefault("claim_gaps", {})[k] = out.get("claim_gaps", {}).get(k, 0) + n
            # C3 v4(AG-13-29 A): 되감기 대신 기록만 한 검사(⑯) 건수. 키가 없는 이벤트(C1·C1+·C2)는 기존 모양 그대로
            for k, n in _code_counts(e.get("recorded")).items():
                out.setdefault("recorded", {})[k] = out.get("recorded", {}).get(k, 0) + n
    return out


def count_block_warn(events: list[dict[str, Any]]) -> int:
    """정상 경로 회귀(RFP-33-04)의 "하네스 차단·경고 0건" 판정에 쓰는 수. `append`(119)·`flag`는 세지 않는다."""
    return sum(1 for h in harness_events(events) if h["action"] in BLOCK_OR_WARN)


def _ids(items: list[dict[str, Any]]) -> list[str]:
    return [str(it["evidence_id"]) for it in items if isinstance(it, dict) and it.get("evidence_id")]


def _arg_summary(args: dict[str, Any]) -> dict[str, Any]:
    """도구 인자 요약: 인자 이름과 약 개수, 품목기준코드·성분코드처럼 코드인 값만(약 이름 원문은 넣지 않는다)."""
    summ: dict[str, Any] = {"arg_names": sorted(args)}
    drugs = args.get("drugs")
    if isinstance(drugs, list):
        summ["n_drugs"] = len(drugs)
        seqs = [d.get("item_seq") for d in drugs if isinstance(d, dict) and d.get("item_seq")]
        if seqs:
            summ["item_seqs"] = seqs
    for k in ("item_seq", "ingredient_code", "section"):
        if isinstance(args.get(k), str):
            summ[k] = args[k]
    if "pregnancy" in args:
        summ["pregnancy"] = bool(args.get("pregnancy"))
    if isinstance(args.get("age"), dict):
        summ["age_given"] = True
    return summ


def _tool_out_summary(out: dict[str, Any]) -> dict[str, Any]:
    items = [it for it in out.get("items") or [] if isinstance(it, dict)]
    statuses: dict[str, int] = {}
    for it in items:
        statuses[str(it.get("status"))] = statuses.get(str(it.get("status")), 0) + 1
    summ: dict[str, Any] = {"n_items": len(items), "statuses": statuses}
    err = out.get("error")
    if isinstance(err, dict) and err.get("code"):
        summ["error_code"] = err["code"]
    return summ


def _sources(items: list[dict[str, Any]]) -> tuple[str | None, str | None, str | None]:
    """(source, file_api_match, data_as_of). source: file/api(혼합이면 `file+api`). 일치는 꼬리표 이름 그대로."""
    kinds = {it.get("source_kind") for it in items if it.get("source_kind")}
    src = None
    if kinds:
        has_api = any(str(k).startswith("API") for k in kinds)
        has_file = any(not str(k).startswith("API") for k in kinds)
        src = "file+api" if has_api and has_file else ("api" if has_api else "file")
    match_flags = [f for it in items for f in it.get("flags") or [] if f in ("API_SAME", "FILE_ONLY", "API_ONLY", "API_FAIL", "API_PAIR_INCOMPLETE")]
    match = ",".join(sorted(set(match_flags))) or None
    dates = sorted({str(it["as_of"]) for it in items if isinstance(it.get("as_of"), str) and it.get("as_of")})
    return src, match, (",".join(dates) or None)


@dataclass
class _Trace:
    trace_id: str
    started: float
    n: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0


@dataclass
class GraphTracer:
    """노드·도구·하네스 span을 `sink`에 쓴다. 그래프 하나에 하나(한 번에 한 질문, 동기 실행 전제)."""

    sink: SpanSink
    prompt_version: str | None = None
    prompt_set: str | None = None
    graph_version: str | None = None
    tool_schema_version: str | None = None
    api_enabled: bool | None = None
    model: str | None = None
    provider: str = "openai"
    item_id: str | None = None
    condition: str | None = None
    repeat_idx: int | None = None
    branch_type: str | None = None
    clock: Callable[[], float] = time.monotonic
    cost_fn: Callable[[int, int, int], float] | None = None
    _trace: _Trace | None = field(default=None, init=False, repr=False)
    _node_span: str | None = field(default=None, init=False, repr=False)
    _pending_summary: dict[str, Any] | None = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------ 공통
    def _new_span_id(self) -> str:
        if self._trace is None:
            self.start_trace()
        assert self._trace is not None  # noqa: S101 — 바로 위에서 만든다(타입 좁히기)
        self._trace.n += 1
        return f"s-{self._trace.n:04d}"

    def _base(self) -> dict[str, Any]:
        f: dict[str, Any] = {"trace_id": self._trace.trace_id if self._trace else None, "prompt_version": self.prompt_version,
                             "graph_version": self.graph_version, "tool_schema_version": self.tool_schema_version}
        if self.prompt_set:
            f["prompt_set"] = self.prompt_set
        for k in ("item_id", "condition", "repeat_idx", "branch_type"):
            v = getattr(self, k)
            if v is not None:
                f[k] = v
        return {k: v for k, v in f.items() if v is not None}

    def start_trace(self) -> str:
        self._trace = _Trace(trace_id=f"t-{uuid.uuid4().hex[:12]}", started=self.clock())
        self._node_span = None
        self._pending_summary = None
        return self._trace.trace_id

    @property
    def trace_id(self) -> str | None:
        return self._trace.trace_id if self._trace else None

    # ------------------------------------------------------------------ 노드
    def wrap_node(self, name: str, fn: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable[[dict[str, Any]], dict[str, Any]]:
        def run(state: dict[str, Any]) -> dict[str, Any]:
            if name == "guardrail_in" or self._trace is None:
                self.start_trace()
            span_id = self._new_span_id()
            self._node_span = span_id
            t0 = self.clock()
            err: str | None = None
            upd: dict[str, Any] = {}
            try:
                upd = fn(state)
                return upd
            except Exception as exc:
                err = type(exc).__name__
                raise
            finally:
                self._emit_node(name, span_id, state, upd, int((self.clock() - t0) * 1000), err)
                self._node_span = None
                if name == "finalize":
                    self._emit_header(state, upd)

        return run

    def _emit_node(self, name: str, span_id: str, state: dict[str, Any], upd: dict[str, Any], ms: int, err: str | None) -> None:
        calls = upd.get("call_count", state.get("call_count", 0))
        f: dict[str, Any] = {**self._base(), "span_id": span_id, "node": name, "step": calls, "latency_ms": ms,
                             "model_calls_so_far": calls, "rollbacks_so_far": upd.get("rewind_count", state.get("rewind_count", 0)), "retry": 0}
        if err:
            f["error_type"] = err
        if name == "router":
            f["route"] = state.get("route")
            f["intent"] = ",".join(upd.get("intent") or []) or None
            f["output_summary"] = {"n_entities": len(upd.get("entities") or []), "ambiguous": bool(upd.get("ambiguous")),
                                   "branch": upd.get("branch_label")}
        elif name == "guardrail_in":
            f["route"] = upd.get("route")
        elif name == "model":
            self._model_fields(f, upd)
        elif name == "tools":
            ev = upd.get("evidence") or []
            f["evidence_ids"] = _ids(ev)
            f["source"], f["file_api_match"], f["data_as_of"] = _sources(ev)
        elif name == "validator":
            v = upd.get("validation") or {}
            st = str(v.get("status") or "").upper()
            f["verdict"] = {"PASS": "pass", "FIXED": "fix", "FAIL": "fail"}.get(st, st.lower() or None)
            # `violations` = 되감기 사유 코드 + 규칙 번호가 붙은 검사 코드(H22·H24, AG-07-02 B). 코드 이름만, 문장 내용 없음.
            checks = {str(k): int(n) for k, n in (v.get("rule_checks") or {}).items()}
            f["violations"] = sorted({*(str(r) for r in v.get("reasons") or []), *checks})
            summary: dict[str, Any] = {}
            if checks:
                summary = {"rule_checks": checks, "rules": {str(k): int(n) for k, n in (v.get("rules") or {}).items()}}
            summary.update(_check_counts(upd.get("events") or []))  # AG-13-12 A: 문장 걸러짐·삭제 사유 코드별 건수(원문 없음)
            if summary:
                f["output_summary"] = summary
        elif name == "finalize":
            f["end_reason"] = upd.get("end_reason")
            ans = upd.get("answer") or {}
            f["output_summary"] = {"n_entries": len(ans.get("entries") or []), "emergency": bool(ans.get("emergency")),
                                   "has_summary": bool(ans.get("summary")), "n_citations": len(ans.get("citations") or [])}
            f["evidence_ids"] = [c.get("evidence_id") for c in ans.get("citations") or [] if isinstance(c, dict) and c.get("evidence_id")]
        self.sink.log(**{k: v for k, v in f.items() if v is not None})
        for h in harness_events(upd.get("events") or []):
            self.sink.log(**self._base(), span_id=self._new_span_id(), parent_id=span_id, node=name, step=calls, harness_event=h)

    def _model_fields(self, f: dict[str, Any], upd: dict[str, Any]) -> None:
        msgs = upd.get("messages") or []
        last = msgs[-1] if msgs else None
        if last is None:
            return
        f["model"] = self.model
        f["provider"] = self.provider
        um = getattr(last, "usage_metadata", None) or {}
        tin, tout = int(um.get("input_tokens") or 0), int(um.get("output_tokens") or 0)
        tcached = int(((um.get("input_token_details") or {}).get("cache_read")) or 0)
        cost = self.cost_fn(tin, tout, tcached) if (um and self.cost_fn is not None) else 0.0
        meta = getattr(last, "response_metadata", None) or {}
        f["cache"] = str(meta.get("mediagent_cache") or "off")
        n_calls = len(getattr(last, "tool_calls", None) or [])
        f["output_summary"] = {"n_tool_calls": n_calls, "tools": [tc.get("name") for tc in getattr(last, "tool_calls", None) or []],
                               "summary_draft": upd.get("draft") is not None}
        ps, self._pending_summary = self._pending_summary, None
        has_usage = bool(um)
        if ps is not None:  # 같은 노드의 요약 호출을 합산(내역은 output_summary에)
            s_cost = self.cost_fn(ps["tokens_in"], ps["tokens_out"], ps["tokens_cached"]) if (ps["has_usage"] and self.cost_fn is not None) else 0.0
            f["output_summary"]["summary_call"] = {"cache": ps["cache"], "parsed": ps["parsed"], "tokens_in": ps["tokens_in"],
                                                   "tokens_out": ps["tokens_out"], "tokens_cached": ps["tokens_cached"], "cost_usd": round(s_cost, 8)}
            tin, tout, tcached, cost = tin + ps["tokens_in"], tout + ps["tokens_out"], tcached + ps["tokens_cached"], cost + s_cost
            has_usage = has_usage or ps["has_usage"]
            if ps["cache"] != f["cache"]:  # 두 호출의 캐시 상태가 다르면 실제 호출이 있었던 쪽을 남긴다(적중 비율이 부풀지 않게)
                f["cache"] = next((c for c in ("stored", "miss", "off") if c in (f["cache"], ps["cache"])), f["cache"])
        if has_usage:
            f["tokens_in"], f["tokens_out"], f["tokens_cached"] = tin, tout, tcached
            if self.cost_fn is not None:
                f["cost_usd"] = round(cost, 8)
        if self._trace is not None:
            self._trace.tokens_in += tin
            self._trace.tokens_out += tout
            self._trace.cost_usd += float(f.get("cost_usd") or 0.0)

    def summary_call(self, raw: Any, *, step: int, parsed: bool) -> None:
        """요약(구조화 출력) 호출 한 번의 토큰·비용·캐시를 같은 `model` 노드 span에 합친다(새 span·새 필드 없음, 2026-11-11 가산).

        `model` 노드 하나가 도구 선택 호출과 요약 호출을 함께 하므로(AG-19 ④) 노드 span의 `tokens_*`·`cost_usd`는 두 호출의 합이 되고,
        호출별 내역은 `output_summary.summary_call`(dev·eval만)에 둔다. `raw`가 없으면(가짜 요약) 토큰 0, `cache=off`다.
        """
        um = getattr(raw, "usage_metadata", None) or {}
        meta = getattr(raw, "response_metadata", None) or {}
        self._pending_summary = {"step": step, "parsed": bool(parsed), "cache": str(meta.get("mediagent_cache") or "off"), "has_usage": bool(um),
                                 "tokens_in": int(um.get("input_tokens") or 0), "tokens_out": int(um.get("output_tokens") or 0),
                                 "tokens_cached": int(((um.get("input_token_details") or {}).get("cache_read")) or 0)}

    def _emit_header(self, state: dict[str, Any], upd: dict[str, Any]) -> None:
        # service 집계에는 머리 레코드를 보내지 않는다(종료 사유는 finalize span이 이미 한 번 세었다. 두 번 세지 않게)
        if self._trace is None or getattr(self.sink, "mode", None) == "service":
            return
        evidence = state.get("evidence") or []
        _, match, as_of = _sources(evidence)
        self.sink.log(**self._base(), span_id="s-0000", model=self.model, api_enabled=self.api_enabled, end_reason=upd.get("end_reason"),
                      total_latency_ms=int((self.clock() - self._trace.started) * 1000), total_cost_usd=round(self._trace.cost_usd, 8),
                      model_calls_so_far=state.get("call_count", 0), rollbacks_so_far=state.get("rewind_count", 0),
                      data_as_of=as_of, file_api_match=match, tokens_in=self._trace.tokens_in, tokens_out=self._trace.tokens_out)

    # ------------------------------------------------------------------ 도구(자식 span)
    @contextmanager
    def tool_span(self, tool: str, args: dict[str, Any], step: int) -> Iterator[dict[str, Any]]:
        """`with tracer.tool_span(name, args, step) as rec: ...; rec["out"] = out` — 끝날 때 도구 span 한 줄을 쓴다."""
        parent = self._node_span
        span_id = self._new_span_id()
        rec: dict[str, Any] = {"out": None, "error_type": None}
        t0 = self.clock()
        try:
            yield rec
        finally:
            out = rec.get("out") or {}
            items = [it for it in out.get("items") or [] if isinstance(it, dict)]
            src, match, as_of = _sources(items)
            f: dict[str, Any] = {**self._base(), "span_id": span_id, "parent_id": parent, "node": "tools", "tool": tool, "step": step,
                                 "latency_ms": int((self.clock() - t0) * 1000), "input_summary": _arg_summary(args),
                                 "output_summary": _tool_out_summary(out), "evidence_ids": _ids(items), "source": src,
                                 "file_api_match": match, "data_as_of": as_of, "retry": 0, "error_type": rec.get("error_type")}
            # 인자 차단(ARG_SCHEMA·UNKNOWN_TOOL)은 `output_summary.error_code`로 보이고, 하네스 이벤트 span은 `tools` 노드 이벤트에서 한 번만 쓴다
            self.sink.log(**{k: v for k, v in f.items() if v is not None})


class ListSink:
    """시험·리허설용 수집기(파일 없음). `SpanLogger`와 같은 `.log(**fields)`."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def log(self, **fields: Any) -> dict[str, Any]:
        self.records.append(dict(fields))
        return fields
