"""BE-06 스트림 이벤트 `chat_event@v1` 시험(외부 호출 0): 모양·라벨 상수(BE-06-09 A)·순서 규칙(응급 첫 이벤트 PRD-01-02, seq)·하트비트(BE-06-10 A)."""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

from app.agent import fixed_phrases as fp
from app.agent.finalize import finalize
from app.api import events as ev
from app.api.events import (
    CLIENT_IDLE_TIMEOUT_S,
    ERROR_CODES,
    EVENT_SCHEMA_VERSION,
    HEARTBEAT_INTERVAL_S,
    HEARTBEAT_LINE,
    STAGES,
    AnswerEvent,
    ChatEvent,
    DoneEvent,
    EmergencyEvent,
    ErrorEvent,
    EventOrderError,
    EventSequence,
    ProgressEvent,
    check_event_order,
    encode_event,
    ndjson_with_heartbeat,
)
from app.api.schemas import to_chat_response

ITEM = {"kind": "pregnancy", "status": "FOUND", "subject": ["448001ATB"], "evidence_id": "pregnancy:448001ATB", "source": "한국의약품안전관리원",
        "as_of": "2026-07-21", "flags": [], "dataset_key": "pregnancy", "source_kind": "FILE", "drugs": ["타이레놀콜드-에스정"],
        "matches": [{"row_key": "p0", "row_evidence_id": "pregnancy:448001ATB#0", "grade": "2", "notice_no": "20200061", "notice_date": "2020-06-30"}]}


def resp(emergency: bool = False, end_reason: str = "NORMAL"):
    return to_chat_response(finalize([ITEM], model_summary="요약", emergency=emergency), end_reason=end_reason)


def normal_stream():
    return [ev.progress(0, "drug_lookup"), ev.progress(1, "contraindication_check"), ev.progress(2, "evidence_search"),
            ev.answer(3, resp()), ev.done(4, "NORMAL")]


def emergency_stream():
    return [ev.emergency(0), ev.progress(1, "drug_lookup"), ev.answer(2, resp(emergency=True)), ev.done(3, "NORMAL")]


# --------------------------------------------------------------------------- BE-06-09 A: progress.label은 서버 상수에서만
def test_progress_labels_are_prd_text_and_screen_safe():
    assert STAGES == ("drug_lookup", "contraindication_check", "evidence_search")
    assert [fp.PROGRESS_LABELS[s] for s in STAGES] == ["약 찾는 중", "금기 확인 중", "근거 찾는 중"]  # PJ2-PRD.md 15.4절 로딩 행 글자 그대로
    for label in fp.PROGRESS_LABELS.values():
        assert not [t for t in fp.FORBIDDEN_SCREEN_TERMS if t in label]  # "단계" 등 금지어 없음
        assert label not in fp.DRAFT_KEYS


def test_progress_label_must_equal_constant():
    for s in STAGES:
        assert ev.progress(0, s).label == fp.PROGRESS_LABELS[s]
    with pytest.raises(ValidationError):
        ProgressEvent(seq=0, stage="drug_lookup", label="약 찾는 중이에요")
    with pytest.raises(ValidationError):
        ProgressEvent(seq=0, stage="drug_lookup", label=fp.PROGRESS_CONTRA_CHECK)  # 다른 단계의 문구
    with pytest.raises(ValidationError):
        ProgressEvent(seq=0, stage="thinking", label="생각 중")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- 모양·판별 유니온·NDJSON
def test_event_lines_are_flat_type_discriminated_ndjson():
    lines = b"".join(encode_event(e) for e in normal_stream()).decode("utf-8").split("\n")
    assert lines[-1] == "" and all(lines[:-1])  # 한 줄에 JSON 하나, 줄 끝 \n
    objs = [json.loads(x) for x in lines[:-1]]
    assert [o["type"] for o in objs] == ["progress", "progress", "progress", "answer", "done"]
    assert [o["seq"] for o in objs] == [0, 1, 2, 3, 4] and {o["schema_version"] for o in objs} == {EVENT_SCHEMA_VERSION}
    assert objs[0] == {"seq": 0, "schema_version": "chat_event@v1", "type": "progress", "stage": "drug_lookup", "label": "약 찾는 중"}
    assert objs[3]["response"]["schema_version"] == "chat_response@v1" and objs[4]["end_reason"] == "NORMAL"
    assert "event" not in objs[0] and "data" not in objs[0]  # mock(event+data) 형식이 아니다
    parsed = [ChatEvent.model_validate_json(x).root for x in lines[:-1]]
    assert [type(p) for p in parsed] == [ProgressEvent, ProgressEvent, ProgressEvent, AnswerEvent, DoneEvent]
    for bad in ({**objs[0], "type": "thinking"}, {**objs[0], "extra": 1}, {**objs[4], "schema_version": "chat_event@v0"}):
        with pytest.raises(ValidationError):
            ChatEvent.model_validate(bad)


def test_error_event_codes_and_pending_message():
    e = ev.error(0, "INTERNAL_ERROR")
    assert e.code in ERROR_CODES and e.message is None  # 문구 대기: 문구를 지어내지 않는다
    with pytest.raises(ValidationError):
        ErrorEvent(seq=0, code="INTERNAL_ERROR", message="지어낸 오류 문구")
    with pytest.raises(ValidationError):
        ErrorEvent(seq=0, code="SOMETHING")  # type: ignore[arg-type]
    assert json.loads(encode_event(e)) == {"seq": 0, "schema_version": "chat_event@v1", "type": "error", "code": "INTERNAL_ERROR", "message": None}


