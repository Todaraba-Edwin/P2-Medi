"""시작 화면 안내 상수(FE-01-24 A, 2026-11-16 초안. 외부 AI 고지는 PRD-17-10 A로 삭제)와 `NO_PRODUCT_INFO` 글자 정정(Recap 19②) 시험. LLM·외부 호출 없음.

- 시작 화면 문구는 백엔드 상수이고 프런트는 `frontend/scripts/gen-fixed-phrases.mjs`가 이 파일에서 생성한 값만 쓴다(FE-01-19 A).
  생성기는 `^NAME\\s*=\\s*"..."` 한 줄 글자만 읽으므로 그 모양을 여기서도 고정한다.
- 외부 AI 전송 고지: 시작 화면 상수 `START_EXTERNAL_AI_NOTICE`는 PRD-17-10 A(2026-11-20)로 삭제했다. 같은 고지는 입력창 아래
  고지 하나(프런트 `features/chat/copy.ts` INPUT_NOTICE, PRD-17-07 A)만 둔다. 상수가 되살아나지 않게 여기서 막는다.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.agent import fixed_phrases as fp
from app.tools.provenance import FLAG_NOTES

FP_SOURCE = Path(fp.__file__)
START_KEYS = ("START_EMERGENCY_119",)
REMOVED_START_KEYS = ("START_EXTERNAL_AI_NOTICE",)  # PRD-17-10 A 삭제


def _js_generator_constant(text: str, name: str) -> str | None:
    """`gen-fixed-phrases.mjs`의 `constant()` 정규식과 같은 규칙(줄 처음, 큰따옴표 한 줄 글자)."""
    m = re.search(rf'^{name}\s*=\s*"((?:[^"\\]|\\.)*)"', text, re.MULTILINE)
    return m.group(1) if m else None


# --------------------------------------------------------------------------- 글자 일치
def test_start_emergency_119_text_exact():
    assert fp.START_EMERGENCY_119 == "응급 상황이면 지금 바로 119에 전화하세요."


def test_start_external_ai_notice_removed_prd17_10():
    """PRD-17-10 A: 시작 화면 외부 AI 고지 상수는 없다(입력창 고지 하나). 원본 파일에도 생성기가 읽을 줄이 없다."""
    src = FP_SOURCE.read_text(encoding="utf-8")
    for k in REMOVED_START_KEYS:
        assert not hasattr(fp, k), k
        assert _js_generator_constant(src, k) is None, k
    # 시작 화면 상수 어디에도 외부 AI 전송 문장이 없다(같은 고지 두 번 노출 금지)
    for k in START_KEYS:
        assert "외부 AI" not in getattr(fp, k), k
        assert "OpenAI" not in getattr(fp, k), k


# --------------------------------------------------------------------------- 승인 표시(2026-11-16 문구 승인 1·2번)
def test_start_constants_are_approved():
    for k in START_KEYS:
        assert k not in fp.DRAFT_KEYS, k
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
