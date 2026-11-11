"""AG-05 Router 규칙 기반 부분 시험. 합성 소사전(항상)과 실제 사전(`data/mock/dict/drug_dict.json`이 있을 때만)으로 확인한다.

시험 문장은 모두 합성이다(평가 세트·시험셋·페르소나 질문 아님). LLM·네트워크 호출 없음.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_drug_dict import build_dictionary  # noqa: E402

from app.agent import router as R  # noqa: E402
from app.agent.router import (  # noqa: E402
    MAX_CLARIFY_OPTIONS,
    MAX_DRUGS,
    ROUTER_WRITABLE_KEYS,
    extract_mentions,
    route_input,
)
from app.tools.drug_dict import DEFAULT_DICT_PATH, DrugDict  # noqa: E402

KIDS = [
    {"product_code": "111111111", "name": "타이레놀정500밀리그람(아세트아미노펜)_(500mg/1정)", "ingr_code": "101301ATB", "ingr_name": "acetaminophen", "entp": "A사"},
    {"product_code": "444444444", "name": "부루펜정200밀리그램(이부프로펜)_(200mg/1정)", "ingr_code": "102001ATB", "ingr_name": "ibuprofen", "entp": "H사"},
    {"product_code": "555555555", "name": "아스피린프로텍트정100밀리그램(아스피린)_(100mg/1정)", "ingr_code": "103001ATB", "ingr_name": "aspirin", "entp": "I사"},
    {"product_code": "666666666", "name": "와파린정(와파린나트륨)_(2mg/1정)", "ingr_code": "104001ATB", "ingr_name": "warfarin sodium", "entp": "J사"},
    {"product_code": "777777777", "name": "게보린정(이소프로필안티피린)_(1정)", "ingr_code": "105001ATB", "ingr_name": "isopropylantipyrine", "entp": "K사"},
    {"product_code": "888888888", "name": "슈도정(슈도에페드린염산염)_(60mg/1정)", "ingr_code": "100101ATB", "ingr_name": "pseudoephedrine hydrochloride", "entp": "C사"},
]


def _p(seq: str, name: str, entp: str, ingr: str, edi: str = "", kind: str = "일반의약품") -> dict:
    return {"item_seq": seq, "item_name": name, "entp_name": entp, "spclty_pblc": kind, "item_ingr_name": ingr, "edi_code": edi, "cancel_name": "정상"}


SNAPS = {
    "prmsn": [
        _p("1", "타이레놀정500밀리그람", "A사", "Acetaminophen", "111111111"),
        _p("2", "타이레놀8시간이알서방정", "A사", "Acetaminophen"),
        _p("3", "동명약", "D사", "Zzz", kind="전문의약품"),
        _p("4", "동명약", "E사", "Yyy", kind="전문의약품"),
        _p("8", "부루펜정200밀리그램", "H사", "Ibuprofen", "444444444"),
        _p("9", "아스피린프로텍트정100밀리그램", "I사", "Aspirin", "555555555"),
        _p("10", "와파린정", "J사", "Warfarin Sodium", "666666666"),
        _p("11", "게보린정", "K사", "Isopropylantipyrine", "777777777"),
        _p("12", "슈도정", "C사", "Pseudoephedrine HCl", "333333333"),
        _p("13", "이부프로펜", "L사", "Ibuprofen"),  # 제품명이 성분명과 같은 제품(동명)
    ],
    "eyak": [],
    "detail": [],
    "dur_ingr": [
        {"INGR_CODE": "D000147", "INGR_ENG_NAME": "Acetaminophen", "INGR_NAME": "아세트아미노펜", "MIX_TYPE": "단일"},
        {"INGR_CODE": "D000200", "INGR_ENG_NAME": "Ibuprofen", "INGR_NAME": "이부프로펜", "MIX_TYPE": "단일"},
        {"INGR_CODE": "D000300", "INGR_ENG_NAME": "Aspirin", "INGR_NAME": "아스피린", "MIX_TYPE": "단일"},
        {"INGR_CODE": "D000400", "INGR_ENG_NAME": "Warfarin Sodium", "INGR_NAME": "와파린나트륨", "MIX_TYPE": "단일"},
    ],
    "ingr_codes": {},
}


@pytest.fixture(scope="module")
def dd() -> DrugDict:
    return DrugDict(build_dictionary(KIDS, [], SNAPS, {"x": "y"})[0])


def _names(res: R.RouterResult) -> list[str]:
    return res.drug_mentions


# --------------------------------------------------------------------------- 단일 약 (5)

class TestSingle:
    @pytest.mark.parametrize("q", ["게보린정 먹어도 되나요?", "게보린정을 먹어도 돼요", "게보린정은 어떤 약인가요", "게보린정 효능이 뭐예요", "게보린정이 집에 있는데 괜찮을까요"])
    def test_single_resolved(self, dd, q):
        r = route_input(q, dd)
        assert len(r.entities) == 1, r.drug_mentions
        e = r.entities[0]
        assert e.status == "RESOLVED" and e.resolved and e.item_seq == "11"
        assert r.branch_label == R.BRANCH_NORMAL and not r.ambiguous and r.clarify is None
        assert e.code_status == "linked"


# --------------------------------------------------------------------------- 두 약 병용 (5)

class TestPair:
    @pytest.mark.parametrize("q", [
        "게보린정이랑 와파린정 같이 먹어도 되나요?",
        "게보린정하고 와파린정을 함께 먹어도 돼요?",
        "게보린정, 와파린정 병용해도 되는지 알려줘",
        "게보린정과 와파린정 동시에 복용 가능한가요",
        "게보린정 / 와파린정 같이 먹으면 안 되나요",
    ])
    def test_two_drugs(self, dd, q):
        r = route_input(q, dd)
        assert sorted(e.item_seq for e in r.entities) == ["10", "11"], r.drug_mentions
        assert r.n_pairs == 1 and R.INTENT_CONTRA in r.intent
        assert r.branch_label == R.BRANCH_NORMAL


# --------------------------------------------------------------------------- 세 약 이상 (5)

class TestMany:
    def test_three_drugs_three_pairs(self, dd):
        r = route_input("게보린정, 와파린정, 부루펜정200밀리그램 다 같이 먹어도 되나요?", dd)
        assert len(r.entities) == 3 and r.n_pairs == 3

    def test_four_drugs(self, dd):
        r = route_input("게보린정 와파린정 부루펜정200밀리그램 슈도정 같이 먹어도 돼요", dd)
        assert len(r.entities) == 4 and r.n_pairs == 6

    def test_cap_six_means_fifteen_pairs(self, dd):
        names = ["게보린정", "와파린정", "부루펜정200밀리그램", "슈도정", "아스피린프로텍트정100밀리그램", "타이레놀정500밀리그람"]
        r = route_input(", ".join(names) + " 같이 먹어도 되나요", dd)
        assert len(r.entities) == 6 and r.n_pairs == 15 and not r.truncated

    def test_over_cap_is_truncated_not_silent(self, dd):
        names = ["게보린정", "와파린정", "부루펜정200밀리그램", "슈도정", "아스피린프로텍트정100밀리그램", "타이레놀정500밀리그람", "동명약"]
        r = route_input(", ".join(names) + " 같이 먹어도 되나요", dd)
        assert len(r.entities) <= MAX_DRUGS and r.truncated

    def test_duplicates_removed(self, dd):
        r = route_input("게보린정이랑 게보린정 같이 먹어도 되나요", dd)
        assert len(r.entities) == 1 and r.n_pairs == 0

    def test_drug_mentions_match_entities(self, dd):
        r = route_input("게보린정이랑 와파린정 같이", dd)
        assert r.drug_mentions == [e.raw for e in r.entities]


# --------------------------------------------------------------------------- 오탈자 (5)

class TestTypo:
    @pytest.mark.parametrize("q", ["게보린징 먹어도 되나요", "와파린쟁 같이 먹어도 돼요", "부루팬정200밀리그램 괜찮나요", "아스피린프로택트정 먹어도 되나요", "타이레놀쩡500밀리그람 먹어도 돼요"])
    def test_typo_never_auto_resolved(self, dd, q):
        r = route_input(q, dd)
        # 오탈자는 자동 확정하지 않는다. 후보가 있으면 되묻고, 사전이 못 찾으면 근거 없음이다.
        for e in r.entities:
            assert not e.resolved and e.item_seq is None
        assert r.branch_label in (R.BRANCH_TYPO, R.BRANCH_AMBIGUOUS, R.BRANCH_NO_EVIDENCE)
        if r.ambiguous:
            assert r.clarify is not None and 1 <= len(r.clarify.options) <= MAX_CLARIFY_OPTIONS

    def test_typo_threshold_label(self, dd):
        r = route_input("게보린징", dd)
        e = r.entities[0]
        if e.match_type == "bm25":
            top = e.options[0].score
            assert (e.status == R.ST_TYPO) == (top <= R.TYPO_SCORE_MAX)


# --------------------------------------------------------------------------- 접두 브랜드 되묻기 (5)

class TestPrefixClarify:
    @pytest.mark.parametrize("q", ["타이레놀 먹어도 되나요", "타이레놀이랑 게보린정 같이 먹어도 되나요", "타이레놀을 먹어도 돼요", "타이레놀은 어떤 약이에요", "게보린정하고 타이레놀 같이 복용 가능한가요"])
    def test_brand_prefix_asks(self, dd, q):
        r = route_input(q, dd)
        t = next(e for e in r.entities if e.raw.startswith("타이레놀"))
        assert t.status == "AMBIGUOUS" and not t.resolved and t.item_seq is None
        assert t.needs_clarification and t.n_candidates >= 2
        assert r.ambiguous and r.branch_label == R.BRANCH_AMBIGUOUS
        assert r.clarify is not None and r.clarify.target_raw == t.raw
        assert {o.item_seq for o in r.clarify.options} >= {"1", "2"}
        assert len(r.clarify.options) <= MAX_CLARIFY_OPTIONS

    def test_clarify_template_no_verdict(self, dd):
        r = route_input("타이레놀 먹어도 되나요", dd)
        q = r.clarify.question
        assert q.count("?") == 0 or q.count("?") == 1
        for bad in ("안전", "괜찮", "먹어도 됩", "금기 없", "문제 없", "드셔도"):
            assert bad not in q
        assert re.search(r"[\d]+\s*(mg|밀리|정|알)", q) is None  # 용량 숫자 없음

    def test_only_one_question_for_multiple_ambiguous(self, dd):
        r = route_input("타이레놀이랑 동명약 같이 먹어도 되나요", dd)
        assert r.clarify is not None and len(r.clarify.pending_raws) == 1
        assert r.clarify.question.count("?") <= 1


# --------------------------------------------------------------------------- 성분명만 (5)

class TestIngredientOnly:
    @pytest.mark.parametrize("q", ["아세트아미노펜 먹어도 되나요", "아세트아미노펜이랑 아스피린 같이 먹어도 되나요", "acetaminophen 같이 복용 가능한가요", "아스피린 임신 중에 먹어도 돼요", "아스피린 하고 아세트아미노펜 같이 먹어도 돼요"])
    def test_ingredient_unit_flag_and_not_blocked(self, dd, q):
        r = route_input(q, dd)
        ing = [e for e in r.entities if e.matched_by == "ingredient_name"]
        assert ing, r.entities
        for e in ing:
            assert R.FLAG_NO_PRODUCT_INFO in e.flags  # H17 표시
            assert e.status == "RESOLVED" and e.item_seq is None  # 제품 식별 아님
        assert not r.ambiguous  # 막지 않는다(되묻기로 돌리지 않음)


# --------------------------------------------------------------------------- 사전에 없는 약 (5)

class TestNotFound:
    @pytest.mark.parametrize("q", ["쿵쿵따리정 먹어도 되나요", "zzzqqq 같이 먹어도 되나요", "게보린정이랑 쿵쿵따리정 같이 먹어도 되나요", "헤르몬샤정 괜찮나요", "ㅋㅋㅋㅋ"])
    def test_not_found_is_not_safe(self, dd, q):
        r = route_input(q, dd)
        nf = [e for e in r.entities if e.status == "NOT_FOUND"]
        if "ㅋㅋ" in q:
            return
        assert nf, r.entities
        for e in nf:
            assert e.branch == R.BRANCH_NO_EVIDENCE and e.n_candidates == 0 and not e.resolved
        assert not r.ambiguous
        assert r.branch_label == R.BRANCH_NO_EVIDENCE


# --------------------------------------------------------------------------- 제품·성분 동명 (5)

class TestSameName:
    def test_product_wins_and_noted(self, dd):
        r = route_input("이부프로펜 먹어도 되나요", dd)
        e = r.entities[0]
        # 제품 일치가 우선하고, 성분명이기도 함을 표시한다. 하나로 정해졌으면 제품, 아니면 되묻기. 어느 쪽이든 임의 선택은 없다.
        assert e.matched_by == "product_name"
        assert R.FLAG_SAME_NAME_INGREDIENT in e.flags

    def test_same_product_name_two_makers_asks(self, dd):
        r = route_input("동명약 먹어도 되나요", dd)
        e = r.entities[0]
        assert e.status == "AMBIGUOUS" and e.item_seq is None and e.n_candidates == 2
        assert {o.entp_name for o in e.options} == {"D사", "E사"}

    def test_never_picks_one_of_many(self, dd):
        r = route_input("동명약이랑 게보린정 같이 먹어도 되나요", dd)
        for e in r.entities:
            if e.n_candidates > 1:
                assert not e.resolved and e.item_seq is None

    def test_options_cap(self, dd):
        r = route_input("타이레놀 먹어도 되나요", dd)
        assert len(r.entities[0].options) <= MAX_CLARIFY_OPTIONS

    def test_ingredient_name_alone_with_product_same_name_flagged(self, dd):
        r = route_input("이부프로펜이랑 와파린정 같이 먹어도 되나요", dd)
        assert any(R.FLAG_SAME_NAME_INGREDIENT in e.flags for e in r.entities)


# --------------------------------------------------------------------------- 섞인 입력 (5)

class TestMixed:
    @pytest.mark.parametrize("q", ["게보린정이랑아스피린프로텍트정100밀리그램 같이 먹어도 되나요", "게보린정과아스피린프로텍트정100밀리그램 같이 먹어도 돼요", "게보린정하고와파린정 같이 괜찮나요"])
    def test_joined_without_space(self, dd, q):
        r = route_input(q, dd)
        assert len(r.entities) == 2 and all(e.status == "RESOLVED" for e in r.entities)

    def test_warfarin_name_starting_with_connector_syllable_survives(self, dd):
        r = route_input("게보린정과와파린정 같이 먹어도 돼요", dd)
        assert sorted(e.item_seq for e in r.entities) == ["10", "11"]

    def test_product_ingredient_ko_en_mixed(self, dd):
        r = route_input("타이레놀정500밀리그람이랑 ibuprofen 같이 먹어도 되나요", dd)
        assert len(r.entities) == 2
        assert r.entities[0].item_seq == "1" and r.entities[1].matched_by in ("ingredient_name", "product_name")

    def test_stopwords_not_drugs(self, dd):
        m = extract_mentions("집에 있는 약인데 같이 먹어도 되나요 임신 중이에요 5살 아이가 먹어도 돼요", dd)
        assert m == []


# --------------------------------------------------------------------------- 프로필·유형·응급 통과

class TestProfileIntent:
    def test_age_and_pregnancy_from_question(self, dd):
        r = route_input("임신 중인데 게보린정 먹어도 되나요", dd)
        assert r.profile.pregnant is True and r.profile.source == "question"
        r = route_input("5살 아이가 게보린정 먹어도 되나요", dd)
        assert r.profile.age_years == 5.0
        r = route_input("18개월 아기가 게보린정 먹어도 되나요", dd)
        assert r.profile.age_years == 1.5

    def test_negated_pregnancy(self, dd):
        assert route_input("임신은 아니고 게보린정 먹어도 돼요", dd).profile.pregnant is False

    def test_profile_passthrough_and_question_precedence(self, dd):
        r = route_input("게보린정 먹어도 되나요", dd, profile={"age_years": 70, "pregnant": None, "source": "profile"})
        assert r.profile.age_years == 70 and r.profile.source == "profile"
        r = route_input("30살인데 게보린정 먹어도 되나요", dd, profile={"age_years": 70})
        assert r.profile.age_years == 30 and r.profile.source == "question"

    def test_open_question_without_drug(self, dd):
        r = route_input("임신 중 피해야 할 진통제가 뭐예요", dd)
        assert R.INTENT_OPEN in r.intent and r.entities == []

    def test_two_intents(self, dd):
        r = route_input("게보린정 효능이랑 병용금기 고시 등급이 뭔지 알려줘", dd)
        assert R.INTENT_DRUG_INFO in r.intent and R.INTENT_DOCUMENT in r.intent

    def test_drug_info_only(self, dd):
        r = route_input("게보린정은 무슨 약이에요", dd)
        assert r.intent == [R.INTENT_DRUG_INFO]

    def test_emergency_passthrough_does_not_change_result(self, dd):
        q = "게보린정이랑 와파린정 같이 먹어도 되나요"
        a = route_input(q, dd)
        b = route_input(q, dd, emergency=True, guardrail_route="정상")
        assert b.emergency is True and b.guardrail_route == "정상"
        for k in ("entities", "intent", "profile", "branch_label", "ambiguous", "drug_mentions", "n_pairs"):
            assert getattr(a, k) == getattr(b, k)

    def test_state_update_keys_restricted(self, dd):
        u = route_input("게보린정 먹어도 되나요", dd, emergency=True).state_update()
        assert set(u) <= ROUTER_WRITABLE_KEYS
        for forbidden in ("emergency", "route", "messages", "evidence", "answer", "guardrail_route"):
            assert forbidden not in u

    def test_pure_no_side_effects(self, dd, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        route_input("30살 임신 중인데 게보린정 먹어도 되나요", dd)
        assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------- 정적 점검

def test_no_emergency_keyword_list_in_router():
    src = Path(R.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    for kw in ("119", "응급", "호흡곤란", "의식", "경련", "아나필락시스", "과다복용", "emergency_keywords", "EMERGENCY_KEYWORDS"):
        # `emergency` 입력 필드 이름과 독스트링 설명은 허용하고, 키워드 값·목록은 금지한다
        for line in code.splitlines():
            if kw in ("emergency_keywords", "EMERGENCY_KEYWORDS"):
                assert kw not in line
            elif kw not in ("응급",) and not line.strip().startswith(('"""', "'''")):
                assert kw not in line or "emergency" in line or line.strip().startswith(("모듈", "-", "하지", "하는"))


