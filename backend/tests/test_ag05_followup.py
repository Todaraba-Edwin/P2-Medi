"""AG-05 후속(2026-11-12): 잡음 엔티티 규칙 확장, 비저장·비로깅, 필요한 주장 유형 목록(코드 규칙 부분) 시험.

합성 소사전(가상의 제품 이름)과 합성 문장만 쓴다(평가 세트·개발셋·시험셋 문장 아님). LLM·네트워크·DB 호출 없음.
"""

from __future__ import annotations

import ast
import copy
import json
import logging
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_drug_dict import build_dictionary  # noqa: E402

from app.agent import router as R  # noqa: E402
from app.agent.graph.nodes import GraphDeps, make_nodes  # noqa: E402
from app.agent.graph.state import NODE_WRITABLE, AgentState, restrict_update  # noqa: E402
from app.agent.graph.trace import GraphTracer, ListSink  # noqa: E402
from app.agent.router import extract_mentions, required_claims, route_input  # noqa: E402
from app.tools.drug_dict import DrugDict  # noqa: E402


def _p(seq: str, name: str, ingr: str) -> dict:
    return {"item_seq": seq, "item_name": name, "entp_name": "가상사", "spclty_pblc": "일반의약품", "item_ingr_name": ingr, "edi_code": "",
            "cancel_name": "정상"}


SNAPS = {
    "prmsn": [
        _p("201", "가온정", "Alpha"),
        _p("202", "나래캡슐", "Beta"),
        _p("203", "마로정", "Gamma"),          # "마로" = 한 음절 + 조사 꼴이지만 접두 일치라 남아야 한다
        _p("204", "보라정에이", "Delta"),      # "보라" = 어미 꼴(라)이지만 접두 일치(후보 2개)라 남아야 한다
        _p("205", "보라정비", "Delta"),
        _p("206", "다솜좌약", "Epsilon"),      # 제형 이름으로 끝나는 제품
        _p("207", "한울위장약", "Zeta"),       # 약효군 접미(약)로 끝나지만 사전에 있는 제품
    ],
    "eyak": [], "detail": [], "dur_ingr": [], "ingr_codes": {},
}


@pytest.fixture(scope="module")
def dd() -> DrugDict:
    return DrugDict(build_dictionary([], [], SNAPS, {"x": "y"})[0])


# =========================================================================== A. 잡음 엔티티·어미 규칙

class TestNoiseRules:
    @pytest.mark.parametrize("q", [
        "열이 나는데 가온정 먹어도 되나요",
        "눈에 가온정 들어갔어요",
        "밥을 먹고 가온정 먹어도 되나요",
        "한 번에 가온정 먹어도 돼요",
    ])
    def test_one_syllable_plus_particle_is_not_a_drug(self, dd, q):
        assert extract_mentions(q, dd) == ["가온정"]

    @pytest.mark.parametrize("q", [
        "조카한테 가온정 줘도 되나요",
        "할머니께 가온정 드려도 되나요",
        "이웃에게 가온정 줘도 되나요",
        "가온정 두 알씩 먹어도 되나요",
    ])
    def test_recipient_and_distributive_particles(self, dd, q):
        assert extract_mentions(q, dd) == ["가온정"]

    @pytest.mark.parametrize("q", [
        "가온정 정리해 주세요",
        "가온정 복용 충분한 건가요",
        "가온정 써도 된다고 하던데 맞나요",
        "가온정 먹다가 졸리다고 하셨어요",
        "가온정 먹어도 무난하다며 들었어요",
        "가온정 끊거나 줄여도 되나요",
        "가온정 꾸준히 먹어도 되나요",
        "가온정 먹어도 되는지 봐요",
        "가온정 먹으면 잠이 와요",
        "가온정 먹지 말자고 했어요",
        "가온정 먹도록 했어요",
        "가온정 먹으면서 운동해도 되나요",
    ])
    def test_verb_forms_are_not_drugs(self, dd, q):
        assert extract_mentions(q, dd) == ["가온정"]

    @pytest.mark.parametrize("q", ["치통이 있는데 가온정 먹어도 되나요", "위염에 가온정 먹어도 되나요", "불면증을 앓는데 가온정 괜찮나요"])
    def test_symptom_noun_with_particle(self, dd, q):
        assert extract_mentions(q, dd) == ["가온정"]

    @pytest.mark.parametrize("q", ["당뇨약이랑 가온정 같이 먹어도 되나요", "이뇨제를 먹는데 가온정 괜찮나요"])
    def test_drug_class_noun_is_not_a_product(self, dd, q):
        assert extract_mentions(q, dd) == ["가온정"]

    def test_number_with_counter_and_stop_stem(self, dd):
        assert extract_mentions("가온정 3등급 맞나요", dd) == ["가온정"]
        assert extract_mentions("가온정 4가지 맞나요", dd) == ["가온정"]
        assert extract_mentions("가온정 괜찮나", dd) == ["가온정"]

    def test_examples_are_not_hardcoded_stop_words(self):
        """위 시험이 낱말 목록이 아니라 규칙으로 걸러지는지 확인한다."""
        for w in ("열이", "눈에", "조카한테", "할머니께", "정리해", "충분한", "하던데", "꾸준히", "치통", "당뇨약", "이뇨제", "3등급", "괜찮"):
            assert w not in R._STOP_WORDS


