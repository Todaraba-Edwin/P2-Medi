"""GROUP-01 3단계(2026-11-19): `/chat` HTTP 계약 연결 — AG-21 `prior_drugs`(AG-21-02 A), AG-22 `took_today`(AG-22-05 A),
FE-11 결과 묶음 칸(`Finding.section`·`pair_ref`·`caution_desc`, `ChatResponse.result_summary`·`rest_fold`·`dose_check`·`dose_notice`·
`redose_notice`, FE-11-04·05·07·08 A). LLM·공공 API·원격 DB 호출 0.

- 요청: 있음/없음/상한 초과/형식 오류 422(입력 값을 되돌려 주지 않음), 그래프 입력으로 옮기는 규칙(`graph_extras`).
- 회귀: 새 요청 칸이 없거나 비면 실행기 인자·응답 JSON이 이전과 같다. `finalize`가 새 칸을 주지 않으면 응답 글자에 새 키가 없다.
- q1 → q2 → q3(로컬 조사 `ctx-rca.md` §6 1~6)를 HTTP 수준에서. 약 3개 결과의 구역·요약·접힘 줄, `took_today`에 따른 되묻기·고지.
- 로그·이벤트·지표에 품목기준코드·약 이름·`took_today` 값이 남지 않는다.
- 사전·질문·항목은 합성(`e2e/golden_synth.py`·이 파일)이다. 평가 세트·시험셋 문항이 아니다.
"""

from __future__ import annotations

import copy
import json
import logging
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import SEQ_AZI, SEQ_COLD, SEQ_T500, FakeDur, golden_conn, golden_dict  # noqa: E402

from app.agent import fixed_phrases as fp  # noqa: E402
from app.agent.finalize import finalize  # noqa: E402
from app.agent.graph.build import build_graph, run_question  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.api import chat as chat_api  # noqa: E402
from app.api import events as ev  # noqa: E402
from app.api.request import CONFIRMED_DRUGS_MAX, ChatRequest, ConversationContext  # noqa: E402
from app.api.runner import GraphRunner, graph_extras, prior_from_context  # noqa: E402
from app.api.schemas import (  # noqa: E402
    ChatResponse,
    DoseCheck,
    Finding,
    PairRef,
    RestFold,
    ResultSummary,
    response_from_state,
    to_chat_response,
)
from app.tools.drug_dict import DrugDict  # noqa: E402

T500, COLD, AZI = "타이레놀정500밀리그람", "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
Q1 = "타이레놀이랑 이지렉트 같이 먹어도 되나요?"  # 두 이름 모두 모호(ctx-rca §1.3)
Q3 = "타이레놀을 2정을 점심에 먹었는데 두통이 해결되지 않아 15시인데 먹어도 되니?"
Q3C = "타이레놀 500 점심에 먹었는데 또 먹어도 되니?"  # 함량 단서 500(이전 선택 콜드-에스정과 맞지 않음)
PAIR_EID = "contra_pair:254000ATB:625201ATB"
NEW_RESPONSE_KEYS = {"result_summary", "rest_fold", "dose_check", "dose_notice", "redose_notice"}
NEW_FINDING_KEYS = {"section", "pair_ref", "caution_desc"}


def _pick(input_name: str, item_seq: str, name: str = "표시 이름") -> dict[str, str]:
    return {"name": name, "item_seq": item_seq, "input_name": input_name}


Q2_PICKS = [_pick("타이레놀", SEQ_COLD, COLD), _pick("이지렉트", SEQ_AZI, AZI)]


@pytest.fixture(scope="module")
def dd() -> DrugDict:
    return golden_dict()


# --------------------------------------------------------------------------- 공용: 그래프·HTTP
def _guide() -> dict[str, Any]:
    return {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}


PAIR_DRAFT = {"sentences": [{"text": "두 약은 함께 먹으면 안 되는 조합(병용금기)으로 올라 있어요.", "evidence_ids": [PAIR_EID],
                             "claim_type": "fact", "citations": []}, _guide()]}