def test_router_has_no_llm_or_network_imports():
    src = Path(R.__file__).read_text(encoding="utf-8")
    for bad in ("import openai", "from openai", "anthropic", "import requests", "import httpx", "langchain", "langgraph"):
        assert bad not in src


# --------------------------------------------------------------------------- 실제 사전(있을 때만)

@pytest.fixture(scope="module")
def real_dd():
    if not DEFAULT_DICT_PATH.exists():
        pytest.skip("data/mock/dict/drug_dict.json 없음")
    return DrugDict.load(DEFAULT_DICT_PATH)


class TestRealDict:
    def test_brand_prefix_real(self, real_dd):
        r = route_input("타이레놀 먹어도 되나요", real_dd)
        e = r.entities[0]
        assert not e.resolved and len(e.options) <= MAX_CLARIFY_OPTIONS and r.ambiguous

    def test_ingredient_real_not_blocked(self, real_dd):
        r = route_input("아세트아미노펜이랑 이부프로펜 같이 먹어도 되나요", real_dd)
        assert len(r.entities) == 2
        for e in r.entities:
            assert e.item_seq is None or e.resolved

    def test_two_real_products_pair(self, real_dd):
        r = route_input("게보린정이랑 와파린정 같이 먹어도 되나요", real_dd)
        assert len(r.entities) >= 1
        for e in r.entities:
            if e.n_candidates > 1:
                assert not e.resolved


