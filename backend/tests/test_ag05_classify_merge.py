"""AG-05 2차(2026-11-18): 분류기 병합의 충돌 처리(규칙 우선·LLM 보완), 모호 되묻기 물음표 초안, 분류기 경로의 비저장·비로깅. 외부 호출 0(가짜 모델)."""

from __future__ import annotations

import ast
import json
import logging
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_drug_dict import build_dictionary  # noqa: E402

from app.agent import fixed_phrases as fp  # noqa: E402
from app.agent import router as R  # noqa: E402
from app.agent import router_classify as C  # noqa: E402
from app.agent.router import route_input  # noqa: E402
from app.tools.drug_dict import MATCH_EXACT, MATCH_NORMALIZED, DrugDict  # noqa: E402


def _p(seq: str, name: str, ingr: str) -> dict:
    return {"item_seq": seq, "item_name": name, "entp_name": f"가상사{seq[-1]}", "spclty_pblc": "일반의약품", "item_ingr_name": ingr,
            "edi_code": "", "cancel_name": "정상"}


SNAPS = {
    "prmsn": [
        _p("302000001", "가온정", "Alpha"),
        _p("302000002", "솔솔", "Theta"),
        _p("302000003", "보라정에이", "Delta"),       # "보라" → 접두 일치 후보 2개(모호)
        _p("302000004", "보라정비", "Delta"),
        _p("302000005", "누리정", "Iota"),            # 같은 이름 제품 2개 → 이름 그대로(정확) 일치인데 모호
        _p("302000006", "누리정", "Iota"),
        _p("302000007", "배가나정", "Kappa"),         # "배가"(잡음)가 접두로 걸리는 제품
    ],
    "eyak": [], "detail": [], "dur_ingr": [], "ingr_codes": {},
}

PROMPT = "가짜 프롬프트"  # 프롬프트 파일을 읽지 않게 주입한다(감사 훅 시험에서 파일 읽기와 섞이지 않게)


@pytest.fixture(scope="module")
def dd() -> DrugDict:
    return DrugDict(build_dictionary([], [], SNAPS, {"x": "y"})[0])


def _out(**kw: Any) -> dict:
    base = {"drug_mentions": [], "conditions": [], "age_years": None, "pregnancy": "unknown", "intent": ["contraindication"], "needed_claims": []}
    return {**base, **kw}


class FakeModel:
    def __init__(self, out: Any):
        self.out = out
        self.calls: list[list[dict[str, str]]] = []

    def __call__(self, messages: list[dict[str, str]]) -> Any:
        self.calls.append(messages)
        return self.out


def run(q: str, dd: DrugDict, profile: Any = None, **out: Any) -> C.ClassifyOutcome:
    return C.route_with_classifier(q, dd, profile, call=FakeModel(_out(**out)), enabled=True, prompt=PROMPT)


ALL_CONFLICTS = {v for k, v in vars(C).items() if k.startswith("CONFLICT_")}


# =========================================================================== 1. 병합 규칙 한눈에 보기

class TestMergePolicy:
    def test_policy_covers_every_schema_field(self):
        assert set(C.MERGE_POLICY) == set(C.RouterClassification.model_fields)

    def test_conflict_codes_are_unique_upper_snake(self):
        names = [v for k, v in vars(C).items() if k.startswith("CONFLICT_")]
        assert len(names) == len(set(names)) and all(n.replace("_", "").isupper() for n in names)

    def test_no_conflict_when_model_agrees(self, dd):
        o = run("가온정이랑 솔솔 같이 먹어도 되나요", dd, drug_mentions=["가온정", "솔솔"])
        assert o.used and o.conflicts == [] and o.removed == [] and o.added == []
        assert o.result == route_input("가온정이랑 솔솔 같이 먹어도 되나요", dd)


# =========================================================================== 2. 엔티티 충돌

