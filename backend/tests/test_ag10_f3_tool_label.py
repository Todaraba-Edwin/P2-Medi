"""AG-10-07 A(이슈 F3 원천 수정) 시험: 모델이 확정된 약을 `{"item_seq": ...}`만으로 넘겨도 `check_contraindications`의 표시명
(`drugs`·`subject`·`input_name`)이 품목기준코드가 아니라 사전 확정 제품명이다. LLM·공공 API·원격 DB 호출 0.

- 바뀌는 것은 표시명뿐이다: 근거 ID·`drug_keys`·판정(상태)은 이름으로 넘긴 호출과 같다.
- 사전에 없는 코드는 지어내지 않고 지금까지처럼 코드를 둔다.
- 쌍 줄 머리(`finalize` `entries[].drug`)와 요약 모델 입력의 도구 결과 블록(`_summary_messages`, AG-10-08 B)도 이름이 된다.
- API 응답 변환(`app.api.schemas.display_names`, BE-06 F3)은 안전망으로 그대로다(이 시험은 그 변환을 거치지 않는 그래프 상태를 본다).
근거 항목·사전은 합성이다(`tests/e2e/golden_synth.py`, 평가 세트·시험셋 문항 아님).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import SEQ_AZI, SEQ_COLD, FakeDur, golden_conn, golden_dict  # noqa: E402

from app.agent.graph.build import build_graph, run_question  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.agent.tools.check_contraindications import check_contraindications  # noqa: E402
from app.agent.tools.contract import DATA_CLOSE, DATA_OPEN  # noqa: E402
from app.agent.tools.schemas import CheckContraArgs  # noqa: E402

COLD, AZI = "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"  # golden_synth 사전의 제품명
UNKNOWN_SEQ = "999999999"  # 사전에 없는 9자리 코드(합성)
PAIR_EID = "contra_pair:254000ATB:625201ATB"
NAME_FIELDS = ("drugs", "subject", "input_name")


@pytest.fixture(scope="module")
def dd() -> Any:
    return golden_dict()


def _ctx(dd: Any) -> Any:
    return build_tool_context(dd, mode="eval", conn_factory=golden_conn)  # API 끔(평가 경로와 같은 모양)


def _check(dd: Any, drugs: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    return check_contraindications(CheckContraArgs(drugs=drugs, **kw), _ctx(dd))


def _shown(items: list[dict[str, Any]]) -> list[str]:
    """표시명 칸의 값 전부(근거 ID·`drug_keys`·`cause_codes`는 키라서 뺀다)."""
    out: list[str] = []
    for it in items:
        for k in NAME_FIELDS:
            v = it.get(k)
            out.extend(str(x) for x in (v if isinstance(v, list) else [v]) if x)
    return out


# --------------------------------------------------------------------------- 도구 결과
def test_item_seq_only_drugs_are_shown_by_dictionary_name(dd):
    res = _check(dd, [{"item_seq": SEQ_COLD}, {"item_seq": SEQ_AZI}], pregnancy=True)
    shown = _shown(res["items"])
    assert SEQ_COLD not in shown and SEQ_AZI not in shown, shown
    assert {COLD, AZI} <= set(shown)
    pair = next(it for it in res["items"] if it["evidence_id"] == PAIR_EID)
    assert pair["drugs"] == [COLD, AZI] and pair["drug_keys"] == [SEQ_COLD, SEQ_AZI]  # 키는 코드 그대로


def test_only_display_changes_judgement_and_ids_match_the_named_call(dd):
    by_seq = _check(dd, [{"item_seq": SEQ_COLD}, {"item_seq": SEQ_AZI}], pregnancy=True)
    by_name = _check(dd, [{"name": COLD}, {"name": AZI}], pregnancy=True)
    strip = lambda r: sorted((it["evidence_id"], it["kind"], it["status"], tuple(it.get("drug_keys") or [])) for it in r["items"])  # noqa: E731
    assert strip(by_seq) == strip(by_name)
    assert by_seq["known_ids"] == by_name["known_ids"] and by_seq["input_units"] == by_name["input_units"]
    assert sorted(_shown(by_seq["items"])) == sorted(_shown(by_name["items"]))  # 사용자가 사전 이름을 적은 것과 같은 표시


def test_unknown_item_seq_keeps_the_code_and_never_invents_a_name(dd):
    res = _check(dd, [{"item_seq": UNKNOWN_SEQ}, {"item_seq": SEQ_AZI}])
    ident = next(it for it in res["items"] if it["evidence_id"] == f"identify:{UNKNOWN_SEQ}")
    assert ident["status"] == "UNIDENTIFIED" and "CODE_NOT_LINKED" in ident["flags"]
    assert ident["drugs"] == [UNKNOWN_SEQ] and ident["input_name"] == UNKNOWN_SEQ  # 지금까지와 같은 값
    pair = next(it for it in res["items"] if it["kind"] == "contra_pair")
    assert pair["drugs"] == [UNKNOWN_SEQ, AZI]  # 아는 약만 이름이 된다


def test_typed_name_wins_over_dictionary_name(dd):
    res = _check(dd, [{"name": "타이레놀콜드", "item_seq": SEQ_COLD}, {"item_seq": SEQ_AZI}])
    pair = next(it for it in res["items"] if it["evidence_id"] == PAIR_EID)
    assert pair["drugs"] == ["타이레놀콜드", AZI]


# --------------------------------------------------------------------------- 그래프: 쌍 줄 머리·요약 입력 블록
class CapturingSummary(ScriptedSummary):
    def __init__(self, drafts: list[Any]) -> None:
        super().__init__(drafts)
        self.inputs: list[list[Any]] = []

    def invoke(self, messages: Any, **kwargs: Any) -> Any:
        self.inputs.append(list(messages))
        return super().invoke(messages, **kwargs)


def _block_items(text: str) -> list[dict[str, Any]]:
    bodies = re.findall(re.escape(DATA_OPEN) + r"[^\n]*\n(.*?)\n" + re.escape(DATA_CLOSE), text, flags=re.S)
    return [it for b in bodies for it in json.loads(b)["items"]]


def test_graph_pair_head_and_summary_input_use_names_when_model_passes_item_seq(dd):
    script = [AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"item_seq": SEQ_COLD}, {"item_seq": SEQ_AZI}]}, "c1")]),
              AIMessage("조회를 마쳤다")]
    good = {"sentences": [{"text": "두 약은 병용금기로 올라 있어요.", "evidence_ids": [PAIR_EID], "claim_type": "fact", "citations": []}]}
    sm = CapturingSummary([good])
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    deps = build_deps(dd, ctx, tool_model=ScriptedToolModel(script=script), summary_model=sm, system_prompt="시험용 시스템 프롬프트")
    st = run_question(build_graph(deps), f"{AZI}이랑 {COLD} 같이 먹어도 되나요?")

    # 요약 모델 입력: 도구 결과 블록의 표시명 칸에 코드가 없고 사전 이름이 있다
    assert sm.inputs, "요약 호출이 없었다"
    human = next(m for m in sm.inputs[-1] if isinstance(m, HumanMessage))
    items = _block_items(str(human.content))
    assert items, "요약 입력에 도구 결과 블록이 없다"
    shown = _shown(items)
    assert SEQ_COLD not in shown and SEQ_AZI not in shown, shown
    assert {COLD, AZI} <= set(shown)

    # 쌍 줄 머리(API 응답 변환을 거치기 전, finalize 출력)
    pairs = [e for e in st["answer"]["entries"] if e.get("evidence_id") == PAIR_EID]
    assert pairs, st["answer"]["entries"]
    for e in pairs:
        assert SEQ_COLD not in e["drug"] and SEQ_AZI not in e["drug"], e["drug"]
        assert COLD in e["drug"] and AZI in e["drug"]