# --------------------------------------------------------------------------- AG-05-01 일반 규칙 보강(개발셋 문항과 무관한 합성 문장)

class TestGeneralRules051:
    def test_slash_between_digits_kept_but_slash_between_words_splits(self, dd):
        assert extract_mentions("가나다정5/850밀리그램 먹어도 되나요", dd) == ["가나다정5/850밀리그램"]
        assert extract_mentions("게보린정/와파린정 같이", dd) == ["게보린정", "와파린정"]

    @pytest.mark.parametrize("q", ["게보린정 500mg 먹어도 돼요", "게보린정 2알 먹었어요", "게보린정 5밀리그램 괜찮나요", "게보린정 10mL 정도"])
    def test_dose_tokens_are_not_drugs(self, dd, q):
        assert extract_mentions(q, dd) == ["게보린정"]

    @pytest.mark.parametrize("q", ["아버지가 게보린정 계속 드셔도 되나요", "남편이 방금 게보린정 먹었어요", "병원에서 게보린정 처방했어요"])
    def test_kinship_time_place_words_are_not_drugs(self, dd, q):
        assert extract_mentions(q, dd) == ["게보린정"]

    @pytest.mark.parametrize("q", ["게보린정 먹어도 되냐", "게보린정 먹어야 해", "게보린정 괜찮을까", "게보린정 먹자"])
    def test_verb_endings_are_not_drugs(self, dd, q):
        assert extract_mentions(q, dd) == ["게보린정"]

    def test_symptom_noun_is_not_drug_but_dictionary_exact_is_kept(self, dd):
        assert extract_mentions("방광염 때문에 게보린정 먹어도 되나요", dd) == ["게보린정"]
        # 사전에 정확히 있는 이름은 어미·접미 규칙으로 버리지 않는다(와파린정 → 끝이 '정'이라 해당 없음, 동명약은 '약' 규칙 점검)
        assert extract_mentions("동명약 먹어도 되나요", dd) == ["동명약"]