class TestEntityConflicts:
    def test_resolved_kept_with_code(self, dd):
        o = run("가온정 먹어도 되나요", dd, drug_mentions=[])
        assert [e.raw for e in o.result.entities] == ["가온정"] and C.CONFLICT_RESOLVED_KEPT in o.conflicts

    def test_exact_named_ambiguous_is_kept(self, dd):
        rule = route_input("누리정 먹어도 되나요", dd)
        (e,) = rule.entities
        assert e.status == R.ST_AMBIGUOUS and e.match_type in (MATCH_EXACT, MATCH_NORMALIZED)  # 같은 이름 제품 2개
        o = run("누리정 먹어도 되나요", dd, drug_mentions=[])
        assert o.result.ambiguous and o.removed == [] and C.CONFLICT_NAMED_AMBIGUOUS_KEPT in o.conflicts

    def test_prefix_noise_is_removed(self, dd):
        q = "배가 아픈데 가온정 먹어도 되나요"   # "배가" → 접두 일치(배가나정) 모호: 규칙은 되묻는다
        rule = route_input(q, dd)
        assert rule.ambiguous and rule.clarify.target_raw == "배가"
        o = run(q, dd, drug_mentions=["가온정"], conditions=["배가 아픈"])
        assert "배가" in o.removed and not o.result.ambiguous and C.CONFLICT_UNRESOLVED_REMOVED in o.conflicts
        assert [e.raw for e in o.result.entities] == ["가온정"] and o.result.branch_label == R.BRANCH_NORMAL

    def test_prefix_drug_named_by_model_keeps_clarify(self, dd):
        o = run("보라랑 가온정 같이 먹어도 되나요", dd, drug_mentions=["보라", "가온정"])
        assert o.result.ambiguous and o.result.clarify.target_raw == "보라" and o.removed == []

    def test_unresolvable_model_mention_is_not_added(self, dd):
        o = run("가온정이랑 보라정 같이 먹어도 되나요", dd, drug_mentions=["가온정", "보라정"])
        assert "보라정" in [e.raw for e in o.result.entities]  # 규칙이 이미 뽑은 것은 그대로
        o2 = run("가온정 먹고 보라 계열도 먹어도 되나요", dd, drug_mentions=["가온정", "보라 계열"])
        assert all(e.raw != "보라 계열" for e in o2.result.entities)
        assert C.CONFLICT_MENTION_NOT_RESOLVED in o2.conflicts and o2.added == []

    def test_model_naming_the_noise_word_keeps_it(self, dd):
        """LLM이 그 낱말을 약으로 보면(부분 일치 포함) 규칙 엔티티를 남긴다: 빼는 쪽은 LLM이 약으로 보지 않았을 때뿐이다."""
        o = run("배가 아픈데 가온정 먹어도 되나요", dd, drug_mentions=["가온정", "배가"])
        assert "배가" in [e.raw for e in o.result.entities] and o.result.ambiguous


# =========================================================================== 3. 연령·임신 충돌