class TestNoiseRuleNames:
    @pytest.mark.parametrize(("tok", "rule"), [
        ("열이", R.NOISE_ONE_SYLLABLE),
        ("조카한테", R.NOISE_RECIPIENT),
        ("알씩", R.NOISE_RECIPIENT),
        ("정리해", R.NOISE_VERB_END),
        ("충분한", R.NOISE_VERB_END),
        ("된다고", R.NOISE_VERB_END),       # 용언 어미(다) + 인용 조사(고)
        ("무난하다며", R.NOISE_VERB_END),
        ("봐요", R.NOISE_VERB_END),
        ("치통이", R.NOISE_NOUN_SUFFIX),
        ("당뇨약이랑", R.NOISE_NOUN_SUFFIX),
        ("괜찮나", R.NOISE_STOP_STEM),
    ])
    def test_rule(self, tok, rule):
        assert R._noise_rule(tok, R._variants(tok)) == rule

    @pytest.mark.parametrize("tok", ["가온정", "나래캡슐을", "하늘좌약", "별빛산제", "구름라를", "구름아가", "가온정이요"])
    def test_no_rule_for_drug_like_tokens(self, tok):
        """제형으로 끝나는 이름, 격조사(을·를·이·가)가 붙은 이름은 어미 꼴로 끝나도 규칙에 걸리지 않는다(오탈자 약 보호)."""
        assert R._noise_rule(tok, R._variants(tok)) is None

    def test_contracted_yo_only_for_wa_wo(self):
        assert R._ends_contracted_yo("메스꺼워요") and R._ends_contracted_yo("와요") and R._ends_contracted_yo("줘요")
        assert not R._ends_contracted_yo("가온정이요") and not R._ends_contracted_yo("요") and not R._ends_contracted_yo("원요")


