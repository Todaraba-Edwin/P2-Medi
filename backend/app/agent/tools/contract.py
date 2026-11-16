"""도구 출력 계약 검사(PostToolUse 1~6번의 오프라인 판, H1·H2·H8·H17·H18·H20)와 데이터 블록 렌더.

판정은 바꾸지 않는다. 계약 위반 목록만 돌려준다. 개선 단계의 `harnessed_tools`가 같은 함수를 실행 중에 쓴다.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.agent.tools.schemas import API_FLAGS, MISSING_REASONS, STATUS_BY_TOOL

DATA_OPEN = "<<<TOOL_DATA"
DATA_CLOSE = "TOOL_DATA>>>"
_DELIM_RE = re.compile(r"<<<\s*TOOL_DATA|TOOL_DATA\s*>>>")
PRODUCT_FIELDS = ("product_age_text", "label", "form")  # 성분명 일치 항목에서 비어 있어야 하는 제품 필드(H17)


def render_data_block(tool: str, items: list[dict[str, Any]]) -> str:
    """결과를 데이터 블록으로 감싼다. 본문 안의 구분자 모양은 제거해 블록 탈출을 막는다(H8, NFR-09)."""
    body = json.dumps({"items": items}, ensure_ascii=False)
    body = _DELIM_RE.sub("[삭제됨]", body)
    return f"{DATA_OPEN} tool={tool}\n{body}\n{DATA_CLOSE}"


def check_items(tool: str, items: list[dict[str, Any]]) -> list[str]:
    """계약 위반 문자열 목록. 비어 있으면 통과."""
    bad: list[str] = []
    allowed = STATUS_BY_TOOL[tool]
    for n, it in enumerate(items):
        tag = f"[{n}:{it.get('evidence_id')}]"
        st = it.get("status")
        if st not in allowed:
            bad.append(f"{tag} 상태 {st} 는 {tool}에서 쓸 수 없다")
        if not it.get("evidence_id"):
            bad.append(f"{tag} evidence_id 없음")
        if st in ("FOUND", "NOT_LISTED"):  # 조회한 결과만 출처·기준일(또는 조회 시각)을 단다(UNIDENTIFIED는 BE-09-04 A)
            if not it.get("source"):
                bad.append(f"{tag} source 없음")
            if not (it.get("as_of") or it.get("queried_at_utc")):
                bad.append(f"{tag} 기준일·조회 시각 없음")
            if not it.get("source_kind"):
                bad.append(f"{tag} source_kind 없음")
        if "flags" not in it or not isinstance(it["flags"], list):
            bad.append(f"{tag} flags 목록 없음")
        flags = it.get("flags") or []
        if it.get("matched_by") == "ingredient_name":  # H17
            if "NO_PRODUCT_INFO" not in flags:
                bad.append(f"{tag} 성분명 일치인데 NO_PRODUCT_INFO 없음")
            if any(it.get(f) for f in PRODUCT_FIELDS):
                bad.append(f"{tag} 성분명 일치인데 제품 필드가 비어 있지 않다")
        if it.get("is_label") and st == "FOUND" and it.get("easy_text") is None and "EASY_TEXT_MISSING" in flags and it.get("label_source") != "허가정보 상세":
            bad.append(f"{tag} EASY_TEXT_MISSING인데 라벨 출처가 허가정보 상세가 아니다")  # H18
        api = [f for f in flags if f in API_FLAGS]
        if len(api) > 1:
            bad.append(f"{tag} API 꼬리표가 둘 이상: {api}")
        if "API_PAIR_INCOMPLETE" in api and it.get("kind") != "contra_pair":
            bad.append(f"{tag} API_PAIR_INCOMPLETE는 병용 쌍 항목에만 쓴다(성분 단위 연령·임부는 API_FAIL)")  # H20
        if isinstance(it.get("api"), dict) and it["api"].get("codes_truncated") and {"FILE_ONLY", "API_SAME"} & set(api):
            want = "API_PAIR_INCOMPLETE" if it.get("kind") == "contra_pair" else "API_FAIL"  # 쌍: AG-01-04 A, 성분 단위 연령·임부: AG-01-09 A
            bad.append(f"{tag} API 성분 코드가 한도로 잘렸는데 FILE_ONLY·API_SAME이 붙었다({want}여야 한다)")
        if it.get("source_kind") == "API_DIRECT" and it.get("dataset_key") == "dur_ingr" and not it.get("queried_at_utc"):
            bad.append(f"{tag} API 항목에 조회 시각 없음")
        if it.get("missing_reason") is not None and it["missing_reason"] not in MISSING_REASONS:
            bad.append(f"{tag} missing_reason 값 이상: {it['missing_reason']}")
        if it.get("missing_reason") and (it.get("text") or it.get("matches")):
            bad.append(f"{tag} 값이 있는데 missing_reason이 있다")  # H26: 값이 있으면 비움
    return bad


def known_ids(items: list[dict[str, Any]]) -> set[str]:
    """`known_ids` 갱신용: 항목·행 근거 ID, 후보의 품목기준코드·성분코드(두 체계)."""
    ids: set[str] = set()
    for it in items:
        if it.get("evidence_id"):
            ids.add(it["evidence_id"])
        for m in it.get("matches") or []:
            if m.get("row_evidence_id"):
                ids.add(m["row_evidence_id"])
        if it.get("item_seq"):
            ids.add(it["item_seq"])
        for c in (it.get("kids_codes") or []) + (it.get("api_codes") or []):
            ids.add(c)
    return ids
