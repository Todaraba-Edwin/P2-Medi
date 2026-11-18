"""AG-05 후속(2026-11-18): 되묻기 후보 1개 문구, 잡음 낱말 2차 규칙·표기 변형, 프롬프트 분류기(기본 꺼짐, 가짜 모델만). 외부 호출 0."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_drug_dict import build_dictionary  # noqa: E402

from app.agent import router as R  # noqa: E402
from app.agent import router_classify as C  # noqa: E402
from app.agent.router import extract_mentions, route_input  # noqa: E402
from app.llm import prompts as P  # noqa: E402
from app.tools.drug_dict import DrugDict  # noqa: E402


def _p(seq: str, name: str, ingr: str) -> dict:
    return {"item_seq": seq, "item_name": name, "entp_name": "가상사", "spclty_pblc": "일반의약품", "item_ingr_name": ingr, "edi_code": "",
            "cancel_name": "정상"}


SNAPS = {
    "prmsn": [
        _p("301000001", "가온정", "Alpha"),
        _p("301000002", "마로정", "Gamma"),            # "마로" → 후보 1개(접두 일치)
        _p("301000003", "보라정에이", "Delta"),        # "보라" → 후보 2개
        _p("301000004", "보라정비", "Delta"),
        _p("301000005", "이제로정", "Eta"),            # 부사 "이제"가 접두로 걸리는 제품
        _p("301000006", "솔솔", "Theta"),              # 2음절 제품명(정확 일치)
        _p("301000007", "누리캡슐300밀리그램", "Iota"),  # "누리캅셀300밀리그램" 옛 표기
        _p("301000008", "다솜패취10μg/h", "Kappa"),     # 시간당 함량 표기
    ],
    "eyak": [], "detail": [], "dur_ingr": [], "ingr_codes": {},
}


@pytest.fixture(scope="module")
def dd() -> DrugDict:
    return DrugDict(build_dictionary([], [], SNAPS, {"x": "y"})[0])


# =========================================================================== 1. 되묻기 후보 1개 문구(AG-05 §3 "여러 개예요")

class TestClarifyOneCandidate:
    def test_one_candidate_does_not_say_many(self, dd):
        r = route_input("마로 먹어도 되나요", dd)
        assert r.ambiguous and len(r.clarify.options) == 1
        assert "여러 개" not in r.clarify.question
        assert r.clarify.question == "'마로': 어떤 약인지 하나를 골라 주세요."  # 승인 전: 기존 문장에서 틀린 절만 뺀 꼴

    def test_many_candidates_keep_existing_sentence(self, dd):
        r = route_input("보라를 먹어도 되나요", dd)
        assert len(r.clarify.options) == 2
        assert r.clarify.question == "'보라'에 해당하는 약이 여러 개예요. 어떤 약인지 하나를 골라 주세요."

    def test_draft_is_used_only_after_approval(self, dd, monkeypatch):
        assert R.CLARIFY_ONE_CANDIDATE_APPROVED is False
        monkeypatch.setattr(R, "CLARIFY_ONE_CANDIDATE_APPROVED", True)
        q = route_input("마로 먹어도 되나요", dd).clarify.question
        assert q == R.CLARIFY_ONE_CANDIDATE.format(drug="마로")

    def test_draft_has_no_verdict_or_dose(self):
        t = R.CLARIFY_ONE_CANDIDATE
        assert t.count("?") == 1 and "{drug}" in t
        for bad in ("안전", "괜찮", "먹어도 돼", "복용하세요", "mg", "밀리그램"):
            assert bad not in t


# =========================================================================== 2. 잡음 낱말 2차 규칙

class TestNoiseRule2:
    @pytest.mark.parametrize("q", [
        "시간 지나서 가온정 먹어도 되나요",       # 2음절, 사전에 이름으로 없음
        "수유 중인데 가온정 먹어도 되나요",
        "아이가 드시는 가온정 먹어도 되나요",     # "드시는" → "드시"
        "아무 문제 없다던데 가온정 먹어도 되나요",  # 닫힌 품사
        "이제 가온정 먹어도 되나요",              # 닫힌 품사가 제품 접두("이제로정")에 걸려도 버린다
    ])
    def test_noise_dropped(self, dd, q):
        assert extract_mentions(q, dd) == ["가온정"]

    def test_short_name_in_dictionary_is_kept(self, dd):
        r = route_input("솔솔 먹어도 되나요", dd)
        assert [e.status for e in r.entities] == [R.ST_RESOLVED]

    def test_short_prefix_name_is_kept_and_asked(self, dd):
        """2음절이어도 사전 접두 일치(줄여 부른 이름)면 버리지 않고 되묻는다(AG-05-01 A)."""
        r = route_input("마로 먹어도 되나요", dd)
        assert [e.raw for e in r.entities] == ["마로"] and r.ambiguous

    def test_longer_unknown_name_still_reported(self, dd):
        """3음절 이상 사전에 없는 이름은 지금처럼 '근거 없음'으로 남는다(없다고 안전하다는 뜻이 아니다)."""
        r = route_input("가온정이랑 쿠쿠루정 같이 먹어도 되나요", dd)
        assert [e.raw for e in r.entities] == ["가온정", "쿠쿠루정"] and r.branch_label == R.BRANCH_NO_EVIDENCE

    def test_rule_names(self, dd):
        assert R._noise_rule2("아무", ["아무"], dd) == R.NOISE_FUNCTION_WORD
        assert R._noise_rule2("시간", ["시간"], dd) == R.NOISE_SHORT_UNKNOWN
        assert R._noise_rule2("솔솔", ["솔솔"], dd) is None
        assert R._noise_rule2("마로", ["마로"], dd) is None

    def test_function_words_are_not_dictionary_names(self, dd):
        for w in R._FUNCTION_WORDS:
            assert not R._strong(dd, w), w

    def test_emergency_flag_still_does_not_change_result(self, dd):
        q = "아이가 시간 지나서 가온정 먹었어"
        assert route_input(q, dd, emergency=True).state_update() == route_input(q, dd, emergency=False).state_update()

    @pytest.mark.parametrize("q", ["가온정 먹으면 안 되나요", "가온정 먹을 수 있나요", "가온정 먹을 수 있을까요", "아이한테 가온정 먹일 수 있는지"])
    def test_permission_forms_are_contraindication(self, dd, q):
        assert R.INTENT_CONTRA in route_input(q, dd).intent

    def test_dose_count_question_is_not_contraindication(self, dd):
        assert R.INTENT_CONTRA not in route_input("가온정 하루에 몇 번까지 먹을 수 있어요?", dd).intent


class TestSpellingVariants:
    def test_old_capsule_spelling_resolves(self, dd):
        r = route_input("누리캅셀300밀리그램 먹어도 되나요", dd)
        assert [(e.status, e.item_seq) for e in r.entities] == [(R.ST_RESOLVED, "301000007")]

    def test_spelling_variant_only_when_exact(self, dd):
        """표기를 바꿔도 정확·정규화 일치가 아니면 쓰지 않는다(되묻기·근거 없음은 그대로)."""
        r = route_input("누리캅셀 먹어도 되나요", dd)
        assert r.entities[0].raw == "누리캅셀" and r.entities[0].status != R.ST_RESOLVED

    def test_per_hour_strength_not_split(self, dd):
        assert extract_mentions("다솜패취10μg/h 붙여도 되나요", dd) == ["다솜패취10μg/h"]
        assert route_input("다솜패취10μg/h 붙여도 되나요", dd).entities[0].status == R.ST_RESOLVED

    def test_slash_between_names_still_splits(self, dd):
        assert extract_mentions("가온정/솔솔 같이 먹어도 되나요", dd) == ["가온정", "솔솔"]
        assert extract_mentions("가온정 5mg/마로정 같이", dd)[0].startswith("가온정")


# =========================================================================== 3. 프롬프트 분류기(기본 꺼짐, 가짜 모델)

def _out(**kw) -> dict:
    base = {"drug_mentions": [], "conditions": [], "age_years": None, "pregnancy": "unknown", "intent": ["contraindication"], "needed_claims": []}
    return {**base, **kw}


class FakeModel:
    def __init__(self, out):
        self.out = out
        self.calls: list[list[dict[str, str]]] = []

    def __call__(self, messages):
        self.calls.append(messages)
        if isinstance(self.out, Exception):
            raise self.out
        return self.out


class TestClassifierOffByDefault:
    def test_default_is_off_and_equals_rule(self, dd):
        fake = FakeModel(_out(drug_mentions=["가온정"]))
        q = "시간 지나서 쿠쿠루정 먹어도 되나요"
        o = C.route_with_classifier(q, dd, call=fake)
        assert C.ROUTER_LLM_CLASSIFY_DEFAULT is False and not o.used and fake.calls == []
        assert o.result == route_input(q, dd)

    def test_no_call_function_means_rule_only(self, dd):
        o = C.route_with_classifier("가온정 먹어도 되나요", dd, enabled=True)
        assert not o.used and o.result == route_input("가온정 먹어도 되나요", dd)

    def test_service_and_eval_paths_do_not_import_classifier(self):
        root = Path(__file__).resolve().parents[1] / "app"
        for p in [*(root / "agent" / "graph").glob("*.py"), *(root / "agent" / "pipeline").rglob("*.py"), root / "agent" / "router.py"]:
            assert "router_classify" not in p.read_text(encoding="utf-8"), p


class TestClassifierValidation:
    @pytest.mark.parametrize("raw,err", [
        ("{not json", "JSON_INVALID"),
        ([1, 2], "NOT_OBJECT"),
        ({"drug_mentions": []}, "SCHEMA_INVALID"),
        (_out(intent=[]), "SCHEMA_INVALID"),
        (_out(intent=["route_to_tool"]), "SCHEMA_INVALID"),
        (_out(age_years=300), "SCHEMA_INVALID"),
        (_out(extra="x"), "SCHEMA_INVALID"),
        (_out(drug_mentions=["a", "b", "c", "d", "e", "f", "g"]), "SCHEMA_INVALID"),
    ])
    def test_bad_output_falls_back_to_rule(self, dd, raw, err):
        q = "가온정 먹어도 되나요"
        o = C.route_with_classifier(q, dd, call=FakeModel(raw), enabled=True)
        assert not o.used and o.error == err and o.result == route_input(q, dd)

    def test_call_failure_falls_back(self, dd):
        o = C.route_with_classifier("가온정 먹어도 되나요", dd, call=FakeModel(TimeoutError()), enabled=True)
        assert not o.used and o.error == "CALL_FAILED:TimeoutError"

    def test_json_string_is_accepted(self, dd):
        o = C.route_with_classifier("가온정 먹어도 되나요", dd, call=FakeModel(json.dumps(_out(drug_mentions=["가온정"]))), enabled=True)
        assert o.used and o.error is None

    def test_invented_names_are_dropped(self, dd):
        chk = C.validate_output(_out(drug_mentions=["가온정", "솔솔"], conditions=["두통", "고혈압"]), "두통에 가온정 먹어도 되나요")
        assert chk.value.drug_mentions == ["가온정"] and chk.dropped_mentions == ["솔솔"]
        assert chk.value.conditions == ["두통"] and chk.dropped_conditions == ["고혈압"]


class TestClassifierMerge:
    def test_removes_unresolved_noise_not_named_by_model(self, dd):
        q = "가온정이랑 하늘구름 같이 먹어도 되나요"   # "하늘구름": 사전에 없는 낱말(규칙은 근거 없음 엔티티로 남김)
        rule = route_input(q, dd)
        assert [e.raw for e in rule.entities] == ["가온정", "하늘구름"]
        o = C.route_with_classifier(q, dd, call=FakeModel(_out(drug_mentions=["가온정"])), enabled=True)
        assert [e.raw for e in o.result.entities] == ["가온정"] and o.removed == ["하늘구름"]
        assert o.result.branch_label == R.BRANCH_NORMAL

    def test_never_removes_resolved_drug(self, dd):
        o = C.route_with_classifier("가온정이랑 솔솔 같이 먹어도 되나요", dd, call=FakeModel(_out(drug_mentions=[])), enabled=True)
        assert [e.raw for e in o.result.entities] == ["가온정", "솔솔"] and o.removed == []

    def test_adds_only_dictionary_resolved_names(self, dd):
        q = "가온정 먹는데 감기에 솔솔 그리고 마로도 괜찮나요"
        rule = route_input(q, dd)
        fake = FakeModel(_out(drug_mentions=["가온정", "솔솔", "마로"]))
        o = C.route_with_classifier(q, dd, call=fake, enabled=True)
        raws = [e.raw for e in o.result.entities]
        assert "가온정" in raws
        # 마로(접두 일치·되묻기 대상)는 LLM 제안으로 새로 더하지 않는다. 규칙이 이미 뽑았으면 그대로 둔다
        assert raws.count("마로") == [e.raw for e in rule.entities].count("마로")
        assert all(a in ("솔솔",) for a in o.added)

    def test_ambiguous_drug_named_by_model_keeps_clarify(self, dd):
        o = C.route_with_classifier("보라를 먹어도 되나요", dd, call=FakeModel(_out(drug_mentions=["보라를"])), enabled=True)
        assert o.result.ambiguous and o.removed == []

    def test_profile_rule_wins_and_possible_is_not_used(self, dd):
        o = C.route_with_classifier("37살인데 가온정 먹어도 되나요", dd, call=FakeModel(_out(age_years=40, pregnancy="possible")), enabled=True)
        assert o.result.profile.age_years == 37 and o.result.profile.pregnant is None
        o2 = C.route_with_classifier("가온정 먹어도 되나요", dd, call=FakeModel(_out(pregnancy="yes")), enabled=True)
        assert o2.result.profile.pregnant is True and o2.result.profile.source == "question"

    def test_intent_and_claims_are_added_not_removed(self, dd):
        q = "가온정 임부금기 2등급이 무슨 뜻이에요"
        rule = route_input(q, dd)
        o = C.route_with_classifier(q, dd, call=FakeModel(_out(drug_mentions=["가온정"], intent=["document"], needed_claims=["grade_definition"])),
                                    enabled=True)
        assert set(rule.intent) <= set(o.result.intent) and R.INTENT_DOCUMENT in o.result.intent
        assert R.CLAIM_GRADE_DEFINITION in o.result.required_claims and set(rule.required_claims) <= set(o.result.required_claims)

    def test_out_of_scope_is_a_label_only(self, dd):
        o = C.route_with_classifier("가온정 몇 알 먹어야 해요", dd, call=FakeModel(_out(drug_mentions=["가온정"], intent=["out_of_scope"])), enabled=True)
        assert C.INTENT_OUT_OF_SCOPE in o.result.intent and o.result.guardrail_route is None and not o.result.ambiguous

    def test_open_is_dropped_when_a_drug_is_present(self, dd):
        o = C.route_with_classifier("가온정 먹어도 되나요", dd, call=FakeModel(_out(drug_mentions=["가온정"], intent=["open", "contraindication"])),
                                    enabled=True)
        assert R.INTENT_OPEN not in o.result.intent

    def test_conditions_are_returned_but_not_written_to_state(self, dd):
        o = C.route_with_classifier("두통에 가온정 먹어도 되나요", dd, call=FakeModel(_out(drug_mentions=["가온정"], conditions=["두통"])), enabled=True)
        assert o.conditions == ["두통"] and "conditions" not in o.result.state_update()
        assert set(o.result.state_update()) <= R.ROUTER_WRITABLE_KEYS

    def test_messages_carry_prompt_and_question_only(self, dd):
        fake = FakeModel(_out(drug_mentions=["가온정"]))
        C.route_with_classifier("가온정 먹어도 되나요", dd, call=fake, enabled=True)
        (msgs,) = fake.calls
        assert [m["role"] for m in msgs] == ["system", "user"] and msgs[1]["content"] == "가온정 먹어도 되나요"
        assert msgs[0]["content"] == C.load_prompt() and not msgs[0]["content"].startswith("---")


class TestClassifierSchemaAndPrompt:
    def test_strict_schema_shape(self):
        s = C.classification_json_schema()
        assert s["strict"] is True and s["name"] == "router_classify"
        props = s["schema"]["properties"]
        assert set(props) == set(s["schema"]["required"]) == set(C.RouterClassification.model_fields)
        assert s["schema"]["additionalProperties"] is False

    def test_prompt_file_is_draft_and_passes_l0(self):
        path = C.PROMPT_PATH
        fm, _ = P.split_frontmatter(path.read_text(encoding="utf-8"))
        assert fm["status"] == "draft" and fm["ticket"] == "AG-05"
        assert P.check_prompt_file(path, dev_questions=P.load_dev_questions()) == []

    def test_prompt_is_not_in_any_prompt_set(self):
        for sp in sorted((C.PROMPT_PATH.parent).glob("prompt_set@v*.yaml")):
            assert C.PROMPT_ID not in sp.read_text(encoding="utf-8"), sp

    def test_cost_estimate_and_cli_refuses_test_set(self, tmp_path, capsys):
        assert 0 < C.estimate_usd(150) < 0.05
        sealed = tmp_path / "test_set.SEALED.jsonl"
        sealed.write_text("", encoding="utf-8")
        with pytest.raises(SystemExit):
            C.main(["--dict", "x", "--dev-set", str(sealed), "--max-usd", "0.05"])

    def test_cli_without_yes_makes_no_call(self, tmp_path, capsys, monkeypatch):
        dev = tmp_path / "dev_set.jsonl"
        dev.write_text(json.dumps({"id": "dev-001", "set": "dev", "question": "가온정 먹어도 되나요"}) + "\n", encoding="utf-8")
        monkeypatch.setattr(C, "make_openai_call", lambda *a, **k: pytest.fail("호출 함수를 만들면 안 된다"))
        assert C.main(["--dict", "x", "--dev-set", str(dev), "--max-usd", "0.05"]) == 0
        assert "어림 비용" in capsys.readouterr().out