class TestProfileConflicts:
    def test_rule_age_wins(self, dd):
        o = run("37살인데 가온정 먹어도 되나요", dd, drug_mentions=["가온정"], age_years=40)
        assert o.result.profile.age_years == 37 and C.CONFLICT_AGE_RULE_KEPT in o.conflicts

    def test_age_without_cue_is_dropped(self, dd):
        o = run("할머니가 가온정 드셔도 되는지 알려 주세요", dd, drug_mentions=["가온정"], age_years=75)
        assert o.result.profile.age_years is None and C.CONFLICT_AGE_NO_CUE in o.conflicts

    @pytest.mark.parametrize("q,age", [("70대 어머니가 가온정 먹어도 되나요", 70), ("다섯 살 아이가 가온정 먹어도 되나요", 5),
                                       ("칠십대 아버지 가온정 먹어도 되나요", 70)])
    def test_age_with_cue_fills_when_rule_missed(self, dd, q, age):
        assert route_input(q, dd).profile.age_years is None
        o = run(q, dd, drug_mentions=["가온정"], age_years=age)
        assert o.result.profile.age_years == age and o.result.profile.source == "question"

    def test_question_age_from_model_beats_profile(self, dd):
        prof = {"age_years": 40, "pregnant": None, "source": "profile"}
        o = run("70대 어머니가 가온정 먹어도 되나요", dd, prof, drug_mentions=["가온정"], age_years=70)
        assert o.result.profile.age_years == 70 and C.CONFLICT_AGE_OVER_PROFILE in o.conflicts

    def test_polite_ending_se_is_not_an_age_cue(self):
        assert not C._AGE_CUE_RE.search("가온정 드시지 마세요. 확인하세요")
        assert C._AGE_CUE_RE.search("3세 아이") and C._AGE_CUE_RE.search("18개월 아기")

    def test_rule_pregnancy_wins(self, dd):
        o = run("임신 중인데 가온정 먹어도 되나요", dd, drug_mentions=["가온정"], pregnancy="no")
        assert o.result.profile.pregnant is True and C.CONFLICT_PREG_RULE_KEPT in o.conflicts

    def test_model_no_is_ignored(self, dd):
        o = run("가온정 먹어도 되나요", dd, drug_mentions=["가온정"], pregnancy="no")
        assert o.result.profile.pregnant is None and C.CONFLICT_PREG_NO_IGNORED in o.conflicts
        prof = {"age_years": None, "pregnant": True, "source": "profile"}
        o2 = run("가온정 먹어도 되나요", dd, prof, drug_mentions=["가온정"], pregnancy="no")
        assert o2.result.profile.pregnant is True and o2.result.profile.source == "profile"

    def test_model_yes_is_used_even_over_profile_no(self, dd):
        prof = {"age_years": None, "pregnant": False, "source": "profile"}
        o = run("배 속 아기가 있는데 가온정 먹어도 되나요", dd, prof, drug_mentions=["가온정"], pregnancy="yes")
        assert o.result.profile.pregnant is True and o.result.profile.source == "question"

    def test_possible_is_recorded_not_written(self, dd):
        o = run("가온정 먹어도 되나요", dd, drug_mentions=["가온정"], pregnancy="possible")
        assert o.result.profile.pregnant is None and C.CONFLICT_PREG_POSSIBLE in o.conflicts

    def test_profile_object_is_not_mutated(self, dd):
        prof = {"age_years": 40, "pregnant": False, "source": "profile"}
        before = dict(prof)
        run("70대 어머니가 임신은 아니고 가온정 먹어도 되나요", dd, prof, drug_mentions=["가온정"], age_years=70, pregnancy="yes")
        assert prof == before


# =========================================================================== 4. 유형 라벨·주장 유형 충돌

class TestIntentConflicts:
    def test_rule_label_is_kept(self, dd):
        q = "가온정이랑 솔솔 같이 먹어도 되나요"
        o = run(q, dd, drug_mentions=["가온정", "솔솔"], intent=["drug_info"])
        assert R.INTENT_CONTRA in o.result.intent and R.INTENT_DRUG_INFO in o.result.intent
        assert C.CONFLICT_INTENT_RULE_KEPT in o.conflicts

    def test_open_from_model_dropped_when_drug_present(self, dd):
        o = run("가온정 먹어도 되나요", dd, drug_mentions=["가온정"], intent=["open"])
        assert R.INTENT_OPEN not in o.result.intent and C.CONFLICT_OPEN_DROPPED in o.conflicts

    def test_open_kept_without_drug(self, dd):
        q = "임신 중에 피해야 할 진통제가 뭐예요"
        o = run(q, dd, intent=["open", "contraindication"])
        assert R.INTENT_OPEN in o.result.intent and o.result.entities == []

    def test_out_of_scope_only_label_keeps_rule_labels(self, dd):
        o = run("가온정 몇 알 먹어야 해요", dd, drug_mentions=["가온정"], intent=["out_of_scope"])
        assert o.result.intent and C.INTENT_OUT_OF_SCOPE not in o.result.intent and o.scope_hint
        assert C.INTENT_OUT_OF_SCOPE not in json.dumps(o.result.state_update(), ensure_ascii=False)

    def test_claims_union_keeps_code_rule_claims(self, dd):
        q = "가온정이랑 솔솔 같이 먹어도 되나요 용어도 알려 주세요"
        rule = route_input(q, dd)
        o = run(q, dd, drug_mentions=["가온정", "솔솔"], needed_claims=["term_procedure"])
        assert set(rule.required_claims) <= set(o.result.required_claims) and R.CLAIM_TERM_PROCEDURE in o.result.required_claims
        assert o.result.required_claims == [c for c in R.CLAIM_TYPES if c in o.result.required_claims]  # 설계 문서 순서


