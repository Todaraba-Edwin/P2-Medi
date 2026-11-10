"""AG-06 통합 시험 재료: AG-02 합성 소사전·SQLite로 실제 도구(`registry.invoke`)를 불러 `items[]`를 만든다. 외부 호출 없음.

시험 문장은 모두 합성이다(평가 세트·페르소나 질문 아님).
"""

from __future__ import annotations

from typing import Any

from ag02_synth import FakeLabels, ctx, doc

from app.agent.answer_schema import Citation, Sentence
from app.agent.tools.registry import invoke

LABEL_SEQ = "201908146"
DOSE_TEXT = "성인 1회 1~2정씩 1일 3회 복용한다."


def tool_items(name: str, args: dict[str, Any], **ctx_kw: Any) -> list[dict[str, Any]]:
    out = invoke(name, args, ctx(**ctx_kw))
    assert "error" not in out and out["contract_violations"] == [], out
    return out["items"]


def check_items_pair(pregnancy: bool = True, age: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """이부정+와파린정(병용·임부 FOUND), 미등록정(코드 없음), 에이캡슐(참고 전용)을 한 번에 조회한다."""
    args: dict[str, Any] = {"drugs": [{"name": "이부정"}, {"name": "와파린정"}, {"name": "미등록정"}, {"name": "에이캡슐"}], "pregnancy": pregnancy}
    if age:
        args["age"] = age
    return tool_items("check_contraindications", args)


def ambiguous_items() -> list[dict[str, Any]]:
    return tool_items("check_contraindications", {"drugs": [{"name": "감기정"}, {"name": "와파린정"}]})


def identify_items(name: str) -> list[dict[str, Any]]:
    return tool_items("identify_drug", {"name": name})


def label_provider(section_xml: str | None = None) -> FakeLabels:
    return FakeLabels(detail_map={LABEL_SEQ: {"item": {"UD_DOC_DATA": section_xml or doc("용법용량", DOSE_TEXT)}, "collected_at": "2026-11-10T07:00:00Z", "source": "snapshot"}})


def label_items(section: str = "용법용량", lab: FakeLabels | None = None, seq: str = LABEL_SEQ) -> list[dict[str, Any]]:
    return tool_items("get_label_section", {"item_seq": seq, "section": section}, label_provider=lab or label_provider())


def easy_label_items() -> list[dict[str, Any]]:
    lab = FakeLabels(eyak_map={"000000001": {"item": {"efcy": "열을 내려요\n"}, "collected_at": "2026-11-10T00:00:00Z", "source": "snapshot"}})
    return label_items("효능", lab, seq="000000001")


def S(text: str, ids: tuple[str, ...] | list[str] = (), ct: str = "fact", cites: tuple[Citation, ...] | list[Citation] = ()) -> Sentence:
    return Sentence(text=text, evidence_ids=list(ids), claim_type=ct, citations=list(cites))  # type: ignore[arg-type]


def by_kind(items: list[dict[str, Any]], kind: str, status: str | None = None) -> list[dict[str, Any]]:
    return [i for i in items if i["kind"] == kind and (status is None or i["status"] == status)]