def _script(a: str, b: str) -> list[AIMessage]:
    return [
        AIMessage("", tool_calls=[tool_call("identify_drug", {"name": a}, "c1"), tool_call("identify_drug", {"name": b}, "c2")]),
        AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": a}, {"name": b}]}, "c3")]),
        AIMessage("조회를 마쳤다"),
    ]


def _deps(dd: DrugDict, script: list[AIMessage], drafts: list[Any]) -> tuple[Any, ScriptedToolModel]:
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    tm = ScriptedToolModel(script=list(script))
    return build_deps(dd, ctx, tool_model=tm, summary_model=ScriptedSummary(drafts), system_prompt="시험용 시스템 프롬프트"), tm


class SinkMetrics:
    """지표 기록기 대역(`.log(**fields)`): 넘어온 칸을 그대로 모은다."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def log(self, **fields: Any) -> None:
        self.calls.append(fields)


def _post(runner: Any, body: dict[str, Any], metrics: Any = None) -> tuple[Any, list[ev.ChatEvent], list[bytes]]:
    app = FastAPI()
    chat_api.register(app)
    if runner is not None:
        chat_api.set_runner(app, runner, metrics=metrics)
    r = TestClient(app).post("/chat", json=body)
    lines = [x for x in r.content.split(b"\n") if x]
    events = [ev.ChatEvent.model_validate_json(x) for x in lines] if r.status_code == 200 else []
    if events:
        ev.check_event_order(events, complete=True)  # 순서 규칙(응급 seq 0 등) 유지
    return r, events, lines


def _answer(events: list[ev.ChatEvent]) -> ChatResponse:
    return next(e.root.response for e in events if e.root.type == "answer")


def _raw_answer(lines: list[bytes]) -> dict[str, Any]:
    return next(json.loads(x)["response"] for x in lines if json.loads(x)["type"] == "answer")


class RecordingRunner:
    """받은 인자를 기록하고 `finalize` 갱신 하나를 내는 실행기(그래프 없이 HTTP → 실행기 → 응답 연결만 본다)."""

    def __init__(self, answer_fn: Any = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._answer_fn = answer_fn or (lambda **_: finalize([], "요약"))

    def updates(self, question: str, profile: Any, confirmed_item_seqs: Any = (), **kw: Any) -> Any:
        self.calls.append({"question": question, "profile": profile, "confirmed": list(confirmed_item_seqs), **kw})
        yield {"finalize": {"answer": self._answer_fn(**kw), "end_reason": "NORMAL"}}


class LegacyRunner:
    """새 키워드(`prior_drugs`·`took_today`)를 받지 않는 이전 실행기 모양(시험용 가짜들이 이 모양이다)."""

    def updates(self, question: str, profile: Any, confirmed_item_seqs: Any = ()) -> Any:  # noqa: ARG002
        yield {"finalize": {"answer": finalize([], "요약"), "end_reason": "NORMAL"}}


# =========================================================================== 1. 요청 계약(있음/없음/상한/형식)
class TestRequestContract:
    def test_defaults_when_absent(self):
        ctx = ChatRequest(question="q").context
        assert ctx.prior_drugs == [] and ctx.took_today is None
        assert graph_extras(ctx) == {}

    def test_present_values_are_accepted(self):
        ctx = ConversationContext.model_validate({"prior_drugs": Q2_PICKS, "took_today": True})
        assert [d.item_seq for d in ctx.prior_drugs] == [SEQ_COLD, SEQ_AZI] and ctx.took_today is True
        assert ConversationContext.model_validate({"took_today": False}).took_today is False

    def test_prior_drugs_cap_is_confirmed_drugs_max(self):
        ok = [_pick(f"약{i}", f"{200000000 + i}") for i in range(CONFIRMED_DRUGS_MAX)]
        assert len(ConversationContext(prior_drugs=ok).prior_drugs) == CONFIRMED_DRUGS_MAX
        with pytest.raises(ValidationError):
            ConversationContext.model_validate({"prior_drugs": [*ok, _pick("약x", "299999999")]})

    @pytest.mark.parametrize("ctx", [
        {"prior_drugs": [{"name": "a", "item_seq": "12345"}]},                 # 품목기준코드 형식(9자리)
        {"prior_drugs": [{"name": " ", "item_seq": "202106954"}]},             # 빈 이름
        {"prior_drugs": [{"name": "a", "item_seq": "202106954", "x": 1}]},     # 모르는 칸
        {"prior_drugs": "타이레놀"},                                            # 목록 아님
        {"took_today": "예"},                                                   # 문자열(엄격 bool)
        {"took_today": 1},                                                      # 숫자
        {"took_today": "true"},
        {"taken_today": True},                                                  # 모르는 칸
    ])
    def test_malformed_is_422_without_echo(self, ctx):
        r, _, _ = _post(RecordingRunner(), {"question": "비밀질문표지QX7", "context": ctx})
        assert r.status_code == 422
        body = r.json()
        assert body["code"] == "INVALID_REQUEST" and set(body) == {"code", "fields"}
        assert "비밀질문표지QX7" not in r.text and "202106954" not in r.text and "예" not in r.text

    def test_422_fields_name_new_keys(self):
        over = [_pick(f"약{i}", f"{200000000 + i}") for i in range(CONFIRMED_DRUGS_MAX + 1)]
        r, _, _ = _post(RecordingRunner(), {"question": "q", "context": {"prior_drugs": over}})
        assert r.status_code == 422 and r.json()["fields"] == ["context.prior_drugs"]
        r, _, _ = _post(RecordingRunner(), {"question": "q", "context": {"took_today": "예"}})
        assert r.status_code == 422 and r.json()["fields"] == ["context.took_today"]


# =========================================================================== 2. 그래프 입력 변환
class TestGraphExtras:
    def test_prior_drops_display_name_and_codeless_and_dupes(self):
        ctx = ConversationContext.model_validate({"prior_drugs": [
            _pick("타이레놀", SEQ_COLD, "<script>요청 글자</script>"), {"name": "코드 없음"}, _pick("타이레놀", SEQ_COLD),
            {"name": "이름 없는 묶음", "item_seq": SEQ_AZI}]})
        assert prior_from_context(ctx) == [{"item_seq": SEQ_COLD, "input_name": "타이레놀"}, {"item_seq": SEQ_AZI}]
        assert "<script>" not in json.dumps(graph_extras(ctx), ensure_ascii=False)

    def test_extras_only_when_present(self):
        assert graph_extras(ConversationContext.model_validate({"prior_drugs": [], "took_today": None})) == {}
        assert graph_extras(ConversationContext(took_today=False)) == {"took_today": False}
        assert set(graph_extras(ConversationContext.model_validate({"prior_drugs": Q2_PICKS, "took_today": True}))) == {
            "prior_drugs", "took_today"}

    def test_runner_receives_kwargs_only_when_present(self):
        rec = RecordingRunner()
        _post(rec, {"question": "q"})
        _post(rec, {"question": "q", "context": {"prior_drugs": [], "took_today": None}})
        _post(rec, {"question": "q", "context": {"prior_drugs": Q2_PICKS[:1], "took_today": True, "confirmed_drugs": Q2_PICKS[1:]}})
        assert [set(c) - {"question", "profile", "confirmed"} for c in rec.calls] == [set(), set(), {"prior_drugs", "took_today"}]
        assert rec.calls[2]["prior_drugs"] == [{"item_seq": SEQ_COLD, "input_name": "타이레놀"}] and rec.calls[2]["took_today"] is True
        assert rec.calls[2]["confirmed"] == [{"item_seq": SEQ_AZI, "input_name": "이지렉트"}]  # 이번 질문의 되묻기 답은 따로

    def test_legacy_runner_still_works_without_new_fields(self):
        """새 키워드를 받지 않는 실행기도 새 칸이 없는(또는 빈) 요청에서는 그대로 돈다."""
        for ctx in ({}, {"prior_drugs": [], "took_today": None}):
            r, events, _ = _post(LegacyRunner(), {"question": "q", "context": ctx})
            assert r.status_code == 200 and [e.root.type for e in events] == ["answer", "done"]


# =========================================================================== 3. 회귀: 새 칸이 없으면 이전과 같다
def _strip_new(resp: dict[str, Any]) -> dict[str, Any]:
    """2단계 이전 `finalize` 출력 모양(새 키 없음)."""
    out = {k: v for k, v in copy.deepcopy(resp).items()
           if k not in {"sections", "caution_descs", "result_summary", "dose_check", "dose_notice", "redose_notice"}}
    for r in out.get("product_rows") or []:
        for k in ("section", "pair_ref", "caution_desc"):
            r.pop(k, None)
    return out


class TestRegression:
    def test_http_answer_identical_for_absent_or_empty_new_fields(self, dd):
        bodies = [{"question": Q1}, {"question": Q1, "context": {"prior_drugs": [], "took_today": None}}]
        outs = []
        for body in bodies:
            deps, _ = _deps(dd, [], [])
            _, _, lines = _post(GraphRunner.from_deps(deps), body)
            outs.append(lines)
        assert outs[0] == outs[1]

    def test_old_finalize_output_has_no_new_keys(self):
        """`finalize`가 새 칸을 주지 않으면(이전 출력) 응답 글자에 새 키가 없고 줄 순서도 그대로다(새 칸은 기본값 = 생략)."""
        resp = finalize(_three_drugs(), "요약", n_drugs=3)
        old = to_chat_response(_strip_new(resp), end_reason="NORMAL")
        dumped = old.model_dump(mode="json")
        assert not NEW_RESPONSE_KEYS & set(dumped)
        assert not any(NEW_FINDING_KEYS & set(f) for f in dumped["findings"])
        # 그러면 모델 기본값으로 다시 읽어도 같은 응답(받는 쪽에서 빠진 키 = 기본값)
        assert ChatResponse.model_validate(dumped).model_dump(mode="json") == dumped

    def test_single_drug_response_only_adds_section(self, dd):
        """약 하나·되묻기·고지 없는 응답은 새 칸 중 `section`만 더해지고 나머지 글자는 같다."""
        resp = finalize([_item("pregnancy", "FOUND", "pregnancy:SEQ_A", [A], grade="1")], "요약")
        new = to_chat_response(resp, end_reason="NORMAL").model_dump(mode="json")
        old = to_chat_response(_strip_new(resp), end_reason="NORMAL").model_dump(mode="json")
        assert not NEW_RESPONSE_KEYS & set(new)
        assert [{k: v for k, v in f.items() if k != "section"} for f in new["findings"]] == old["findings"]
        assert {k: v for k, v in new.items() if k != "findings"} == {k: v for k, v in old.items() if k != "findings"}


# =========================================================================== 4. q1 → q2 → q3(HTTP, ctx-rca §6 1~6)
class TestTurnsOverHttp:
    def test_q1_asks_both_names(self, dd):
        deps, tm = _deps(dd, [], [])
        r, events, _ = _post(GraphRunner.from_deps(deps), {"question": Q1})
        a = _answer(events)
        assert a.end_reason == "CLARIFY" and list(dict.fromkeys(c.input_name for c in a.candidates)) == ["타이레놀", "이지렉트"]
        assert tm.calls == [] and a.result_summary is None and a.dose_check is None

    def test_q2_resend_with_confirmed_drugs_goes_normal(self, dd):
        deps, _ = _deps(dd, _script(COLD, AZI), [PAIR_DRAFT])
        _, events, _ = _post(GraphRunner.from_deps(deps), {"question": Q1, "context": {"confirmed_drugs": Q2_PICKS}})
        a = _answer(events)
        assert a.end_reason == "NORMAL" and not a.candidates
        pair = next(f for f in a.findings if f.target == "pair" and f.bucket == "found")
        assert pair.section == "core" and a.findings[0] is pair  # 핵심 구역의 짝 줄이 맨 앞(FE-11-08 A)
        assert a.result_summary is not None and a.result_summary.n_drugs == 2 and a.result_summary.pair_only_notice is None
        # 약별 제품 줄에는 병용 배지가 없고 짝 참조만(FE-11-05 A)
        products = [f for f in a.findings if f.target == "product" and f.pair_ref is not None]
        assert products and all(not any(b.kind == "contra_pair" for b in f.badges) for f in products)
        assert all(f.pair_ref.evidence_ids == [pair.evidence_id] for f in products)

    def test_q3_prior_only_ends_with_confirm_question(self, dd):
        deps, tm = _deps(dd, [], [])
        priors = [_pick("타이레놀", SEQ_COLD, COLD), _pick("이지렉트", SEQ_AZI, AZI)]
        _, events, _ = _post(GraphRunner.from_deps(deps), {"question": Q3, "context": {"prior_drugs": priors}})
        a = _answer(events)
        assert a.end_reason == "CLARIFY" and a.summary == fp.CLARIFY_PRIOR_PICK.format(drug=COLD)
        assert (a.candidates[0].input_name, a.candidates[0].item_seq) == ("타이레놀", SEQ_COLD) and tm.calls == []

    def test_q3_confirmed_wins_over_prior(self, dd):
        deps, _ = _deps(dd, [AIMessage("조회 없이 끝")], [{"sentences": [_guide()]}])
        body = {"question": Q3, "context": {"confirmed_drugs": [_pick("타이레놀", SEQ_T500, T500)],
                                            "prior_drugs": [_pick("타이레놀", SEQ_COLD, COLD)]}}
        _, events, _ = _post(GraphRunner.from_deps(deps), body)
        assert _answer(events).end_reason != "CLARIFY"

    def test_q3c_strength_mismatch_uses_general_question(self, dd):
        deps, _ = _deps(dd, [], [])
        _, events, _ = _post(GraphRunner.from_deps(deps), {"question": Q3C, "context": {"prior_drugs": [_pick("타이레놀", SEQ_COLD, COLD)]}})
        a = _answer(events)
        assert a.summary == fp.CLARIFY_MANY_CANDIDATES.format(drug="타이레놀") and a.candidates[0].item_seq == SEQ_T500

    def test_q3_question_does_not_echo_request_display_name(self, dd):
        deps, _ = _deps(dd, [], [])
        body = {"question": Q3, "context": {"prior_drugs": [_pick("타이레놀", SEQ_COLD, "가짜표시이름ZZ9")]}}
        _, _, lines = _post(GraphRunner.from_deps(deps), body)
        assert all("가짜표시이름ZZ9" not in x.decode() for x in lines)  # 확인 질문의 약 이름은 사전 제품명(요청 글자 아님)


# =========================================================================== 5. 약 3개 결과: 구역·요약·접힘 줄, took_today
A, B, C = ("타이레놀콜드-에스정", "SEQ_A"), ("이지렉트정0.5밀리그램", "SEQ_B"), ("게보린릴랙스연질캡슐", "SEQ_C")
KIDS = "한국의약품안전관리원"


def _item(kind: str, status: str, eid: str, drugs: list[tuple[str, str]], **kw: Any) -> dict[str, Any]:
    return {"kind": kind, "status": status, "subject": [d[0] for d in drugs], "evidence_id": eid, "source": KIDS, "as_of": "2026-07-21",
            "flags": [], "dataset_key": kind, "source_kind": "FILE", "drugs": [d[0] for d in drugs], "drug_keys": [d[1] for d in drugs],
            "notes": [], "matches": [{"row_key": "rk", "row_evidence_id": f"{eid}#a", "notice_no": "20250046", "notice_date": "2025-07-14",
                                      "reason": "경련, 반사항진, 이상고열, 혼수 등"}] if status == "FOUND" else [], **kw}


def _three_drugs() -> list[dict[str, Any]]:
    """ISSUE-022 모양(합성): A·B 병용 FOUND, 나머지 짝 목록에 없음, A 용량주의 FOUND, B·C 용량주의 목록에 없음."""
    pair = lambda a, b, s="FOUND": _item("contra_pair", s, f"contra_pair:{a[1]}:{b[1]}", [a, b])  # noqa: E731
    return [pair(A, B), pair(A, C, "NOT_LISTED"), pair(B, C, "NOT_LISTED"),
            _item("dose", "FOUND", "dose:SEQ_A", [A]), _item("dose", "NOT_LISTED", "dose:SEQ_B", [B]),
            _item("dose", "NOT_LISTED", "dose:SEQ_C", [C])]


def _three_answer(**kw: Any) -> dict[str, Any]:
    return finalize(_three_drugs(), None, n_drugs=3, **kw)


class TestThreeDrugs:
    def test_sections_order_and_rest_fold(self):
        r = to_chat_response(_three_answer(), end_reason="NORMAL")
        got = [(f.target, f.section, f.bucket) for f in r.findings]
        assert got[:3] == [("pair", "core", "found"), ("product", "core", "identified"), ("product", "core", "identified")]
        assert [s for _, s, _ in got[3:]] == ["rest"] * (len(got) - 3)
        sections = [f.section for f in r.findings]
        assert sections == sorted(sections, key=["core", "caution", "unconfirmed", "rest"].index)  # 서버가 구역 순서로 준다
        n_rest = sections.count("rest")
        assert r.rest_fold == RestFold(count=n_rest, text=fp.REST_FOLD_LINE.format(n=n_rest))
        assert (r.rest_fold.open_label, r.rest_fold.close_label) == (fp.REST_FOLD_OPEN, fp.REST_FOLD_CLOSE)

    def test_product_rows_pair_ref_and_dose_desc(self):
        r = to_chat_response(_three_answer(), end_reason="NORMAL")
        rows = {f.drug: f for f in r.findings if f.target == "product" and f.evidence_id is None}  # 제품 줄(`product_rows`)만
        assert rows[A[0]].pair_ref == PairRef(count=1, evidence_ids=["contra_pair:SEQ_A:SEQ_B"], text="병용금기 짝 1건에 포함")
        assert rows[A[0]].caution_desc == fp.DOSE_CAUTION_DESC and fp.CAUTION_LABELS["dose"] in rows[A[0]].notes
        assert rows[B[0]].pair_ref is not None and rows[B[0]].caution_desc is None
        # 짝에만 걸린 약 줄의 대표 종류는 줄 글자("찾음")와 짝인 identify(주의·검색 근거 종류 색으로 그리지 않게)
        assert all(f.kind == "identify" and f.text == fp.IDENTIFIED_LINE and not f.badges for f in rows.values())
        assert not any(b.kind == "contra_pair" for f in rows.values() for b in f.badges)

    def test_result_summary(self):
        rs = to_chat_response(_three_answer(), end_reason="NORMAL").result_summary
        assert rs.text == "약 3개를 함께 먹을 때: 병용금기 1건(타이레놀콜드-에스정 + 이지렉트정0.5밀리그램)"
        assert rs.pair_only_notice == fp.PAIR_ONLY_NOTICE and rs.n_pairs == 3 and rs.n_pairs_unchecked == 0
        assert [p.evidence_ids for p in rs.pairs_found] == [["contra_pair:SEQ_A:SEQ_B"]]

    def test_result_summary_uses_display_name_for_item_seq(self):
        """짝 이름이 품목기준코드로만 왔으면(F3) 사전 확정 이름으로 바꾸고 같은 틀로 글자를 다시 채운다."""
        resp = _three_answer()
        resp["result_summary"]["pairs_found"][0]["drugs"] = ["202106954", B[0]]
        resp["result_summary"]["text"] = fp.RESULT_SUMMARY_FOUND.format(n=3, k=1, pairs=f"202106954 + {B[0]}")
        rs = to_chat_response(resp, end_reason="NORMAL", entities=[{"status": "RESOLVED", "item_seq": "202106954", "raw": COLD}]).result_summary
        assert rs.pairs_found[0].drugs == [COLD, B[0]] and rs.text == f"약 3개를 함께 먹을 때: 병용금기 1건({COLD} + {B[0]})"

    @pytest.mark.parametrize("took,check,notice", [(None, True, False), (True, False, True), (False, False, False)])
    def test_took_today_over_http(self, took, check, notice):
        rec = RecordingRunner(lambda **kw: _three_answer(intake_question=True, took_today=kw.get("took_today")))
        ctx = {} if took is None else {"took_today": took}
        r, events, lines = _post(rec, {"question": "같이 먹어도 되나요?", "context": ctx})
        a = _answer(events)
        assert (a.dose_check is not None) is check and (a.dose_notice == fp.DOSE_NOTICE) is notice
        if check:
            assert a.dose_check == DoseCheck(question=fp.DOSE_CHECK_QUESTION, options=["예", "아니요"], drugs=[A[0]],
                                             evidence_ids=["dose:SEQ_A"])
        raw = _raw_answer(lines)
        assert ("dose_check" in raw) is check and ("dose_notice" in raw) is notice  # 값이 없으면 키 자체가 없다

    def test_redose_notice_over_http(self):
        rec = RecordingRunner(lambda **_: _three_answer(redose_question=True))
        _, events, _ = _post(rec, {"question": "또 먹어도 되나요?"})
        a = _answer(events)
        assert a.redose_notice == fp.REDOSE_NOTICE and a.summary != fp.REDOSE_NOTICE

    def test_stream_final_event_carries_new_fields_and_order(self):
        rec = RecordingRunner(lambda **_: _three_answer(intake_question=True))
        r, events, lines = _post(rec, {"question": "같이 먹어도 되나요?"})
        assert [e.root.type for e in events] == ["answer", "done"]
        raw = _raw_answer(lines)
        assert {"result_summary", "rest_fold", "dose_check"} <= set(raw) and not {"dose_notice", "redose_notice"} & set(raw)
        assert all("section" in f for f in raw["findings"])
        # 왕복 동일(FE가 받은 글자로 다시 검증해도 같다). 빈 `name_corrections`는 이벤트 글자에서 빠진다(`events.encode_event`, 이전부터)
        again = ChatResponse.model_validate(raw).model_dump(mode="json")
        assert again.pop("name_corrections") == [] and again == raw


# =========================================================================== 6. 문구는 상수 그대로(검증)
class TestConstantsEnforced:
    def _base(self) -> dict[str, Any]:
        return to_chat_response(_three_answer(intake_question=True), end_reason="NORMAL").model_dump(mode="json")

    @pytest.mark.parametrize("mutate", [
        lambda d: d["result_summary"].update(text="약 3개: 괜찮아요"),
        lambda d: d["result_summary"].update(pair_only_notice=None),
        lambda d: d["result_summary"].update(n_pairs=5),
        lambda d: d["rest_fold"].update(text="나머지 펼치기"),
        lambda d: d["rest_fold"].update(count=99, text=fp.REST_FOLD_LINE.format(n=99)),
        lambda d: d["rest_fold"].update(open_label="열기"),
        lambda d: d["dose_check"].update(question="오늘 몇 알 드셨나요?"),
        lambda d: d["dose_check"].update(options=["네", "아니요"]),
        lambda d: d.update(dose_notice="지어낸 고지"),
        lambda d: d.update(redose_notice="두 시간 뒤 드세요"),
        lambda d: d.update(dose_notice=fp.DOSE_NOTICE),                         # 되묻기와 고지는 함께 오지 않는다
        lambda d: next(f for f in d["findings"] if f.get("pair_ref")).update(
            pair_ref={"count": 1, "evidence_ids": ["x"], "text": "병용금기 짝"}),
        lambda d: next(f for f in d["findings"] if f.get("pair_ref")).update(
            pair_ref={"count": 2, "evidence_ids": ["x"], "text": fp.PAIR_REF_LINE.format(n=2)}),
        lambda d: next(f for f in d["findings"] if f["target"] == "pair").update(
            pair_ref={"count": 1, "evidence_ids": ["x"], "text": fp.PAIR_REF_LINE.format(n=1)}),
        lambda d: next(f for f in d["findings"] if f.get("caution_desc")).update(caution_desc="하루 3알까지"),
        lambda d: d["findings"][0].update(section="danger"),
    ])
    def test_non_constant_or_inconsistent_is_rejected(self, mutate):
        d = self._base()
        assert ChatResponse.model_validate(d)  # 기준은 통과
        mutate(d)
        with pytest.raises(ValidationError):
            ChatResponse.model_validate(d)

    def test_rest_fold_filled_by_server_when_missing(self):
        d = self._base()
        expected = d.pop("rest_fold")
        assert ChatResponse.model_validate(d).rest_fold.model_dump() == expected

    def test_clarify_has_no_result_fields(self):
        d = self._base()
        d.update(end_reason="CLARIFY")
        with pytest.raises(ValidationError):
            ChatResponse.model_validate(d)

    def test_model_classes_reject_non_constants(self):
        with pytest.raises(ValidationError):
            ResultSummary(n_drugs=2, n_pairs=1, n_pairs_unchecked=0, text="x")
        with pytest.raises(ValidationError):
            Finding(bucket="found", evidence_id=None, kind="pregnancy", drug="a", text="t", section="core", caution_desc="x")


# =========================================================================== 7. 로그·이벤트·지표에 값 없음
SECRETS = (SEQ_COLD, SEQ_AZI, SEQ_T500, COLD, AZI, "가짜표시이름ZZ9", "took_today")


def test_logs_events_metrics_have_no_values(dd, caplog):
    caplog.set_level(logging.DEBUG)
    deps, _ = _deps(dd, [], [])
    metrics = SinkMetrics()
    body = {"question": Q3, "context": {"prior_drugs": [_pick("타이레놀", SEQ_COLD, "가짜표시이름ZZ9")], "took_today": True}}
    r, events, lines = _post(GraphRunner.from_deps(deps), body, metrics=metrics)
    assert r.status_code == 200
    blob_logs = "\n".join(rec.getMessage() for rec in caplog.records)
    blob_metrics = json.dumps(metrics.calls, ensure_ascii=False, default=str)
    blob_events = "\n".join(x.decode() for x in lines if json.loads(x)["type"] != "answer")  # 응답 본문은 후보 이름을 싣는 계약
    for s in SECRETS:
        assert s not in blob_logs and s not in blob_metrics and s not in blob_events
    assert "took_today" not in _raw_answer(lines) and "prior_drugs" not in _raw_answer(lines)


def test_graph_internal_events_count_only(dd):
    deps, _ = _deps(dd, [], [])
    st = run_question(build_graph(deps), Q3, prior_drugs=[{"item_seq": SEQ_COLD, "input_name": "타이레놀"}], took_today=True)
    blob = json.dumps(st.get("events") or [], ensure_ascii=False, default=str)
    assert "took_today" not in blob and SEQ_COLD not in blob and COLD not in blob
    router_ev = next(e for e in st["events"] if e.get("event") == "ROUTER")
    assert router_ev["n_prior_asked"] == 1
    assert "took_today" not in json.dumps(response_from_state(st).model_dump(mode="json"), ensure_ascii=False)
