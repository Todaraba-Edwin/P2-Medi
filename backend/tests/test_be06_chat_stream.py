"""BE-06 `/chat` 그래프 연결·NDJSON 스트림 시험(goal 2회차 §2-1·2·7). LLM·공공 API·원격 DB 호출 0.

- 실행기는 가짜 모델(`ScriptedToolModel`·`ScriptedSummary`)로 만든 그래프를 주입한다. 도구 본문은 실제이고 데이터는 합성 소사전·소규모 SQLite
  (`e2e/golden_synth.py`), DUR API는 가짜 `DurClient`(`FakeDur`)다.
- 시험 질문은 합성이다(평가 세트·시험셋 문항 아님).
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from pydantic import PrivateAttr

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import Q_P3, SEQ_AZI, SEQ_COLD, SEQ_KID, SEQ_T500, FakeDur, golden_conn, golden_dict  # noqa: E402

from app.agent import fixed_phrases as fp  # noqa: E402
from app.agent.graph.build import build_graph, run_question  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call  # noqa: E402
from app.agent.graph.trace import GraphTracer, ListSink  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.api import chat as chat_api  # noqa: E402
from app.api import events as ev  # noqa: E402
from app.api.request import AgeInput, ConfirmedDrug, ConversationContext  # noqa: E402
from app.api.runner import GraphRunner, confirmed_from_context, profile_from_context  # noqa: E402
from app.api.schemas import response_from_state  # noqa: E402
from app.tools.drug_dict import DrugDict  # noqa: E402

T500, COLD, AZI = "타이레놀정500밀리그람", "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
MARKER = "비밀질문표지QX7"
Q_PAIR = f"엄마가 {AZI}을 드시는데 감기라서 {COLD}을 사 왔어요. 같이 먹어도 되나요?"
Q_PREG_BY_CONTEXT = f"열이 나요. 집에 {T500}이랑 {COLD}이 있는데 먹어도 되나요?"  # 문장에 임신 신호 없음(요청 묶음으로만 온다)
PAIR_EID = "contra_pair:254000ATB:625201ATB"


def _script(a: str, b: str, **check: Any) -> list[AIMessage]:
    return [
        AIMessage("", tool_calls=[tool_call("identify_drug", {"name": a}, "c1"), tool_call("identify_drug", {"name": b}, "c2")]),
        AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": a}, {"name": b}], **check}, "c3")]),
        AIMessage("조회를 마쳤다"),
    ]


def _guide() -> dict[str, Any]:
    return {"text": "복용 전에 근처 약국·약사에게 꼭 확인해 주세요.", "evidence_ids": [], "claim_type": "guidance", "citations": []}


def _fact(text: str, *eids: str) -> dict[str, Any]:
    return {"text": text, "evidence_ids": list(eids), "claim_type": "fact", "citations": []}


PAIR_DRAFT = {"sentences": [_fact("두 약은 함께 먹으면 안 되는 조합(병용금기)으로 올라 있어요.", PAIR_EID), _guide()]}
PREG_DRAFT = {"sentences": [_fact("타이레놀콜드-에스정에 든 성분이 임부금기 목록에 올라 있어요.", "pregnancy:448001ATB"), _guide()]}


@pytest.fixture(scope="module")
def dd() -> DrugDict:
    return golden_dict()


def _deps(dd: DrugDict, script: list[AIMessage], drafts: list[Any], *, repeat_last: bool = False, tool_model: Any = None, **kw: Any) -> Any:
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    tm = tool_model or ScriptedToolModel(script=list(script), repeat_last=repeat_last)
    return build_deps(dd, ctx, tool_model=tm, summary_model=ScriptedSummary(drafts), system_prompt="시험용 시스템 프롬프트", **kw)


def _client(runner: Any = None) -> TestClient:
    app = FastAPI()
    chat_api.register(app)
    if runner is not None:
        chat_api.set_runner(app, runner)
    return TestClient(app)


def _post(runner: Any, body: dict[str, Any]) -> tuple[Any, list[ev.ChatEvent], list[bytes]]:
    r = _client(runner).post("/chat", json=body)
    lines = r.content.split(b"\n")
    assert lines[-1] == b""  # 마지막 줄도 `\n`으로 끝난다
    events = [ev.ChatEvent.model_validate_json(x) for x in lines[:-1] if x]
    return r, events, lines[:-1]


def _stream(dd: DrugDict, question: str, script: list[AIMessage], drafts: list[Any], *, context: dict[str, Any] | None = None,
            **kw: Any) -> tuple[Any, list[ev.ChatEvent]]:
    body: dict[str, Any] = {"question": question}
    if context is not None:
        body["context"] = context
    r, events, _ = _post(GraphRunner.from_deps(_deps(dd, script, drafts, **kw)), body)
    assert r.status_code == 200 and r.headers["content-type"].startswith(ev.NDJSON_MEDIA_TYPE)
    ev.check_event_order(events, complete=True)
    return r, events


def _types(events: list[ev.ChatEvent]) -> list[str]:
    return [e.root.type for e in events]


def _answer(events: list[ev.ChatEvent]) -> Any:
    return next(e.root.response for e in events if e.root.type == "answer")


def _groups(answer: Any) -> list[str]:
    """되묻기 후보의 묶음 이름(`input_name`)을 나온 순서대로 한 번씩."""
    return list(dict.fromkeys(c.input_name for c in answer.candidates))


# --------------------------------------------------------------------------- ①② 정상 병용 질문
def test_normal_pair_stream_is_ordered_ndjson_ending_normal(dd):
    _, events = _stream(dd, Q_PAIR, _script(AZI, COLD), [PAIR_DRAFT])
    assert _types(events) == ["progress", "progress", "answer", "done"]
    assert [e.root.stage for e in events[:2]] == ["drug_lookup", "contraindication_check"]
    assert [e.root.seq for e in events] == list(range(len(events)))
    assert events[-1].root.end_reason == "NORMAL"
    a = _answer(events)
    assert a.schema_version == "chat_response@v1" and a.emergency is None
    assert any(f.bucket == "found" and f.target == "pair" for f in a.findings)


def test_stream_answer_equals_run_question_response(dd):
    st = run_question(build_graph(_deps(dd, _script(AZI, COLD), [PAIR_DRAFT])), Q_PAIR)
    expected = response_from_state(st).model_dump(mode="json")
    r, events = _stream(dd, Q_PAIR, _script(AZI, COLD), [PAIR_DRAFT])
    assert _answer(events).model_dump(mode="json") == expected
    raw = next(json.loads(x) for x in r.content.split(b"\n") if x and json.loads(x)["type"] == "answer")
    # 전송된 바이트 그대로도 같다. 단 `name_corrections`는 비어 있으면 줄에 싣지 않는다(AG-10-02 A: 칸을 더하기 전과 같은 글자,
    # `events.encode_event`). 빠진 키는 읽는 쪽에서 기본값(빈 목록)이다.
    assert expected["name_corrections"] == [] and "name_corrections" not in raw["response"]
    assert raw["response"] == {k: v for k, v in expected.items() if k != "name_corrections"}


# --------------------------------------------------------------------------- ③ 응급 첫 이벤트
def test_emergency_is_seq_zero_and_tools_still_run(dd):
    _, events = _stream(dd, f"숨쉬기 힘들어요. {AZI}이랑 {COLD}을 같이 먹었어요", _script(AZI, COLD), [PAIR_DRAFT])
    first = events[0].root
    assert first.type == "emergency" and first.seq == 0
    assert first.emergency.text == fp.EMERGENCY_119 and first.emergency.tel == fp.EMERGENCY_119_TEL
    assert "contraindication_check" in [e.root.stage for e in events if e.root.type == "progress"]  # 금기 조회는 막지 않는다
    a = _answer(events)
    assert a.emergency is not None and any(f.bucket == "found" for f in a.findings)


# --------------------------------------------------------------------------- ④ 거절·되묻기·상한
def test_out_of_scope_refuse_ends_with_refuse(dd):
    _, events = _stream(dd, f"{AZI} 처방해 줘", [], [])
    assert _types(events) == ["answer", "done"] and events[-1].root.end_reason == "REFUSE"
    a = _answer(events)
    assert a.route == "REFUSE" and a.summary == fp.REFUSE_MESSAGES["PRESCRIPTION"]


def test_ambiguous_name_ends_with_clarify_candidates(dd):
    _, events = _stream(dd, "엄마가 이지렉트정을 드시는데 타이레놀 콜드-에스를 같이 먹어도 되나요?", [], [])
    assert _types(events) == ["answer", "done"] and events[-1].root.end_reason == "CLARIFY"
    a = _answer(events)
    assert a.candidates and a.candidates_line == fp.CLARIFY_PICK_LINE and not a.findings


def test_two_ambiguous_names_stream_one_answer_with_two_candidate_groups(dd):
    """FE-09-01·02 A: 두 이름이 모두 모호하면 한 `answer` 이벤트에 두 묶음 후보(`input_name`별)와 승인 문구 질문 하나를 싣는다."""
    r, events = _stream(dd, "타이레놀이랑 이지렉트 같이 먹어도 되나요?", [], [])
    assert _types(events) == ["answer", "done"] and events_end(events) == "CLARIFY"
    a = _answer(events)
    assert _groups(a) == ["타이레놀", "이지렉트"] and a.summary.count("?") == 1
    assert a.summary == "'타이레놀', '이지렉트'에 해당하는 약이 여러 개예요. 약마다 하나씩 골라 주시겠어요?"
    assert {c.item_seq for c in a.candidates if c.input_name == "타이레놀"} == {SEQ_T500, SEQ_COLD}
    assert [c.item_seq for c in a.candidates if c.input_name == "이지렉트"] == [SEQ_AZI]
    raw = next(json.loads(x) for x in r.content.split(b"\n") if x and json.loads(x)["type"] == "answer")
    assert [c["input_name"] for c in raw["response"]["candidates"]] == ["타이레놀", "타이레놀", "이지렉트"]  # 전송 바이트도 묶음 순서


def test_call_limit_ends_with_limit_notice(dd):
    always = [AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": AZI}, {"name": COLD}]}, "x1")])]
    _, events = _stream(dd, Q_PAIR, always, [PAIR_DRAFT], repeat_last=True)
    assert events[-1].root.end_reason == "LIMIT"
    a = _answer(events)
    assert a.notice == fp.LIMIT_REACHED and a.summary is None
    assert [e.root.stage for e in events if e.root.type == "progress"] == ["contraindication_check"]  # 같은 단계가 연달아 오면 한 번만


# --------------------------------------------------------------------------- ⑤ 진행 라벨·단계 대응
def test_progress_labels_are_server_constants_and_stage_mapping(dd):
    script = [
        AIMessage("", tool_calls=[tool_call("identify_drug", {"name": AZI}, "c1")]),
        AIMessage("", tool_calls=[tool_call("search_reason", {"query": "병용금기 사유"}, "c2")]),
        AIMessage("", tool_calls=[tool_call("get_label_section", {"item_seq": "202200001", "section": "주의사항"}, "c3")]),
        AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"name": AZI}, {"name": COLD}]}, "c4")]),
        AIMessage("조회를 마쳤다"),
    ]
    _, events = _stream(dd, Q_PAIR, script, [PAIR_DRAFT])
    prog = [e.root for e in events if e.root.type == "progress"]
    assert [p.stage for p in prog] == ["drug_lookup", "evidence_search", "contraindication_check"]
    assert all(p.label == fp.PROGRESS_LABELS[p.stage] for p in prog)


# --------------------------------------------------------------------------- ⑥ 하트비트
class SlowRunner:
    """노드 갱신 사이가 느린 가짜 실행기(그래프 없음). 거절 응답 하나를 낸다."""

    def __init__(self, delay_s: float) -> None:
        self.delay_s = delay_s

    def updates(self, question: str, profile: dict[str, Any] | None, confirmed_item_seqs: Any = ()) -> Any:  # noqa: ARG002
        from app.agent.finalize import finalize

        yield {"guardrail_in": {"emergency": False}}
        time.sleep(self.delay_s)
        yield {"finalize": {"answer": finalize([], refuse_reason="PRESCRIPTION"), "end_reason": "REFUSE"}}


def test_heartbeat_blank_lines_between_slow_events(monkeypatch):
    monkeypatch.setattr(ev, "HEARTBEAT_INTERVAL_S", 0.02)
    r, events, lines = _post(SlowRunner(0.25), {"question": "약 처방해 줘"})
    assert r.status_code == 200
    assert lines.count(b"") >= 2  # 빈 줄(하트비트)
    ev.check_event_order(events, complete=True)  # 빈 줄을 건너뛰면 이벤트 파싱은 그대로다
    assert _types(events) == ["answer", "done"]


# --------------------------------------------------------------------------- ⑦ 질문 비로깅
def test_question_is_not_logged_at_debug(dd, caplog):
    caplog.set_level(logging.DEBUG)
    _stream(dd, f"{MARKER} {Q_PAIR}", _script(AZI, COLD), [PAIR_DRAFT])
    logged = "\n".join(f"{r.getMessage()} {r.args!r}" for r in caplog.records)
    assert MARKER not in logged and AZI not in logged


# --------------------------------------------------------------------------- ⑧ 요청 묶음의 프로필 신호
class RecordingToolModel(ScriptedToolModel):
    """모델 입력(ROUTER_NOTE)을 붙잡는 가짜. 시험 안에서만 내용을 본다."""

    _seen: list[str] = PrivateAttr(default_factory=list)

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any) -> Any:
        self._seen.append("\n".join(str(m.content) for m in messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def test_context_pregnant_reaches_router_profile_and_pregnancy_path(dd):
    tm = RecordingToolModel(script=_script(T500, COLD, pregnancy=True))
    _, events = _stream(dd, Q_PREG_BY_CONTEXT, [], [PREG_DRAFT], context={"pregnant": True}, tool_model=tm)
    note = json.loads(re.search(r"<<<ROUTER_NOTE\n(.*)\nROUTER_NOTE>>>", tm._seen[0], re.S).group(1))
    assert note["pregnant"] is True and note["age_years"] is None  # 문장에 없어도 요청 묶음 값이 프로필로 간다
    a = _answer(events)
    assert events[-1].root.end_reason == "NORMAL"
    assert any(f.kind == "pregnancy" and f.bucket == "found" for f in a.findings)


def test_question_sentence_overrides_context_profile(dd):
    tm = RecordingToolModel(script=_script(T500, COLD))
    q = f"임신은 아니에요. {T500}이랑 {COLD}을 같이 먹어도 되나요?"
    _stream(dd, q, [], [{"sentences": [_guide()]}], context={"pregnant": True}, tool_model=tm)
    note = json.loads(re.search(r"<<<ROUTER_NOTE\n(.*)\nROUTER_NOTE>>>", tm._seen[0], re.S).group(1))
    assert note["pregnant"] is False


@pytest.mark.parametrize("age,expected", [
    ({"lower": 7, "upper": 7, "unit": "세"}, 7.0),
    ({"lower": 18, "upper": 18, "unit": "개월"}, 1.5),
    ({"lower": 6, "upper": 11, "unit": "세"}, None),  # 구간: 나이를 특정할 수 없으면 넘기지 않는다(FE-07-18 A)
    (None, None),
])
def test_profile_from_context_age_only_when_single_value(age, expected):
    ctx = ConversationContext(age=AgeInput(**age) if age else None, pregnant=None)
    prof = profile_from_context(ctx)
    assert (prof or {}).get("age_years") == expected
    if expected is None:
        assert prof is None
    assert profile_from_context(ConversationContext(pregnant=False)) == {"age_years": None, "pregnant": False}


def test_confirmed_drugs_without_item_seq_or_already_resolved_change_nothing(dd):
    """코드 없는 고른 약은 쓰지 않고(이름만으로는 확정하지 않는다), 이미 확정된 질문은 고른 약이 있어도 응답이 같다(AG-05-03 A)."""
    _, a = _stream(dd, Q_PAIR, _script(AZI, COLD), [PAIR_DRAFT])
    _, b = _stream(dd, Q_PAIR, _script(AZI, COLD), [PAIR_DRAFT], context={"confirmed_drugs": [{"name": T500}]})
    _, c = _stream(dd, Q_PAIR, _script(AZI, COLD), [PAIR_DRAFT],
                   context={"confirmed_drugs": [{"name": AZI, "item_seq": SEQ_AZI}, {"name": COLD, "item_seq": SEQ_COLD}]})
    assert _answer(a) == _answer(b) == _answer(c)


# --------------------------------------------------------------------------- ⑧-2 되묻기에서 고른 약(AG-05-03 A)
def test_second_turn_with_confirmed_drugs_skips_clarify_and_runs_lookup(dd):
    """(a) 턴 1은 되묻기, 턴 2(같은 질문 + 고른 약 두 개)는 되묻기 없이 조회로 진행해 병용금기를 찾는다."""
    _, first = _stream(dd, Q_P3, [], [])
    assert events_end(first) == "CLARIFY"
    tm = RecordingToolModel(script=_script(AZI, COLD))
    picked = {"confirmed_drugs": [{"name": AZI, "item_seq": SEQ_AZI}, {"name": COLD, "item_seq": SEQ_COLD}]}
    _, second = _stream(dd, Q_P3, [], [PAIR_DRAFT], context=picked, tool_model=tm)
    assert events_end(second) == "NORMAL"
    assert [e.root.stage for e in second if e.root.type == "progress"] == ["drug_lookup", "contraindication_check"]
    a = _answer(second)
    assert not a.candidates and any(f.bucket == "found" and f.target == "pair" for f in a.findings)
    note = json.loads(re.search(r"<<<ROUTER_NOTE\n(.*)\nROUTER_NOTE>>>", tm._seen[0], re.S).group(1))
    assert [(d["status"], d["item_seq"]) for d in note["drug_candidates"]] == [("RESOLVED", SEQ_AZI), ("RESOLVED", SEQ_COLD)]


def test_one_confirmed_drug_keeps_only_the_remaining_ambiguous_names(dd):
    """턴 1은 모호한 이름 전부를 묶음으로 한 번에 보인다(FE-09-01 A). 고른 약이 하나면 그 약만 확정하고 남은 묶음만 다시 묻는다."""
    _, first = _stream(dd, Q_P3, [], [])
    _, second = _stream(dd, Q_P3, [], [], context={"confirmed_drugs": [{"name": AZI, "item_seq": SEQ_AZI}]})
    assert events_end(first) == events_end(second) == "CLARIFY"
    assert _groups(_answer(first)) == ["이지렉트정", "타이레놀", "콜드-에스"]
    assert _answer(first).summary == fp.CLARIFY_MANY_DRUGS.format(drugs="'이지렉트정', '타이레놀', '콜드-에스'")
    assert _groups(_answer(second)) == ["타이레놀", "콜드-에스"] and AZI not in {c.name for c in _answer(second).candidates}
    assert COLD in {c.name for c in _answer(second).candidates}


@pytest.mark.parametrize("picked", [
    [{"name": AZI, "item_seq": "999999999"}],  # 사전에 없는 코드
    [{"name": "어린이타이레놀현탁액", "item_seq": SEQ_KID}],  # 사전에 있지만 질문 속 이름의 후보가 아닌 코드(질문에 없는 약은 더하지 않는다)
    [{"name": AZI}],  # 코드 없음
])
def test_unusable_confirmed_drugs_keep_existing_clarify(dd, picked):
    """(b) 확정에 쓸 수 없는 고른 약은 무시하고 지금처럼 되묻는다(응답이 고른 약 없을 때와 같다)."""
    _, base = _stream(dd, Q_P3, [], [])
    _, got = _stream(dd, Q_P3, [], [], context={"confirmed_drugs": picked})
    assert events_end(got) == "CLARIFY" and _answer(got) == _answer(base)


@pytest.mark.parametrize("question,script,drafts", [(Q_P3, [], []), (Q_PAIR, _script(AZI, COLD), [PAIR_DRAFT])])
def test_empty_confirmed_drugs_is_same_as_no_context(dd, question, script, drafts):
    """(c) 빈 `confirmed_drugs`는 요청 묶음이 없을 때와 같다(평가 경로는 늘 비어 있다)."""
    _, a = _stream(dd, question, list(script), list(drafts))
    _, b = _stream(dd, question, list(script), list(drafts), context={"confirmed_drugs": []})
    assert _answer(a) == _answer(b)


def test_confirmed_drug_values_are_not_logged_or_measured(dd, caplog):
    """(d) 고른 약의 이름·코드는 로그·서비스 지표에 남지 않는다(이름은 그래프로도 넘기지 않는다)."""
    caplog.set_level(logging.DEBUG)
    metrics = ListSink()
    app = FastAPI()
    chat_api.register(app)
    chat_api.set_runner(app, GraphRunner.from_deps(_deps(dd, _script(AZI, COLD), [PAIR_DRAFT])), metrics=metrics)
    body = {"question": Q_P3, "context": {"confirmed_drugs": [{"name": f"{MARKER}정", "item_seq": SEQ_AZI}, {"name": COLD, "item_seq": SEQ_COLD}]}}
    r = TestClient(app).post("/chat", json=body)
    assert r.status_code == 200 and MARKER not in r.text
    logged = "\n".join(f"{x.getMessage()} {x.args!r}" for x in caplog.records)
    assert MARKER not in logged and SEQ_AZI not in logged and SEQ_COLD not in logged
    measured = json.dumps(metrics.records, ensure_ascii=False, default=str)
    assert metrics.records and MARKER not in measured and SEQ_AZI not in measured and SEQ_COLD not in measured


def test_confirmed_from_context_keeps_only_item_seqs_in_order():
    ctx = ConversationContext(confirmed_drugs=[ConfirmedDrug(name="가", item_seq=SEQ_COLD), ConfirmedDrug(name="나"),
                                               ConfirmedDrug(name="다", item_seq=SEQ_AZI), ConfirmedDrug(name="라", item_seq=SEQ_COLD)])
    assert confirmed_from_context(ctx) == [SEQ_COLD, SEQ_AZI]
    assert confirmed_from_context(ConversationContext()) == []


def test_confirmed_from_context_carries_input_name_when_given():
    """FE-09-05 A: `input_name`이 있으면 `{item_seq, input_name}`로, 없으면 이전처럼 코드 문자열로 넘긴다. 표시용 `name`은 넘기지 않는다.
    같은 코드라도 묶음 이름이 다르면 따로 남긴다(겹친 묶음에서 같은 약을 골라도 두 이름 모두 확정)."""
    ctx = ConversationContext(confirmed_drugs=[
        ConfirmedDrug(name="가", item_seq=SEQ_AZI, input_name="이지렉트정"), ConfirmedDrug(name="나", item_seq=SEQ_COLD, input_name="타이레놀"),
        ConfirmedDrug(name="다", item_seq=SEQ_COLD, input_name="콜드-에스"), ConfirmedDrug(name="라", item_seq=SEQ_COLD, input_name="타이레놀"),
        ConfirmedDrug(name="마", item_seq=SEQ_T500), ConfirmedDrug(name="바", input_name="타이레놀")])
    assert confirmed_from_context(ctx) == [{"item_seq": SEQ_AZI, "input_name": "이지렉트정"}, {"item_seq": SEQ_COLD, "input_name": "타이레놀"},
                                           {"item_seq": SEQ_COLD, "input_name": "콜드-에스"}, SEQ_T500]


@pytest.mark.parametrize("order", [(0, 1, 2), (0, 2, 1)])
def test_named_picks_from_overlapping_groups_all_reach_lookup(dd, order):
    """FE-09-05 A: 턴 1의 세 묶음(`이지렉트정`·`타이레놀`·`콜드-에스`, 뒤 둘의 후보가 겹침)에서 각각 고른 약을 `input_name`과 함께 보내면
    보낸 순서와 상관없이 세 약이 모두 확정돼 조회로 간다(이름 없이 묶음 순서로 보내면 정500이 빠지던 경우)."""
    _, first = _stream(dd, Q_P3, [], [])
    cands = {(c.input_name, c.item_seq) for c in _answer(first).candidates}
    picks = [("이지렉트정", SEQ_AZI, AZI), ("타이레놀", SEQ_T500, T500), ("콜드-에스", SEQ_COLD, COLD)]
    assert {(n, s) for n, s, _ in picks} <= cands  # 화면이 보낼 값은 턴 1 응답의 후보 그대로다
    body = [{"name": name, "item_seq": seq, "input_name": n} for n, seq, name in (picks[i] for i in order)]
    tm = RecordingToolModel(script=[AIMessage("조회를 마쳤다")])
    _, second = _stream(dd, Q_P3, [], [{"sentences": [_guide()]}], context={"confirmed_drugs": body}, tool_model=tm)
    assert events_end(second) == "NORMAL" and not _answer(second).candidates
    note = json.loads(re.search(r"<<<ROUTER_NOTE\n(.*)\nROUTER_NOTE>>>", tm._seen[0], re.S).group(1))
    assert [(d["raw"], d["status"], d["item_seq"]) for d in note["drug_candidates"]] == [
        ("이지렉트정", "RESOLVED", SEQ_AZI), ("타이레놀", "RESOLVED", SEQ_T500), ("콜드-에스", "RESOLVED", SEQ_COLD)]


def test_confirmed_input_name_is_not_logged_or_measured(dd, caplog):
    """`input_name`도 고른 약 값이라 로그·서비스 지표에 남기지 않는다."""
    caplog.set_level(logging.DEBUG)
    metrics = ListSink()
    app = FastAPI()
    chat_api.register(app)
    chat_api.set_runner(app, GraphRunner.from_deps(_deps(dd, _script(AZI, COLD), [PAIR_DRAFT])), metrics=metrics)
    body = {"question": Q_P3, "context": {"confirmed_drugs": [{"name": AZI, "item_seq": SEQ_AZI, "input_name": f"{MARKER}정"}]}}
    r = TestClient(app).post("/chat", json=body)
    assert r.status_code == 200 and MARKER not in r.text
    logged = "\n".join(f"{x.getMessage()} {x.args!r}" for x in caplog.records)
    assert MARKER not in logged and SEQ_AZI not in logged
    measured = json.dumps(metrics.records, ensure_ascii=False, default=str)
    assert metrics.records and MARKER not in measured


def events_end(events: list[ev.ChatEvent]) -> str | None:
    return events[-1].root.end_reason


# --------------------------------------------------------------------------- ⑨ 실행기 미주입·trace 끔
def test_without_runner_still_501():
    r = _client(None).post("/chat", json={"question": Q_PAIR})
    assert r.status_code == 501 and r.json() == {"code": "NOT_IMPLEMENTED", "fields": []}


def test_bad_request_is_422_even_with_runner(dd):
    r = _client(GraphRunner.from_deps(_deps(dd, [], []))).post("/chat", json={"question": "  "})
    assert r.status_code == 422 and r.json()["code"] == "INVALID_REQUEST"


def test_runner_from_deps_drops_tracer_in_service_route(dd):
    sink = ListSink()
    tracer = GraphTracer(sink=sink, model="gpt-6-luna", api_enabled=True)
    _stream(dd, Q_PAIR, _script(AZI, COLD), [PAIR_DRAFT], tracer=tracer)
    assert sink.records == []  # 서비스 경로는 trace를 남기지 않는다(RFP-22-06 A)


# --------------------------------------------------------------------------- §2-2 오류 경로
class BoomRunner:
    def __init__(self, *, after: int = 0) -> None:
        self.after = after

    def updates(self, question: str, profile: dict[str, Any] | None, confirmed_item_seqs: Any = ()) -> Any:  # noqa: ARG002
        if self.after:
            yield {"model": {"messages": [AIMessage("", tool_calls=[tool_call("identify_drug", {"name": "x"}, "c1")])]}}
        raise RuntimeError(f"폭발표지ZK9 {question}")


@pytest.mark.parametrize("after", [0, 1])
def test_runner_exception_ends_with_error_then_done(after, caplog):
    caplog.set_level(logging.DEBUG)
    r, events, _ = _post(BoomRunner(after=after), {"question": f"{MARKER} 먹어도 돼?"})
    assert r.status_code == 200
    ev.check_event_order(events, complete=True)
    assert _types(events)[-2:] == ["error", "done"] and len(events) == 2 + after
    err, done = events[-2].root, events[-1].root
    assert err.code == "INTERNAL_ERROR" and err.message == ev.ERROR_MESSAGES["INTERNAL_ERROR"] == fp.ERROR_MESSAGES["INTERNAL_ERROR"]
    assert done.end_reason is None
    body = r.content.decode("utf-8")
    assert "폭발표지ZK9" not in body and MARKER not in body and "RuntimeError" not in body
    logged = "\n".join(f"{x.getMessage()} {x.args!r}" for x in caplog.records)
    assert "폭발표지ZK9" not in logged and MARKER not in logged
    assert "RuntimeError" in logged  # 예외 종류 이름만 로그에 남긴다


class BadAnswerRunner:
    """응답 변환이 실패하는 최종 상태(고정 문구가 빠진 answer)."""

    def updates(self, question: str, profile: dict[str, Any] | None, confirmed_item_seqs: Any = ()) -> Any:  # noqa: ARG002
        yield {"finalize": {"answer": {"summary": "x", "disclaimer": "지어낸 고지"}, "end_reason": "NORMAL"}}


class NoAnswerRunner:
    def updates(self, question: str, profile: dict[str, Any] | None, confirmed_item_seqs: Any = ()) -> Any:  # noqa: ARG002
        yield {"guardrail_in": {"emergency": False}}


@pytest.mark.parametrize("runner", [BadAnswerRunner(), NoAnswerRunner()])
def test_response_conversion_failure_is_internal_error(runner):
    r, events, _ = _post(runner, {"question": "먹어도 돼?"})
    ev.check_event_order(events, complete=True)
    assert _types(events) == ["error", "done"] and events[0].root.code == "INTERNAL_ERROR"
    assert "지어낸 고지" not in r.content.decode("utf-8")


# --------------------------------------------------------------------------- §2-7 AG-06 끝단
CODE_RE = re.compile(r"D\d{6}|\d{6}[A-Z]{3}")


def test_summary_and_detail_are_separate_and_summary_has_no_codes(dd):
    draft = {"sentences": [
        _fact("성분코드 D000200과 625201ATB 조합이 병용금기로 올라 있어요.", PAIR_EID),  # 코드가 든 문장: 필터가 걸러야 한다
        _fact("두 약은 함께 먹으면 안 되는 조합(병용금기)으로 올라 있어요.", PAIR_EID),
        _guide(),
    ]}
    _, events = _stream(dd, Q_PAIR, _script(AZI, COLD), [draft])
    a = _answer(events)
    assert events[-1].root.end_reason == "NORMAL"
    assert a.summary and not CODE_RE.search(a.summary) and "병용금기" in a.summary
    assert a.detail and all(d.evidence_id for d in a.detail)  # 근거 상세는 요약과 따로 있다
    assert a.summary not in json.dumps([d.model_dump(mode="json") for d in a.detail], ensure_ascii=False)
    assert "LLM_SUMMARY" not in a.model_dump_json()


def test_all_sentences_filtered_twice_falls_back_to_code_summary(dd):
    bad = {"sentences": [_fact("성분코드 D000200과 625201ATB 조합이에요.", PAIR_EID)]}
    script = [*_script(AZI, COLD), AIMessage("다시 정리")]
    deps = _deps(dd, script, [bad, bad])
    st = run_question(build_graph(deps), Q_PAIR)
    assert [e["reasons"] for e in st["events"] if e["event"] in ("REWIND", "VALIDATION_FALLBACK")] == [["ALL_SENTENCES_FILTERED"]] * 2
    _, events = _stream(dd, Q_PAIR, script, [bad, bad])
    assert events[-1].root.end_reason == "VALIDATION_FALLBACK"
    a = _answer(events)
    from app.agent.finalize import fallback_summary

    assert a.summary == fallback_summary(st["evidence"]) and not CODE_RE.search(a.summary)
    assert a.summary.startswith(fp.FALLBACK_SOME_CONFIRMED.split("{")[0])
    assert any(f.bucket == "found" for f in a.findings)  # 코드 문구로 항목은 남는다
    assert "LLM_SUMMARY" not in a.model_dump_json()