# =========================================================================== 5. 모호 되묻기 물음표 문구(AG-05-10 A 승인, AG-13-07 A로 켬)

def _q_count(s: str) -> int:
    return s.count("?")  # `evaluation/eval_metrics.py` element_checks의 ONE_QUESTION과 같은 정의


class TestManyCandidatesPhrase:
    def test_approved_phrase_lives_in_fixed_phrases_without_switch(self):
        """AG-05-10 A(원문 승인)·AG-13-07 A(켜기): 원본은 `fixed_phrases`이고 router는 참조만 한다. 승인 스위치는 지웠다."""
        assert fp.CLARIFY_MANY_CANDIDATES == "'{drug}'에 해당하는 약이 여러 개예요. 어떤 약을 말씀하시는 건가요?"
        assert R.CLARIFY_MANY_CANDIDATES is fp.CLARIFY_MANY_CANDIDATES
        assert not hasattr(R, "CLARIFY_MANY_CANDIDATES_APPROVED") and "CLARIFY_MANY_CANDIDATES" not in fp.DRAFT_KEYS

    def test_many_candidates_use_phrase_with_one_question_mark(self, dd):
        c = route_input("보라를 먹어도 되나요", dd).clarify
        assert c.question == fp.CLARIFY_MANY_CANDIDATES.format(drug="보라") and _q_count(c.question) == 1
        assert len(c.options) == 2 and c.pending_raws == []
        assert "어떤 약인지 하나를 골라 주세요" not in c.question   # 이전 문장(물음표 없음)은 더 나오지 않는다

    def test_phrase_has_no_verdict_dose_or_safety(self):
        s = fp.CLARIFY_MANY_CANDIDATES
        for bad in ("먹어도", "괜찮", "안전", "금기", "mg", "밀리그램", "알", "복용하세요"):
            assert bad not in s
        assert _q_count(s) == 1 and "{drug}" in s
        assert not any(term in s for term in fp.FORBIDDEN_SCREEN_TERMS)

    def test_all_templates_have_one_question_mark(self, dd):
        for q in ("보라를 먹어도 되나요", "누리정 먹어도 되나요", "배가 먹어도 되나요"):
            c = route_input(q, dd).clarify
            assert c is not None and _q_count(c.question) == 1, q
            assert len(c.options) <= R.MAX_CLARIFY_OPTIONS

    def test_one_target_per_turn(self, dd):
        c = route_input("보라를 누리정이랑 같이 먹어도 되나요", dd).clarify
        assert c.target_raw == "보라" and c.pending_raws == ["누리정"]


# =========================================================================== 6. 분류기 경로의 비저장·비로깅(AG-05 §2 37·38줄의 남은 확인 가능 부분)

_AUDIT_PREFIXES = ("open", "os.", "socket.", "sqlite3.", "subprocess.", "shutil.", "urllib.", "http.")
_audit_log: list[str] = []
_audit_on = False


def _hook(event: str, args: tuple[Any, ...]) -> None:
    if _audit_on and event.startswith(_AUDIT_PREFIXES):
        _audit_log.append(event)


sys.addaudithook(_hook)  # 지울 수 없어 `_audit_on`으로 창을 연다


def _io_events(fn) -> list[str]:
    global _audit_on
    _audit_log.clear()
    _audit_on = True
    try:
        fn()
    finally:
        _audit_on = False
    return list(_audit_log)


Q_PRIVATE = "37살 임신 중인데 가온정이랑 솔솔 같이 먹어도 되나요"
SECRETS = ("37", "임신", "가온정", "솔솔", Q_PRIVATE)


