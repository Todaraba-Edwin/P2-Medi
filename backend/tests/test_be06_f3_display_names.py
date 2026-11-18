"""BE-06 이슈 F3(2026-11-18, `fe01-live.md` §4) 재현·회귀 시험: 오탈자 보정·되묻기로 확정된 약이 쌍 줄 머리·`drugs`에
품목기준코드(`202106092 · 이부프로펜`)로 나오던 문제. LLM·공공 API·원격 DB 호출 0.

원인: 모델이 확정된 약을 `{"item_seq": ...}`만으로 넘기면 `check_contraindications._resolve`가 표시명 자리(`label`)에
품목기준코드를 둔다(`label = arg.name or arg.item_seq`). 고침(응답 변환, `app.api.schemas.display_names`): 이름 칸의 값이
**정확히 품목기준코드**이고 같은 응답(식별 근거·제품 줄) 또는 같은 요청의 router 확정 엔티티에 그 코드의 사전 확정 이름이 있으면
그 이름으로 바꾼다. 판정·근거 ID·`item_seq` 칸은 그대로다.
근거 항목·사전은 합성이다(평가 세트·시험셋 문항 아님).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import SEQ_AZI, SEQ_COLD, FakeDur, golden_conn, golden_dict  # noqa: E402

from app.agent.answer_schema import Sentence  # noqa: E402
from app.agent.finalize import finalize  # noqa: E402
from app.agent.graph.fakes import ScriptedSummary, ScriptedToolModel, tool_call  # noqa: E402
from app.agent.graph.wiring import build_deps, build_tool_context  # noqa: E402
from app.api import chat as chat_api  # noqa: E402
from app.api.runner import GraphRunner  # noqa: E402
from app.api.schemas import ChatResponse, display_names, to_chat_response  # noqa: E402

KDB = "한국의약품안전관리원"
SEQ = "202106092"  # 합성 품목기준코드(9자리)
NAME = "타이레놀정500밀리그람"  # 사전 확정 이름(보정 결과)
OTHER = "이부프로펜"
EID = f"contra_pair:{SEQ}:ibu"


def pair_item(drugs: list[str], keys: list[str], eid: str = EID) -> dict[str, Any]:
    return {"kind": "contra_pair", "status": "FOUND", "subject": keys, "evidence_id": eid, "source": KDB, "as_of": "2026-07-31",
            "flags": [], "dataset_key": "contra_pair", "source_kind": "FILE", "drugs": drugs, "drug_keys": keys,
            "matches": [{"row_key": "r0", "row_evidence_id": f"{eid}#0", "reason": "합성 사유 문구", "notice_no": "20250046",
                         "notice_date": "2025-07-14"}]}


def identify_item(seq: str, name: str) -> dict[str, Any]:
    return {"kind": "identify", "status": "FOUND", "subject": [seq], "evidence_id": f"identify:{seq}", "item_seq": seq, "name": name,
            "matched_by": "product", "source": "합성 사전", "as_of": None, "flags": [], "dataset_key": "identify", "source_kind": "FILE",
            "ingredients": [{"display": "아세트아미노펜", "name_ko": "아세트아미노펜"}]}


def resolved(seq: str, raw: str) -> dict[str, Any]:
    return {"raw": raw, "status": "RESOLVED", "item_seq": seq, "corrected_from": "타이래놀정500밀리그람"}


SENTS = [Sentence(text="두 약은 함께 먹으면 안 되는 조합으로 올라 있어요.", evidence_ids=[EID], claim_type="fact")]


def _resp(items: list[dict[str, Any]], entities: list[dict[str, Any]] | None = None) -> ChatResponse:
    return to_chat_response(finalize(items, model_summary=SENTS[0].text, sentences=SENTS), end_reason="NORMAL", entities=entities)


def _pair(r: ChatResponse, eid: str = EID) -> Any:
    return next(f for f in r.findings if f.target == "pair" and f.evidence_id == eid)


# --------------------------------------------------------------------------- 재현(고치기 전 모양)과 고친 뒤
def test_without_name_source_code_stays_as_before():
    # 이름 원천이 없으면 지어내지 않는다: 지금까지와 같은 출력(재현 모양 그대로)
    f = _pair(_resp([pair_item([SEQ, OTHER], [SEQ, "ibu"])]))
    assert f.drug == f"{SEQ} · {OTHER}" and f.drugs == [SEQ, OTHER]


def test_router_resolved_entity_names_pair_head_and_drugs():
    r = _resp([pair_item([SEQ, OTHER], [SEQ, "ibu"])], entities=[resolved(SEQ, NAME)])
    f = _pair(r)
    assert f.drug == f"{NAME} · {OTHER}" and f.drugs == [NAME, OTHER]
    d = next(x for x in r.detail if x.evidence_id == EID)
    assert d.drugs == [NAME, OTHER]
    assert f.evidence_id == EID  # 근거 ID(약 키)는 바꾸지 않는다
    assert SEQ not in r.model_dump_json(include={"findings"}).replace(EID, "")  # 줄 칸 어디에도 코드가 이름으로 남지 않음(근거 ID 제외)


def test_identify_evidence_name_wins_over_entity_raw():
    r = _resp([identify_item(SEQ, NAME), pair_item([SEQ, OTHER], [SEQ, "ibu"])], entities=[resolved(SEQ, "다른표기")])
    assert _pair(r).drugs == [NAME, OTHER]
    ident = next(x for x in r.detail if x.evidence_id == f"identify:{SEQ}")
    assert ident.item_seq == SEQ  # `item_seq` 칸은 코드 그대로


def test_product_row_head_uses_dictionary_name():
    r = _resp([identify_item(SEQ, NAME), pair_item([SEQ, OTHER], [SEQ, "ibu"])])
    product = [f for f in r.findings if f.target == "product"]
    assert any(f.drug == NAME and f.drugs == [NAME] for f in product), [(f.drug, f.drugs) for f in product]
    assert all(f.drug != SEQ for f in product)


def test_typed_names_are_never_rewritten():
    # 사용자가 이름으로 적어 표시명이 이미 이름이면 그대로(코드 꼴인 값만 바꾼다)
    f = _pair(_resp([pair_item(["타이레놀", OTHER], [SEQ, "ibu"])], entities=[resolved(SEQ, NAME)]))
    assert f.drugs == ["타이레놀", OTHER] and f.drug == f"타이레놀 · {OTHER}"


def test_display_names_rejects_code_like_or_blank_names():
    resp = {"detail": [{"kind": "identify", "status": "FOUND", "item_seq": SEQ, "name": "  "}],
            "product_rows": [{"key": SEQ, "name": "123456789"}, {"key": "not-a-seq", "name": "x"}]}
    ents = [{"status": "AMBIGUOUS", "item_seq": SEQ, "raw": "모호"}, {"status": "RESOLVED", "item_seq": None, "raw": "코드없음"}]
    assert display_names(resp, ents) == {}
    assert display_names(resp, [resolved(SEQ, NAME)]) == {SEQ: NAME}


# --------------------------------------------------------------------------- `/chat` 끝까지(모델이 품목기준코드만 넘김)
COLD, AZI = "타이레놀콜드-에스정", "이지렉트정1.0밀리그램"
PAIR_EID = "contra_pair:254000ATB:625201ATB"


def test_chat_stream_pair_head_uses_name_when_model_passes_item_seq():
    script = [AIMessage("", tool_calls=[tool_call("check_contraindications", {"drugs": [{"item_seq": SEQ_COLD}, {"item_seq": SEQ_AZI}]}, "c1")]),
              AIMessage("조회를 마쳤다")]
    good = {"sentences": [{"text": "두 약은 병용금기로 올라 있어요.", "evidence_ids": [PAIR_EID], "claim_type": "fact", "citations": []}]}
    dd = golden_dict()
    ctx = build_tool_context(dd, mode="service", dur_client=FakeDur(), conn_factory=golden_conn)
    runner = GraphRunner.from_deps(build_deps(dd, ctx, tool_model=ScriptedToolModel(script=script), summary_model=ScriptedSummary([good]),
                                              system_prompt="시험용 시스템 프롬프트"))
    app = FastAPI()
    chat_api.register(app)
    chat_api.set_runner(app, runner, metrics=None)
    r = TestClient(app).post("/chat", json={"question": f"{AZI}이랑 {COLD} 같이 먹어도 되나요?", "context": {}})
    assert r.status_code == 200
    import json  # noqa: PLC0415

    events = [json.loads(x) for x in r.text.splitlines() if x.strip()]
    answer = next(e for e in events if e["type"] == "answer")["response"]
    pairs = [f for f in answer["findings"] if f["target"] == "pair"]
    assert pairs, answer["findings"]
    for f in pairs:
        assert SEQ_COLD not in f["drugs"] and SEQ_AZI not in f["drugs"], f["drugs"]
        assert SEQ_COLD not in f["drug"] and SEQ_AZI not in f["drug"], f["drug"]
    assert {COLD, AZI} <= {n for f in pairs for n in f["drugs"]}