# --------------------------------------------------------------------------- 순서 규칙
def test_valid_sequences():
    check_event_order(normal_stream())
    check_event_order(emergency_stream())
    check_event_order([ev.error(0, "TIMEOUT"), ev.done(1, None)])  # answer 없는 done은 error 뒤에만
    check_event_order([ev.emergency(0), ev.error(1, "INTERNAL_ERROR"), ev.done(2, None)])  # 응급 뒤 오류여도 119는 이미 나갔다
    check_event_order([ev.answer(0, resp())], complete=False)  # 진행 중 앞부분
    check_event_order([ChatEvent(e) for e in normal_stream()])


@pytest.mark.parametrize("events,rule", [
    (lambda: [ev.progress(0, "drug_lookup"), ev.progress(2, "evidence_search")], 1),                               # seq 빠짐
    (lambda: [ev.progress(1, "drug_lookup")], 1),                                                                     # 0에서 시작 안 함
    (lambda: [ev.progress(0, "drug_lookup"), ev.emergency(1), ev.answer(2, resp(emergency=True)), ev.done(3, "NORMAL")], 2),  # 응급이 첫 이벤트가 아님
    (lambda: [ev.progress(0, "drug_lookup"), ev.answer(1, resp(emergency=True)), ev.done(2, "NORMAL")], 2),      # 응답엔 응급, 첫 이벤트 없음
    (lambda: [ev.emergency(0), ev.answer(1, resp()), ev.done(2, "NORMAL")], 2),                                    # 첫 이벤트 응급, 응답엔 없음
    (lambda: [ev.answer(0, resp()), ev.progress(1, "drug_lookup"), ev.done(2, "NORMAL")], 3),                    # answer 뒤 progress
    (lambda: [ev.answer(0, resp()), ev.error(1, "INTERNAL_ERROR"), ev.done(2, None)], 4),                        # answer 뒤 error
    (lambda: [ev.answer(0, resp()), ev.answer(1, resp()), ev.done(2, "NORMAL")], 4),                              # answer 두 번
    (lambda: [ev.progress(0, "drug_lookup"), ev.done(1, None)], 5),                                                # answer 없는 done
    (lambda: [ev.answer(0, resp()), ev.done(1, "LIMIT")], 5),                                                      # end_reason 불일치
    (lambda: [ev.error(0, "TIMEOUT"), ev.done(1, "NORMAL")], 5),                                                   # error 뒤 done은 null
    (lambda: [ev.answer(0, resp()), ev.done(1, "NORMAL"), ev.done(2, "NORMAL")], 5),                              # done 뒤 이벤트
    (lambda: [ev.progress(0, "drug_lookup"), ev.answer(1, resp())], 5),                                           # 완결 스트림인데 done 없음
])
def test_invalid_sequences(events, rule):
    with pytest.raises(EventOrderError) as ei:
        check_event_order(events())
    assert ei.value.rule == rule


def test_event_sequence_builder_assigns_seq_and_blocks_bad_order():
    s = EventSequence()
    s.emergency()
    s.progress("drug_lookup")
    s.answer(resp(emergency=True))
    s.done()
    assert [e.seq for e in s.events] == [0, 1, 2, 3] and isinstance(s.events[0], EmergencyEvent)
    assert s.events[-1].end_reason == "NORMAL"
    check_event_order(s.events)
    late = EventSequence()
    late.progress("drug_lookup")
    with pytest.raises(EventOrderError):
        late.emergency()  # 응급은 첫 자리에만(LLM 호출 전 guardrail_in)
    no_answer = EventSequence()
    with pytest.raises(EventOrderError):
        no_answer.done()


# --------------------------------------------------------------------------- BE-06-10 A: 하트비트
def test_heartbeat_constants():
    assert HEARTBEAT_LINE == b"\n" and HEARTBEAT_INTERVAL_S < CLIENT_IDLE_TIMEOUT_S == 60.0


def test_heartbeat_fills_gaps_without_cancelling_source():
    async def slow():
        yield ev.progress(0, "drug_lookup")
        await asyncio.sleep(0.12)  # 간격보다 긴 침묵
        yield ev.answer(1, resp())
        yield ev.done(2, "NORMAL")

    async def collect():
        return [x async for x in ndjson_with_heartbeat(slow(), interval_s=0.03)]

    out = asyncio.run(collect())
    events = [json.loads(x) for x in out if x != HEARTBEAT_LINE]
    assert [e["type"] for e in events] == ["progress", "answer", "done"]  # 원본은 끊기지 않는다
    beats = [i for i, x in enumerate(out) if x == HEARTBEAT_LINE]
    assert beats and all(0 < i < len(out) - 2 for i in beats)  # progress와 answer 사이에만
    assert b"".join(out).count(b"\n") == len(out)  # 하트비트·이벤트 모두 줄 단위


def test_no_heartbeat_when_events_are_fast():
    async def fast():
        for e in normal_stream():
            yield e

    async def collect():
        return [x async for x in ndjson_with_heartbeat(fast(), interval_s=5)]

    out = asyncio.run(collect())
    assert HEARTBEAT_LINE not in out and len(out) == 5
