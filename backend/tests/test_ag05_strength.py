"""AG-05 후속: 약 이름·함량 분리와 ROUTER_NOTE 엔티티 블록 시험.

합성 소사전(가상의 제품 이름)과 합성 문장만 쓴다(평가 세트·개발셋·시험셋 문장 아님). LLM·네트워크 호출 없음.
사전 조회 규칙·점수 기준(`TYPO_SCORE_MAX`·`NOT_FOUND_SCORE_MAX`)은 바꾸지 않고, Router가 조회 문자열만 고르는지 본다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_drug_dict import build_dictionary  # noqa: E402

from app.agent import router as R  # noqa: E402
from app.agent.router import (  # noqa: E402
    NOTE_ENTITY_KEYS,
    Mention,
    extract_mention_details,
    extract_mentions,
    lookup_mention,
    note_entities,
    route_input,
    split_strength,
)
from app.tools.drug_dict import MATCH_BM25, DrugDict  # noqa: E402


def _p(seq: str, name: str, ingr: str) -> dict:
    return {"item_seq": seq, "item_name": name, "entp_name": "가상사", "spclty_pblc": "전문의약품", "item_ingr_name": ingr, "edi_code": "",
            "cancel_name": "정상"}


SNAPS = {
    "prmsn": [
        _p("101", "나래주2.5밀리그램/0.5밀리리터", "Zeta"),
        _p("102", "나래주5밀리그램/0.5밀리리터", "Zeta"),
        _p("111", "다솜연질캡슐 350mg", "Eta"),
        _p("112", "다솜연질캡슐 500mg", "Eta"),
        _p("121", "라온서방정 10/5mg", "Theta"),
        _p("122", "라온서방정 10/10mg", "Theta"),
        _p("131", "마루정500밀리그램", "Iota"),
        _p("132", "마루정250밀리그램", "Iota"),
        _p("141", "바다정에이500mg", "Kappa"),
        _p("142", "바다정비250mg", "Kappa"),
        _p("151", "가온정", "Lambda"),
        _p("161", "사랑주50mg/mL", "Mu"),
        _p("162", "사랑주100mg/mL", "Mu"),
    ],
    "eyak": [],
    "detail": [],
    "dur_ingr": [],
    "ingr_codes": {},
}


@pytest.fixture(scope="module")
def dd() -> DrugDict:
    return DrugDict(build_dictionary([], [], SNAPS, {"x": "y"})[0])


# --------------------------------------------------------------------------- 함량 조각 분리(문자열 정리)

class TestExtract:
    @pytest.mark.parametrize("q,token,tail", [
        ("나래주2.5밀리그램/0.5밀리리터 맞아도 되나요", "나래주2.5밀리그램", "/0.5밀리리터"),
        ("다솜연질캡슐 350mg 먹어도 돼요", "다솜연질캡슐", "350mg"),
        ("다솜연질캡슐 350 mg 먹어도 돼요", "다솜연질캡슐", "350mg"),
        ("다솜연질캡슐 350 밀리그램은 어떤 약이에요", "다솜연질캡슐", "350밀리그램"),
        ("라온서방정 10/5mg 같이 먹어도 되나요", "라온서방정", "10/5mg"),
        ("사랑주50mg/mL 맞아도 돼요", "사랑주50mg", "/mL"),
    ])
    def test_detached_strength_is_attached_to_name(self, dd, q, token, tail):
        ms = extract_mention_details(q, dd)
        assert ms[0] == Mention(token, tail), ms
        assert extract_mentions(q, dd)[0] == token          # 함량 조각은 따로 후보가 되지 않는다

    @pytest.mark.parametrize("q", ["마루정, 500mg 먹어도 되나요", "마루정 2알 먹었어요", "마루정 하루 500mg 먹어요"])
    def test_strength_not_attached_across_comma_count_or_words(self, dd, q):
        ms = extract_mention_details(q, dd)
        assert ms[0].token == "마루정" and ms[0].tail is None, ms

    def test_slash_between_products_still_splits(self, dd):
        ms = extract_mention_details("마루정500mg/가온정 같이 먹어도 되나요", dd)
        assert [m.token for m in ms] == ["마루정500mg", "가온정"] and ms[0].tail is None and ms[1].tail is None

    def test_strength_fragment_is_never_its_own_mention(self, dd):
        assert extract_mentions("라온서방정 10/5mg 이랑 마루정 250 mg", dd) == ["라온서방정", "마루정"]

    @pytest.mark.parametrize("tok,expected", [
        ("마루정500mg", ("마루정", "500mg")), ("나래주2.5밀리그램", ("나래주", "2.5밀리그램")), ("라온서방정10/5mg", ("라온서방정", "10/5mg")),
        ("마루정500mg이랑", ("마루정", "500mg")), ("가온정", ("가온정", None)), ("마루정500", ("마루정500", None)), ("정5mg", ("정5mg", None)),
    ])
    def test_split_strength(self, tok, expected):
        assert split_strength(tok) == expected


# --------------------------------------------------------------------------- 사전 조회 후보 품질

class TestLookup:
    @pytest.mark.parametrize("q,seq,raw", [
        ("나래주2.5밀리그램/0.5밀리리터 맞아도 되나요", "101", "나래주2.5밀리그램/0.5밀리리터"),
        ("나래주5밀리그램/0.5밀리리터 맞아도 되나요", "102", "나래주5밀리그램/0.5밀리리터"),
        ("다솜연질캡슐 350mg 먹어도 돼요", "111", "다솜연질캡슐350mg"),
        ("다솜연질캡슐 500 mg 먹어도 돼요", "112", "다솜연질캡슐500mg"),
        ("라온서방정 10/5mg 같이 먹어도 되나요", "121", "라온서방정10/5mg"),
        ("라온서방정 10/10mg 같이 먹어도 되나요", "122", "라온서방정10/10mg"),
        ("사랑주50mg/mL 맞아도 돼요", "161", "사랑주50mg/mL"),
    ])
    def test_name_plus_strength_resolves_to_one_product(self, dd, q, seq, raw):
        r = route_input(q, dd)
        e = r.entities[0]
        assert e.status == R.ST_RESOLVED and e.item_seq == seq, e
        assert e.raw == raw and e.strength                        # 원문 `/` 표기 유지(측정 스크립트의 이름 대조와 같은 모양)
        assert r.branch_label == R.BRANCH_NORMAL and not r.ambiguous

    def test_without_strength_stays_ambiguous(self, dd):
        """함량이 없으면 지금처럼 되묻는다(자동 확정 없음, AG-05-01 A)."""
        e = route_input("다솜연질캡슐 먹어도 돼요", dd).entities[0]
        assert e.status == R.ST_AMBIGUOUS and e.n_candidates == 2 and e.strength is None

    def test_unknown_strength_falls_back_to_name_and_keeps_clarify(self, dd):
        """사전에 없는 함량이 붙으면 이름 접두 일치로 되묻는다(BM25 오탈자 의심으로 보내지 않는다)."""
        e = route_input("다솜연질캡슐700mg 먹어도 돼요", dd).entities[0]
        assert e.status == R.ST_AMBIGUOUS and not e.resolved and e.n_candidates == 2 and e.strength == "700mg"
        assert e.match_type != MATCH_BM25

    @pytest.mark.parametrize("strength,first_seq", [("500mg", "141"), ("250mg", "142")])
    def test_candidates_with_strength_come_first(self, dd, strength, first_seq):
        """이름만 맞고 함량이 든 이름이 따로 없을 때: 후보 순서만 함량 일치 쪽을 앞에 둔다(상태·후보 수 그대로)."""
        e = route_input(f"바다정 {strength} 먹어도 돼요", dd).entities[0]
        assert e.status == R.ST_AMBIGUOUS and e.n_candidates == 2
        assert e.options[0].item_seq == first_seq
        clarify = route_input(f"바다정 {strength} 먹어도 돼요", dd).clarify
        assert clarify is not None and clarify.options[0].item_seq == first_seq

    def test_exact_token_is_unchanged(self, dd):
        """토큰이 그대로 정확·정규화 일치하면 지금까지와 같은 결과다."""
        used, res, strength = lookup_mention(dd, Mention("마루정500밀리그램"))
        assert used == "마루정500밀리그램" and res.resolved and strength == "500밀리그램"
        assert route_input("마루정500mg 먹어도 되나요", dd).entities[0].item_seq == "131"

    def test_unknown_name_with_strength_does_not_become_typo(self, dd):
        """없는 이름 + 함량: 함량을 뗀 이름이 BM25로만 걸리면 쓰지 않는다(없는 약이 오탈자처럼 보이지 않게)."""
        with_s = route_input("하늘별정500mg 먹어도 돼요", dd).entities
        assert with_s and with_s[0].raw == "하늘별정500mg"
        used, res, _ = lookup_mention(dd, Mention("하늘별정500mg"))
        direct = dd.lookup_name("하늘별정500mg", top_k=R.MAX_CLARIFY_OPTIONS)
        assert (res.match_type, res.empty) == (direct.match_type, direct.empty)

    def test_strength_never_used_as_dose_and_thresholds_unchanged(self):
        assert R.TYPO_SCORE_MAX == 0.6 and R.NOT_FOUND_SCORE_MAX == 0.0


# --------------------------------------------------------------------------- ROUTER_NOTE 엔티티 블록

class TestRouterNote:
    def test_note_entities_fixed_keys_and_order(self, dd):
        r = route_input("라온서방정 10/5mg 이랑 다솜연질캡슐 같이 먹어도 되나요", dd)
        note = note_entities(r.entities)
        assert [tuple(n) for n in note] == [NOTE_ENTITY_KEYS] * len(note)
        assert [n["raw"] for n in note] == ["라온서방정10/5mg", "다솜연질캡슐"]
        assert note[0]["strength"] == "10/5mg" and note[0]["status"] == R.ST_RESOLVED and note[0]["item_seq"] == "121"
        assert note[1]["item_seq"] is None                       # 모호하면 하나로 고르지 않는다

    def test_note_entities_from_state_dicts_and_dedup(self, dd):
        st = route_input("마루정500mg 먹어도 되나요", dd).state_update()
        dup = st["entities"] + st["entities"]
        assert note_entities(dup) == note_entities(route_input("마루정500mg 먹어도 되나요", dd).entities)
        assert len(note_entities(dup)) == 1
        assert note_entities(None) == [] and note_entities([]) == []

    def test_graph_router_note_carries_entities(self, dd):
        from app.agent.graph.nodes import _router_note
        st = route_input("라온서방정 10/5mg 먹어도 되나요", dd).state_update()
        block = _router_note(st)
        assert block.startswith("<<<ROUTER_NOTE\n") and block.endswith("\nROUTER_NOTE>>>")
        body = json.loads(block.split("\n")[1])
        assert body["drug_candidates"] == note_entities(st["entities"])
        assert body["drug_candidates"][0]["strength"] == "10/5mg"