class TestNoiseGuards:
    """퇴행 방지: 규칙 꼴이어도 사전에 이름으로 맞으면(정확·접두·중간) 약 후보로 남는다."""

    def test_two_char_prefix_is_kept(self, dd):
        r = route_input("마로 먹어도 되나요", dd)   # 마 + 로(조사 꼴)
        assert [e.raw for e in r.entities] == ["마로"] and r.entities[0].status != R.ST_NOT_FOUND

    @pytest.mark.parametrize("q", ["보라를 먹어도 되나요", "보라는 먹어도 되나요", "보라만 먹어도 되나요"])
    def test_abbreviated_name_ending_like_a_verb_is_kept_and_asked(self, dd, q):
        r = route_input(q, dd)
        assert [e.raw for e in r.entities] == ["보라"]
        assert r.ambiguous and r.branch_label == R.BRANCH_AMBIGUOUS and len(r.clarify.options) == 2

    def test_dictionary_name_ending_with_class_suffix_is_kept(self, dd):
        r = route_input("한울위장약 먹어도 되나요", dd)
        assert [e.status for e in r.entities] == [R.ST_RESOLVED]
        assert route_input("다솜좌약 써도 되나요", dd).entities[0].status == R.ST_RESOLVED

    def test_unknown_dosage_form_name_stays_a_candidate(self, dd):
        """사전에 없는 '…좌약'은 제형 이름이라 약효군 규칙으로 버리지 않는다(지금처럼 확인 못 함으로 남는다)."""
        assert extract_mentions("하늘좌약 써도 되나요", dd) == ["하늘좌약"]

    def test_misspelled_name_with_case_particle_stays_a_candidate(self, dd):
        """격조사를 뗀 꼴이 어미처럼 끝나도(…라) 약 후보로 남긴다. 인용·보조 조사(고·는·며·도·만)일 때만 어미 규칙을 적용한다."""
        assert extract_mentions("구름라를 먹어도 되나요", dd) == ["구름라를"]

    def test_noise_removal_gives_normal_label(self, dd):
        r = route_input("열이 나서 조카한테 가온정 줘도 된다고 하던데 괜찮나", dd)
        assert [e.raw for e in r.entities] == ["가온정"]
        assert r.branch_label == R.BRANCH_NORMAL and not r.ambiguous and r.clarify is None

    def test_real_not_found_drug_still_reported(self, dd):
        """잡음을 줄여도 사전에 없는 약 이름은 '근거 없음'으로 남는다(없다고 안전하다는 뜻이 아니다)."""
        r = route_input("가온정이랑 쿠쿠루정 같이 먹어도 되나요", dd)
        assert len(r.entities) == 2 and r.branch_label != R.BRANCH_NORMAL

    def test_intent_does_not_depend_on_noise_count(self, dd):
        """잡음이 빠져 약이 1개가 돼도 허락을 묻는 꼴·이미 먹은 꼴은 금기 유형으로 남는다."""
        assert R.INTENT_CONTRA in route_input("조카한테 가온정 줘도 되나요", dd).intent
        assert R.INTENT_CONTRA in route_input("조카가 가온정 먹었어. 어떻게 돼", dd).intent


class TestCopulaEnding:
    """ "이다" 활용(인데·인지 등)이 붙은 약 이름은 토큰째 버리지 않고 앞말을 후보로 쓴다. 앞말이 약 이름이 아니면 지금처럼 버린다."""

    @pytest.mark.parametrize(("q", "want"), [
        ("가온정인데 먹어도 되나요", ["가온정"]),
        ("가온정인지 확인해 주세요", ["가온정"]),
        ("먹는 약이 가온정500mg인지 확인해 주세요", ["가온정500mg"]),
        ("쿠쿠루정10밀리그램인가요", ["쿠쿠루정10밀리그램"]),   # 사전에 없어도 함량 표기로 끝나면 후보(확인 못 함으로 남는다)
    ])
    def test_drug_name_before_copula_is_kept(self, dd, q, want):
        assert extract_mentions(q, dd) == want

    def test_abbreviated_name_before_copula_is_asked(self, dd):
        r = route_input("마로인데 먹어도 되나요", dd)   # 접두 일치(줄여 부른 이름)는 자동 확정하지 않고 되묻는다
        assert [e.raw for e in r.entities] == ["마로"] and r.ambiguous and not r.entities[0].resolved

    @pytest.mark.parametrize("q", ["몸살인데 가온정 먹어도 되나요", "초등학생인데 가온정 먹어도 되나요", "어떤 약인지 가온정 알려줘"])
    def test_non_drug_before_copula_is_still_dropped(self, dd, q):
        assert extract_mentions(q, dd) == ["가온정"]


# =========================================================================== B. 비저장·비로깅

_ALLOWED_IMPORTS = {"__future__", "dataclasses", "re", "typing", "pydantic", "app.tools.drug_dict"}
_IO_CALLS = {"open", "print", "exec", "eval", "__import__"}
_IO_ATTRS = {"write_text", "write_bytes", "write", "getLogger", "connect", "execute", "dump", "urlopen", "Popen", "system"}
_AUDIT_PREFIXES = ("open", "os.", "socket.", "sqlite3.", "subprocess.", "shutil.", "urllib.", "http.", "ftplib.", "smtplib.")
_audit_log: list[str] = []
_audit_on = False


def _audit_hook(event: str, args: tuple[Any, ...]) -> None:
    if _audit_on and event.startswith(_AUDIT_PREFIXES):
        _audit_log.append(event)


sys.addaudithook(_audit_hook)  # 훅은 지울 수 없어서 `_audit_on`으로 창을 연다(창 밖에서는 아무것도 하지 않는다)