class TestClassifierPathPrivacy:
    def _go(self, dd: DrugDict, profile: Any = None) -> C.ClassifyOutcome:
        return run(Q_PRIVATE, dd, profile, drug_mentions=["가온정", "솔솔"], age_years=40, pregnancy="no", intent=["out_of_scope"])

    def test_audit_hook_is_live(self, tmp_path):
        assert "open" in _io_events(lambda: (tmp_path / "p.txt").write_text("x", encoding="utf-8"))

    @pytest.mark.parametrize("profile", [None, {"age_years": 70, "pregnant": False, "source": "profile"}], ids=["guest", "profile"])
    def test_no_file_socket_db_access(self, dd, profile, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        self._go(dd, profile)  # 지연 import 먼저
        assert _io_events(lambda: self._go(dd, profile).result.state_update()) == []
        assert list(tmp_path.iterdir()) == []

    def test_no_log_records_and_no_stdout(self, dd, caplog, capsys):
        with caplog.at_level(logging.DEBUG):
            self._go(dd)
        assert caplog.records == []
        out = capsys.readouterr()
        assert out.out == "" and out.err == ""

    def test_conflict_codes_carry_no_question_values(self, dd):
        o = self._go(dd)
        assert o.conflicts and set(o.conflicts) <= ALL_CONFLICTS
        blob = json.dumps(o.conflicts, ensure_ascii=False)
        assert not any(s in blob for s in SECRETS)

    def test_summary_carries_no_question_or_names(self, dd):
        rows = [{"id": "dev-x", "question": Q_PRIVATE, "products": ["가온정", "솔솔"], "composition_group": "정상"}]
        outs = [self._go(dd)]
        s = json.dumps(C.summarize(rows, outs, [route_input(Q_PRIVATE, dd)]), ensure_ascii=False)
        assert not any(x in s for x in SECRETS)

    def test_module_io_only_in_cli_and_call_factory(self):
        """`main`(CLI, 사용자 승인 뒤 실행)·`make_openai_call`(만들기만 함)·`load_prompt`(프롬프트 읽기) 밖에서는 print·파일 쓰기·로거가 없다."""
        tree = ast.parse(Path(C.__file__).read_text(encoding="utf-8"))
        allowed = {"main", "make_openai_call", "load_prompt"}
        bad_calls = {"print", "open"}
        bad_attrs = {"write_text", "write_bytes", "getLogger", "info", "debug", "warning", "error", "exception", "connect", "urlopen"}
        for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name not in allowed]:
            for node in ast.walk(fn):
                if isinstance(node, ast.Call):
                    f = node.func
                    assert not (isinstance(f, ast.Name) and f.id in bad_calls), (fn.name, f.id)
                    assert not (isinstance(f, ast.Attribute) and f.attr in bad_attrs), (fn.name, f.attr)
        assert "logging" not in Path(C.__file__).read_text(encoding="utf-8")


# =========================================================================== 7. 실측 판정 기준(측정 전 고정, CLI 요약)

class TestSummaryJudgment:
    def test_better_and_worse_are_counted(self, dd):
        rows = [
            {"id": "dev-a", "question": "배가 아픈데 가온정 먹어도 되나요", "products": ["가온정"], "composition_group": "정상"},
            {"id": "dev-b", "question": "보라를 먹어도 되나요", "products": ["보라"], "composition_group": "모호"},
        ]
        rules = [route_input(r["question"], dd) for r in rows]
        better = run(rows[0]["question"], dd, drug_mentions=["가온정"])               # 잡음 "배가" 제거 → 개선
        same = run(rows[1]["question"], dd, drug_mentions=["보라"])                     # 그대로
        s = C.summarize(rows, [better, same], rules)
        assert s["items_better"] == [1, 2] and s["items_worse"] == [0, 2] and s["worse_ids"] == []

    def test_lost_clarify_on_ambiguous_item_is_worse(self, dd):
        rows = [{"id": "dev-c", "question": "보라를 먹어도 되나요", "products": [], "composition_group": "모호"}]
        rules = [route_input(rows[0]["question"], dd)]
        lost = run(rows[0]["question"], dd, drug_mentions=[])  # 접두 일치 모호는 LLM이 안 보면 빠진다 → 되묻기 사라짐
        s = C.summarize(rows, [lost], rules)
        assert s["items_worse"] == [1, 1] and s["worse_ids"] == ["dev-c"]
