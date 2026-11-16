"""시작 화면 안내 상수 2종(FE-01-24 A, 2026-11-16 초안)과 `NO_PRODUCT_INFO` 글자 정정(Recap 19②) 시험. LLM·외부 호출 없음.

- 시작 화면 문구는 백엔드 상수이고 프런트는 `frontend/scripts/gen-fixed-phrases.mjs`가 이 파일에서 생성한 값만 쓴다(FE-01-19 A).
  생성기는 `^NAME\\s*=\\s*"..."` 한 줄 글자만 읽으므로 그 모양을 여기서도 고정한다.
- 외부 AI 전송 고지 요소: PJ2-RFP.md 7장 고지 항목(RFP-24-01, PRD-07-02)·`tickets/frontend/FE-02.md` §2.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.agent import fixed_phrases as fp
from app.tools.provenance import FLAG_NOTES

FP_SOURCE = Path(fp.__file__)
START_KEYS = ("START_EMERGENCY_119", "START_EXTERNAL_AI_NOTICE")


def _js_generator_constant(text: str, name: str) -> str | None:
    """`gen-fixed-phrases.mjs`의 `constant()` 정규식과 같은 규칙(줄 처음, 큰따옴표 한 줄 글자)."""
    m = re.search(rf'^{name}\s*=\s*"((?:[^"\\]|\\.)*)"', text, re.MULTILINE)
    return m.group(1) if m else None


# --------------------------------------------------------------------------- 글자 일치
def test_start_emergency_119_text_exact():
    assert fp.START_EMERGENCY_119 == "응급 상황이면 지금 바로 119에 전화하세요."


def test_start_external_ai_notice_text_exact():
    assert fp.START_EXTERNAL_AI_NOTICE == (
        "질문과 입력한 프로필은 답을 만들기 위해 외부 AI(OpenAI)로 보내요. "
        "이 서비스는 질문 내용을 저장하지 않지만, 외부 AI 제공자의 정책에 따라 일정 기간 보관될 수 있어요."
    )


# --------------------------------------------------------------------------- 초안 표시
def test_start_constants_are_marked_draft():
    for k in START_KEYS:
        assert k in fp.DRAFT_KEYS, k
        assert hasattr(fp, k), k


# --------------------------------------------------------------------------- 금지어·내용 규칙
def test_start_constants_have_no_internal_terms():
    for k in START_KEYS:
        text = getattr(fp, k)
        for term in fp.FORBIDDEN_SCREEN_TERMS:
            assert term not in text, (k, term)


def test_start_emergency_uses_only_119_and_matches_approved_tone():
    text = fp.START_EMERGENCY_119
    assert re.findall(r"\d+", text) == ["119"]  # 119 외 연락처 금지(RFP-19-01 A)
    assert text.endswith("지금 바로 119에 전화하세요.")
    assert fp.EMERGENCY_119.endswith("지금 바로 119에 전화하세요.")  # 승인 문구와 같은 말투


def test_start_external_ai_notice_has_required_elements():
    text = fp.START_EXTERNAL_AI_NOTICE
    # PJ2-RFP.md 7장: 질문과 입력한 프로필 / 답변 생성을 위해 / 외부 AI 서비스로 전송 / 제공자 정책에 따라 일정 기간 보관될 수 있음
    for part in ("질문", "프로필", "외부 AI", "OpenAI", "제공자의 정책에 따라", "일정 기간 보관될 수 있어요"):
        assert part in text, part
    assert "질문 내용을 저장하지 않" in text  # CLAUDE.md 1장·PJ2-RFP.md 7장: 질문·대화 비저장


def test_start_external_ai_notice_does_not_assert_provider_policy():
    text = fp.START_EXTERNAL_AI_NOTICE
    # 학습 사용 여부·보관 기간·삭제는 단정하지 않는다(PJ2-RFP.md 7장, RFP-15 §8.1 일부 미확인)
    for word in ("학습", "30일", "삭제", "보관하지 않", "안전"):
        assert word not in text, word


# --------------------------------------------------------------------------- 프런트 생성기 호환
def test_start_constants_are_readable_by_frontend_generator():
    src = FP_SOURCE.read_text(encoding="utf-8")
    for k in START_KEYS:
        assert _js_generator_constant(src, k) == getattr(fp, k), k


# --------------------------------------------------------------------------- NO_PRODUCT_INFO 글자 정정
def test_no_product_info_flag_note_says_허가사항_not_허가라벨_recap19_2():
    """2026-11-16 사용자 결정 Recap 19②: `FLAG_NOTES["NO_PRODUCT_INFO"]` "허가 라벨"→"허가사항"(하네스 3.4절 표 글자)."""
    note = FLAG_NOTES["NO_PRODUCT_INFO"]
    assert "허가 라벨" not in note and "허가사항" in note
    assert note == fp.NO_PRODUCT_INFO  # 도구 꼬리표 안내와 화면 상수가 같은 글자
    assert not [t for t in fp.FORBIDDEN_SCREEN_TERMS if t in note]
