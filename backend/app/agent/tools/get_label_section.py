"""`get_label_section`: 품목기준코드 + 절 이름 → 허가 상세·e약은요의 해당 절 본문(길이 제한).

- 쉬운 설명(e약은요)이 있으면 그 절을 쓰고, 없으면(전문의약품) 허가 상세 원문만 쓴다(`EASY_TEXT_MISSING`, H18, 문장을 지어내지 않는다).
- 용법용량은 허가 상세 원문 그대로이며 근거 상세 인용용이다(RFP-21-03). 요약에 숫자를 쓰는 일은 이 도구 밖이다.
- 성분코드는 인자 스키마(품목기준코드 9자리)에서 막힌다(H17).
- 값이 있으면 `missing_reason`은 비운다. 없으면 `ABSENT`(그 절이 비어 있음)·`FETCH_FAIL`(공급자 실패)·`OUT_OF_SCOPE`(원문 없음, H26).
- 상태는 `FOUND`·`NO_EVIDENCE`뿐이다.
"""

from __future__ import annotations

from typing import Any

from app.agent.tools.context import ToolContext
from app.agent.tools.contract import known_ids
from app.agent.tools.label_source import EYAK_FIELDS, PRMSN_DOC_CODE, PRMSN_DOCS, extract_doc_text
from app.agent.tools.schemas import GetLabelSectionArgs
from app.tools.eyak import SOURCE_NAME as EYAK_SOURCE
from app.tools.provenance import SK_API_DIRECT, SOURCE_PRMSN

TOOL = "get_label_section"
MAX_SECTION_CHARS = 2000
PRMSN_SOURCE = SOURCE_PRMSN
LABEL_SOURCE_PRMSN = "허가정보 상세"
LABEL_SOURCE_EYAK = "e약은요"


def _truncate(text: str) -> tuple[str, bool]:
    return (text, False) if len(text) <= MAX_SECTION_CHARS else (text[:MAX_SECTION_CHARS], True)


def _item(*, item_seq: str, section: str, status: str, evidence_id: str, source: str | None, dataset_key: str | None,
          label_source: str | None, text: str | None, collected_at: str | None, snap: bool, flags: list[str],
          missing_reason: str | None, full_len: int = 0, truncated: bool = False, source_kind: str | None = None) -> dict[str, Any]:
    matches = []
    if text:
        matches = [{"row_key": section, "row_evidence_id": f"{evidence_id}#{section}", "text": text}]
    return {
        "kind": "label", "status": status, "subject": [item_seq, section], "evidence_id": evidence_id, "source": source,
        "as_of": None, "queried_at_utc": collected_at, "queried_at_kind": ("SNAPSHOT_COLLECTED" if snap else "FETCHED") if collected_at else None,
        "flags": flags, "matches": matches, "dataset_key": dataset_key, "source_kind": source_kind, "is_label": True,
        "item_seq": item_seq, "section": section, "label_source": label_source, "easy_text": text if label_source == LABEL_SOURCE_EYAK else None,
        "text": text, "text_length": full_len, "truncated": truncated, "missing_reason": missing_reason,
    }


def get_label_section(args: GetLabelSectionArgs, ctx: ToolContext) -> dict[str, Any]:
    seq, sec = args.item_seq, args.section
    miss_id = f"label:{seq}:{sec}"
    if ctx.label_provider is None:
        items = [_item(item_seq=seq, section=sec, status="NO_EVIDENCE", evidence_id=miss_id, source=None, dataset_key=None, label_source=None,
                       text=None, collected_at=None, snap=False, flags=[], missing_reason="OUT_OF_SCOPE")]
        return {"items": items, "known_ids": sorted(known_ids(items))}
    try:
        easy = ctx.label_provider.eyak(seq)
        detail = ctx.label_provider.prmsn_detail(seq)
    except Exception:  # noqa: BLE001 - 공급자 실패 내용은 싣지 않는다
        items = [_item(item_seq=seq, section=sec, status="NO_EVIDENCE", evidence_id=miss_id, source=None, dataset_key=None, label_source=None,
                       text=None, collected_at=None, snap=False, flags=[], missing_reason="FETCH_FAIL")]
        return {"items": items, "known_ids": sorted(known_ids(items))}

    flags: list[str] = [] if easy is not None else ["EASY_TEXT_MISSING"]
    candidates: list[tuple[str, dict[str, Any]]] = []  # (label_source, 공급 결과)
    # 용법용량은 허가 상세 원문이 우선이다. 나머지 절은 쉬운 설명(e약은요)이 우선이다.
    if sec == "용법용량":
        order = [(LABEL_SOURCE_PRMSN, detail), (LABEL_SOURCE_EYAK, easy)]
    else:
        order = [(LABEL_SOURCE_EYAK, easy), (LABEL_SOURCE_PRMSN, detail)]
    for name, got in order:
        if got is not None:
            candidates.append((name, got))

    for name, got in candidates:
        if name == LABEL_SOURCE_EYAK:
            field = EYAK_FIELDS.get(sec if sec != "용법용량" else "사용법")
            raw = (got["item"].get(field) or "") if field else ""
            text, eid, src, dsk = raw, f"eyak:{seq}:{field}", EYAK_SOURCE, "eyak"
        else:
            doc = PRMSN_DOCS.get(sec)
            raw = extract_doc_text(got["item"].get(doc)) if doc else ""
            text, eid, src, dsk = raw, f"prmsn:{seq}:{PRMSN_DOC_CODE.get(sec, sec)}", PRMSN_SOURCE, "prmsn"
        if text.strip():
            cut, trunc = _truncate(text)
            snap = got.get("source") == "snapshot"
            it = _item(item_seq=seq, section=sec, status="FOUND", evidence_id=eid, source=src, dataset_key=dsk, label_source=name, text=cut,
                       collected_at=got.get("collected_at"), snap=snap, flags=flags + (["SNAPSHOT_TIME"] if snap else []) + (["TRUNCATED"] if trunc else []),
                       missing_reason=None, full_len=len(text), truncated=trunc, source_kind=SK_API_DIRECT)
            return {"items": [it], "known_ids": sorted(known_ids([it]))}

    # 값이 없다. 어느 공급자도 이 품목을 모르면 범위 밖, 품목은 있는데 이 절만 비면 ABSENT.
    reason = "OUT_OF_SCOPE" if not candidates else "ABSENT"
    it = _item(item_seq=seq, section=sec, status="NO_EVIDENCE", evidence_id=miss_id, source=None, dataset_key=None, label_source=None, text=None,
               collected_at=None, snap=False, flags=flags, missing_reason=reason)
    return {"items": [it], "known_ids": sorted(known_ids([it]))}