# --------------------------------------------------------------------------- AG-05-02 A: 가상 약(BM25 약한 점수)은 NOT_FOUND, 후보 제시 유지

class TestWeakBm25NotFound:
    """`NOT_FOUND_SCORE_MAX`(Router 임계값) 동작. 값은 monkeypatch로 지정한다(기본 0.0 = 비활성). 시험 이름은 모두 합성이다."""

    def test_default_is_disabled(self, dd):
        assert R.NOT_FOUND_SCORE_MAX == 0.0
        for e in route_input("게보린징", dd).entities:
            assert e.status != R.ST_NOT_FOUND or e.match_type is None

    @pytest.mark.parametrize("q", ["게보린징 먹어도 되나요", "와파린쟁 같이 먹어도 돼요", "부루팬정200밀리그램 괜찮나요", "아스피린프로택트정 먹어도 되나요", "타이레놀쩡500밀리그람 먹어도 돼요"])
    def test_weak_bm25_becomes_not_found_with_candidates_kept(self, dd, q, monkeypatch):
        base = route_input(q, dd)
        bm = [e for e in base.entities if e.match_type == "bm25"]
        if not bm:
            pytest.skip("이 입력은 BM25 일치가 아님")
        monkeypatch.setattr(R, "NOT_FOUND_SCORE_MAX", 1.0)  # 모든 BM25 일치를 NOT_FOUND 쪽으로
        r = route_input(q, dd)
        nf = [e for e in r.entities if e.match_type == "bm25"]
        assert nf and all(e.status == R.ST_NOT_FOUND and e.branch == R.BRANCH_NO_EVIDENCE for e in nf)
        assert all(e.options and R.FLAG_SIMILAR_SHOWN in e.flags and not e.resolved and e.item_seq is None for e in nf)  # 후보 유지, 자동 확정 없음
        assert all(1 <= len(e.options) <= MAX_CLARIFY_OPTIONS for e in nf)
        # 되묻기 문구: 후보를 그대로 보여 주고 "찾지 못했다"를 먼저 말한다. 안전·가부 단정은 없다.
        assert r.ambiguous and r.clarify is not None and r.clarify.options and "찾지 못했어요" in r.clarify.question
        assert r.branch_label == R.BRANCH_NO_EVIDENCE
        for bad in ("안전", "괜찮", "먹어도 됩니다", "문제없"):
            assert bad not in r.clarify.question

    def test_high_score_typo_stays_typo_suspect(self, dd, monkeypatch):
        q = "게보린징"
        e0 = route_input(q, dd).entities[0]
        if e0.match_type != "bm25":
            pytest.skip("BM25 일치가 아님")
        top = e0.options[0].score
        monkeypatch.setattr(R, "TYPO_SCORE_MAX", 1.0)
        monkeypatch.setattr(R, "NOT_FOUND_SCORE_MAX", top - 0.01)  # 점수가 임계값보다 높다 → NOT_FOUND 아님
        e = route_input(q, dd).entities[0]
        assert e.status == R.ST_TYPO and e.branch == R.BRANCH_TYPO and e.options
        monkeypatch.setattr(R, "NOT_FOUND_SCORE_MAX", top)  # top <= 임계값 → NOT_FOUND
        assert route_input(q, dd).entities[0].status == R.ST_NOT_FOUND

    def test_threshold_boundary_is_inclusive(self, dd, monkeypatch):
        e0 = route_input("와파린쟁", dd).entities[0]
        if e0.match_type != "bm25":
            pytest.skip("BM25 일치가 아님")
        top = e0.options[0].score
        monkeypatch.setattr(R, "NOT_FOUND_SCORE_MAX", top)
        assert route_input("와파린쟁", dd).entities[0].status == R.ST_NOT_FOUND
        monkeypatch.setattr(R, "NOT_FOUND_SCORE_MAX", round(top - 0.0001, 4))
        assert route_input("와파린쟁", dd).entities[0].status != R.ST_NOT_FOUND

    def test_non_bm25_matches_unaffected_by_threshold(self, dd, monkeypatch):
        monkeypatch.setattr(R, "NOT_FOUND_SCORE_MAX", 1.0)
        assert route_input("게보린정", dd).entities[0].status == R.ST_RESOLVED  # 정확·정규화 일치
        assert route_input("타이레놀", dd).entities[0].status == R.ST_AMBIGUOUS  # 접두 일치 되묻기 유지
        assert route_input("완전히없는약이름", dd).entities[0].status in (R.ST_NOT_FOUND, R.ST_TYPO, R.ST_AMBIGUOUS)

    def test_ambiguous_still_wins_branch_label_over_not_found(self, dd, monkeypatch):
        monkeypatch.setattr(R, "NOT_FOUND_SCORE_MAX", 1.0)
        r = route_input("타이레놀이랑 와파린쟁 같이 먹어도 돼요", dd)
        sts = {e.status for e in r.entities}
        if R.ST_AMBIGUOUS in sts:
            assert r.branch_label == R.BRANCH_AMBIGUOUS
