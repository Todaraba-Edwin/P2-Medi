"""`identify_drug`: 약 이름 → 후보 최대 5개(품목기준코드·제품명·제형·성분 목록·일반/전문), 못 찾으면 "없음 + 다시 쓸 이름".

사전(`DrugDict.lookup_name`)만 쓰고 판정하지 않는다. 성분명 일치는 제품 필드를 비우고 `NO_PRODUCT_INFO`(H17),
전문의약품은 `EASY_TEXT_MISSING`(H18), 원문 미확보는 `missing_reason`(H26·H29)을 단다. 상태는 `FOUND`·`UNIDENTIFIED`뿐이다.
"""

from __future__ import annotations

from typing import Any

from app.agent.tools.context import ToolContext
from app.agent.tools.contract import known_ids
from app.agent.tools.schemas import IdentifyDrugArgs
from app.tools import drug_form as DF
from app.tools.drug_dict import MATCHED_BY_INGREDIENT, Candidate
from app.tools.provenance import PUBLISHER, SK_FILE, SOURCE_PRMSN

TOOL = "identify_drug"
MAX_CANDIDATES = 5
RETRY_HINT = "제품명 전체(예: 약 봉투·상자에 적힌 이름)나 성분명으로 다시 알려 주세요"
SOURCE_PRODUCT = SOURCE_PRMSN
SOURCE_INGREDIENT = PUBLISHER["kids"]
SEARCHED = (SOURCE_PRMSN, f"{PUBLISHER['kids']} KIDS 코드")


def _as_of(ctx: ToolContext) -> str:
    built = str(ctx.drug_dict.meta.get("built_at") or "")
    return built[:10] or "2026-07-21"


def _label_state(ctx: ToolContext, c: Candidate) -> dict[str, Any]:
    """e약은요·허가 상세가 있는지 본다. 공급자가 없으면 일반/전문 구분으로만 정한다."""
    flags: list[str] = []
    out: dict[str, Any] = {"label_source": None, "missing_reason": None}
    if ctx.label_provider is None:
        if c.prescription == "전문":
            flags.append("EASY_TEXT_MISSING")
            out["label_source"] = "허가정보 상세"
        out["flags"] = flags
        return out
    try:
        easy = ctx.label_provider.eyak(c.item_seq or "")
        detail = ctx.label_provider.prmsn_detail(c.item_seq or "")
    except Exception:  # noqa: BLE001 - 공급자 실패는 FETCH_FAIL로 알린다(예외를 그래프로 올리지 않는다)
        out["missing_reason"] = "FETCH_FAIL"
        out["flags"] = flags
        return out
    if easy is not None:
        out["label_source"] = "e약은요"
    elif detail is not None:
        flags.append("EASY_TEXT_MISSING")  # 허가 상세 원문만 쓴다. 미확보가 아니다(PRD-08-05 A)
        out["label_source"] = "허가정보 상세"
    else:
        flags.append("EASY_TEXT_MISSING")
        out["missing_reason"] = "OUT_OF_SCOPE"
    out["flags"] = flags
    return out


def _candidate_item(ctx: ToolContext, query: str, c: Candidate) -> dict[str, Any]:
    ingredients = [
        {"name_en": i.name_en, "name_ko": i.name_ko, "display": i.display, "raw": i.raw, "salt": i.salt} for i in c.ingredients
    ]
    base: dict[str, Any] = {
        "kind": "identify", "status": "FOUND", "subject": [query], "matched_by": c.matched_by, "match_type": c.match_type,
        "name": c.name, "score": c.score, "prescription": c.prescription, "ingredients": ingredients,
        "kids_codes": list(c.kids_codes), "api_codes": list(c.api_codes), "code_status": c.code_status,
        "cancelled": c.cancelled, "note": c.note, "as_of": _as_of(ctx), "queried_at_utc": None,
        "source_kind": SK_FILE, "dataset_key": "identify", "dict_version": ctx.drug_dict.version,
        "item_seq": None, "entp_name": None, "form": None, "product_age_text": None, "label": None,
        "label_source": None, "missing_reason": None,
    }
    if c.matched_by == MATCHED_BY_INGREDIENT:  # H17: 성분 단위라 제품 필드를 비운다
        key = ingredients[0]["display"] if ingredients else c.name
        base.update(evidence_id=f"identify:ingredient:{key}", source=SOURCE_INGREDIENT, flags=["NO_PRODUCT_INFO"])
        return base
    p = ctx.drug_dict.products[ctx.drug_dict._by_seq[c.item_seq]] if c.item_seq in ctx.drug_dict._by_seq else {}
    label = _label_state(ctx, c)
    base.update(
        evidence_id=f"identify:{c.item_seq}", source=SOURCE_PRODUCT, item_seq=c.item_seq, entp_name=c.entp_name,
        form=DF.label(p.get("form")) if p.get("form") else None,
        flags=label.pop("flags"), **label,
    )
    return base


def _unidentified(ctx: ToolContext, query: str, normalized: str, notes: tuple[str, ...]) -> dict[str, Any]:
    return {
        "kind": "identify", "status": "UNIDENTIFIED", "subject": [query], "evidence_id": f"identify:{normalized or 'empty'}",
        "source": None, "as_of": None, "queried_at_utc": None, "flags": [], "matches": [], "dataset_key": None,
        "source_kind": None, "input_name": query, "searched": [{"dataset": s, "count": 0} for s in SEARCHED], "retried": False,
        "retry_hint": RETRY_HINT, "notes": list(notes),
    }


def identify_drug(args: IdentifyDrugArgs, ctx: ToolContext) -> dict[str, Any]:
    res = ctx.drug_dict.lookup_name(args.name, top_k=MAX_CANDIDATES)
    if res.empty:
        items = [_unidentified(ctx, args.name, res.normalized_query, res.notes)]
        return {"items": items, "resolved": False, "needs_clarification": False, "known_ids": sorted(known_ids(items))}
    items = [_candidate_item(ctx, args.name, c) for c in res.candidates[:MAX_CANDIDATES]]
    return {
        "items": items, "resolved": res.resolved, "needs_clarification": res.needs_clarification,
        "total_candidates": res.total_candidates, "notes": list(res.notes), "known_ids": sorted(known_ids(items)),
    }