def _io_events(fn) -> list[str]:
    """`fn()` 실행 중에 생긴 파일·소켓·DB·프로세스 감사 이벤트 이름."""
    global _audit_on
    _audit_log.clear()
    _audit_on = True
    try:
        fn()
    finally:
        _audit_on = False
    return list(_audit_log)


Q_PRIVATE = "37살 임신 중인데 가온정 먹어도 되나요"


class TestNoStorageNoLogging:
    def test_router_source_has_no_io_imports_or_calls(self):
        tree = ast.parse(Path(R.__file__).read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    assert node.func.id not in _IO_CALLS, f"router.py가 {node.func.id}()를 부른다"
                elif isinstance(node.func, ast.Attribute):
                    assert node.func.attr not in _IO_ATTRS, f"router.py가 .{node.func.attr}()를 부른다"
        assert imported <= _ALLOWED_IMPORTS, f"허용 밖 import: {imported - _ALLOWED_IMPORTS}"

    def test_audit_hook_detects_file_access(self, tmp_path):
        """감사 훅이 실제로 파일 접근을 잡는지(아래 시험이 빈 통과가 아님) 확인한다."""
        assert "open" in _io_events(lambda: (tmp_path / "probe.txt").write_text("x", encoding="utf-8"))

    @pytest.mark.parametrize("profile", [None, {"age_years": 70, "pregnant": False, "source": "profile"}], ids=["guest", "profile"])
    def test_no_file_socket_db_access(self, dd, profile, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        route_input(Q_PRIVATE, dd, profile).state_update()  # 지연 import가 창 안에서 파일을 열지 않게 먼저 한 번 돈다
        events = _io_events(lambda: route_input(Q_PRIVATE, dd, profile).state_update())
        assert events == []
        assert list(tmp_path.iterdir()) == []  # 작업 폴더에 파일·`logs/`가 생기지 않는다

    @pytest.mark.parametrize("profile", [None, {"age_years": 70, "pregnant": False, "source": "profile"}], ids=["guest", "profile"])
    def test_no_log_records_and_no_stdout(self, dd, profile, caplog, capsys):
        with caplog.at_level(logging.DEBUG):
            route_input(Q_PRIVATE, dd, profile).state_update()
        assert caplog.records == []
        out = capsys.readouterr()
        assert out.out == "" and out.err == ""

    def test_guest_values_do_not_carry_over_to_next_call(self, dd):
        """게스트: 추출한 연령·임신 여부는 그 호출의 반환값에만 있다(모듈 전역·캐시에 남지 않는다)."""
        first = route_input(Q_PRIVATE, dd)
        assert first.profile.age_years == 37 and first.profile.pregnant is True and first.profile.source == "question"
        second = route_input("가온정 먹어도 되나요", dd)
        assert second.profile.model_dump() == {"age_years": None, "pregnant": None, "source": "none"}

    def test_module_state_unchanged_by_calls(self, dd):
        def snapshot() -> dict[str, str]:
            return {k: repr(v) for k, v in vars(R).items()
                    if not k.startswith("__") and isinstance(v, (dict, list, set, frozenset, tuple, str, int, float))}
        before = snapshot()
        route_input(Q_PRIVATE, dd)
        route_input(Q_PRIVATE, dd, {"age_years": 70})
        assert snapshot() == before
        assert not any("37" in v and "임신" in v for v in before.values())

    def test_profile_input_is_not_mutated_and_question_value_is_not_written_back(self, dd):
        """프로필 사용: 질문에서 뽑은 값이 넘겨받은 프로필 객체에 되써지지 않는다(저장되는 것은 동의한 프로필 항목뿐)."""
        prof = {"age_years": 70, "pregnant": False, "source": "profile"}
        saved = copy.deepcopy(prof)
        r = route_input(Q_PRIVATE, dd, prof)
        assert prof == saved
        assert r.profile.age_years == 37 and r.profile.pregnant is True and r.profile.source == "question"
        model = R.ProfileState(age_years=70)
        route_input(Q_PRIVATE, dd, model)
        assert model.age_years == 70 and model.pregnant is None

    def test_guest_and_profile_sources_are_distinguished(self, dd):
        q = "가온정 먹어도 되나요"
        assert route_input(q, dd).profile.source == "none"
        assert route_input(q, dd, {"age_years": 70}).profile.source == "profile"
        assert route_input(Q_PRIVATE, dd, {"age_years": 70}).profile.source == "question"

    def test_age_and_pregnancy_live_only_in_profile_key(self, dd):
        """상태에서 연령·임신 값은 `profile` 키에만 있고, 질문 문장 전체는 어느 키에도 없다(대화 내용 비저장)."""
        upd = route_input(Q_PRIVATE, dd).state_update()
        assert set(upd["profile"]) == {"age_years", "pregnant", "source"}
        rest = json.dumps({k: v for k, v in upd.items() if k != "profile"}, ensure_ascii=False)
        assert "37" not in rest and "임신" not in rest
        assert Q_PRIVATE not in json.dumps(upd, ensure_ascii=False)


def _router_node(dd: DrugDict):
    deps = GraphDeps(drug_dict=dd, tool_model=None, summary_model=None, tools=[], tool_ctx=None, system_prompt="")  # router 노드는 사전만 쓴다
    return make_nodes(deps)["router"]


class TestRouterNodeLeavesNoPrivateValuesInEventsOrTrace:
    """로그로 나가는 길은 노드의 `events`와 L2 trace span뿐이다. 둘 다 연령·임신·질문 문장을 담지 않는다."""

    STATE: AgentState = {"question": Q_PRIVATE, "profile": {"age_years": 70, "pregnant": False, "source": "profile"}}

    def test_events_have_only_counts_and_labels(self, dd):
        upd = _router_node(dd)(self.STATE)
        assert upd["profile"]["age_years"] == 37  # 값은 상태에 있다
        (ev,) = upd["events"]
        assert set(ev) == {"rule", "event", "branch", "ambiguous", "n_entities"}
        text = json.dumps(upd["events"], ensure_ascii=False)
        assert "37" not in text and "70" not in text and "임신" not in text and "pregnan" not in text and "age" not in text

    def test_trace_span_has_no_age_pregnancy_or_question(self, dd, monkeypatch):
        # 무작위 trace_id(uuid4 hex)·실측 latency_ms에 "37"·"70"이 우연히 들어가 간헐 실패하던 것을 막는다(RFP-04-03 A).
        # id·시계만 고정하고 노드·tracer 동작은 그대로 둔다.
        monkeypatch.setattr("app.agent.graph.trace.uuid", SimpleNamespace(uuid4=lambda: uuid.UUID(int=0)))
        sink = ListSink()
        GraphTracer(sink=sink, clock=lambda: 0.0).wrap_node("router", _router_node(dd))(self.STATE)
        assert len(sink.records) == 1
        assert sink.records[0]["trace_id"] == "t-000000000000"  # 고정이 실제로 걸렸는지
        text = json.dumps(sink.records, ensure_ascii=False, default=str)
        for needle in ("37", "70", "임신", "pregnan", "age_years", "profile", "가온정", Q_PRIVATE):
            assert needle not in text
        assert sink.records[0]["output_summary"] == {"n_entities": 1, "ambiguous": False, "branch": R.BRANCH_NORMAL}

    def test_node_update_passes_state_key_restriction(self, dd):
        upd = _router_node(dd)(self.STATE)
        assert restrict_update("router", upd) == upd  # 막힌 키 없음(STATE_KEY_BLOCKED 이벤트가 붙지 않는다)
        assert set(upd) <= NODE_WRITABLE["router"]


# =========================================================================== C. 필요한 주장 유형(코드 규칙 부분)

class TestRequiredClaims:
    def test_seven_claim_types_match_design_doc(self):
        assert [R.CLAIM_LABELS_KO[c] for c in R.CLAIM_TYPES] == ["금기 여부", "등급 정의", "금기 사유", "제품 주의", "용어·절차", "한계·고지", "기준일"]
        assert len(set(R.CLAIM_TYPES)) == 7 and R.CLAIMS_BY_CODE_RULE < set(R.CLAIM_TYPES)

    def test_contraindication_question(self, dd):
        r = route_input("가온정이랑 나래캡슐 같이 먹어도 되나요", dd)
        assert r.intent == [R.INTENT_CONTRA]
        assert r.required_claims == [R.CLAIM_CONTRA_STATUS, R.CLAIM_LIMITATION, R.CLAIM_AS_OF]

    def test_profile_signal_question(self, dd):
        r = route_input("임신 중인데 가온정 먹어도 되나요", dd)
        assert R.CLAIM_CONTRA_STATUS in r.required_claims and R.CLAIM_LIMITATION in r.required_claims

    def test_drug_info_question(self, dd):
        r = route_input("가온정은 무슨 약이에요", dd)
        assert r.intent == [R.INTENT_DRUG_INFO]
        assert r.required_claims == [R.CLAIM_PRODUCT_CAUTION, R.CLAIM_LIMITATION]

    def test_two_intents_are_merged_in_design_doc_order(self, dd):
        r = route_input("가온정이랑 나래캡슐 같이 먹어도 되는지와 효능을 알려줘", dd)
        assert {R.INTENT_CONTRA, R.INTENT_DRUG_INFO} <= set(r.intent)
        assert r.required_claims == [R.CLAIM_CONTRA_STATUS, R.CLAIM_PRODUCT_CAUTION, R.CLAIM_LIMITATION, R.CLAIM_AS_OF]

    def test_open_and_document_questions_get_only_the_notice(self, dd):
        """등급 정의·용어·절차는 프롬프트 분류 몫이라 코드 규칙으로 채우지 않는다. 한계·고지는 항상 든다."""
        r = route_input("피해야 할 진통제가 뭐예요", dd)
        assert r.intent == [R.INTENT_OPEN] and r.required_claims == [R.CLAIM_LIMITATION]
        assert required_claims([R.INTENT_OPEN]) == [R.CLAIM_LIMITATION]
        assert required_claims([R.INTENT_DOCUMENT], "병용금기 2등급이 무슨 뜻이에요") == [R.CLAIM_LIMITATION]
        assert required_claims([]) == [R.CLAIM_LIMITATION]

    def test_as_of_asked_directly(self):
        assert required_claims([R.INTENT_DOCUMENT], "이 자료 기준일이 언제예요") == [R.CLAIM_LIMITATION, R.CLAIM_AS_OF]

    @pytest.mark.parametrize("intent", [[R.INTENT_CONTRA], [R.INTENT_DRUG_INFO], [R.INTENT_DOCUMENT], [R.INTENT_OPEN],
                                        [R.INTENT_CONTRA, R.INTENT_DRUG_INFO, R.INTENT_DOCUMENT]])
    def test_code_rule_never_emits_prompt_side_types(self, intent):
        got = required_claims(intent, "등급 정의와 금기 사유, 용어를 알려줘")
        assert set(got) <= R.CLAIMS_BY_CODE_RULE
        assert not {R.CLAIM_GRADE_DEFINITION, R.CLAIM_CONTRA_REASON, R.CLAIM_TERM_PROCEDURE} & set(got)
        assert got == [c for c in R.CLAIM_TYPES if c in got]  # 설계 문서 순서, 중복 없음

    def test_recorded_in_state_and_writable(self, dd):
        r = route_input("가온정이랑 나래캡슐 같이 먹어도 되나요", dd)
        upd = r.state_update()
        assert upd["required_claims"] == r.required_claims
        assert "required_claims" in R.ROUTER_WRITABLE_KEYS and "required_claims" in AgentState.__annotations__
        assert set(upd) == set(R.ROUTER_WRITABLE_KEYS)

    def test_existing_state_fields_unchanged(self, dd):
        """새 필드를 더해도 기존 필드 이름·모양은 그대로다(다른 노드가 읽는다)."""
        upd = route_input("가온정 먹어도 되나요", dd).state_update()
        for k in ("profile", "drug_mentions", "intent", "entities", "branch_label", "ambiguous", "clarify", "truncated"):
            assert k in upd
        assert "required_claims" not in R.NOTE_ENTITY_KEYS  # 모델 입력 블록(ROUTER_NOTE)은 바꾸지 않는다

    def test_emergency_passthrough_does_not_change_claims(self, dd):
        q = "가온정이랑 나래캡슐 같이 먹어도 되나요"
        assert route_input(q, dd).required_claims == route_input(q, dd, emergency=True, guardrail_route="정상").required_claims
