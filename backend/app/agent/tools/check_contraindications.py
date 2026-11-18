"""`check_contraindications`: 약 여러 개(+연령·임신) → 병용(모든 쌍)·임부·연령(·확장 주의·성분 중복) 항목.

판정은 BE-09 `lookup.py`(성분코드 정확 일치, 파일 1차)가 하고, DUR API 결과는 주입 함수로 받아 병기한다(교차 4경우 꼬리표).
- 코드 없음은 `NOT_LISTED`가 아니라 `UNIDENTIFIED` + `CODE_NOT_LINKED`(BE-10-06 A).
- 성분 단위 연결(`component_only`)은 제형이 맞은(`usable_for_judgment`) 코드만 판정에 쓰고 나머지는 참고 전용(BE-10-08·09 A).
- 항목 = 약 1개 / 쌍 1개 × 금기 종류. 도구 호출 1건에 상태 하나를 두지 않는다(H1·H2).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from itertools import combinations, product
from typing import Any

from app.agent.tools.context import ToolContext
from app.agent.tools.contract import known_ids
from app.agent.tools.schemas import (
    DUR_CODE_RE,
    FLAG_AMBIGUOUS_NAME,
    FLAG_CODE_NOT_LINKED,
    FLAG_REFERENCE_ONLY,
    KIDS_CODE_RE,
    CheckContraArgs,
    DrugArg,
)
from app.db.loaders import AS_OF_KIDS, SRC_KIDS, age_to_days
from app.tools import lookup
from app.tools.drug_dict import MATCHED_BY_INGREDIENT, Candidate
from app.tools.dur import SOURCE_INGR, DurResult, cross_check
from app.tools.lookup import FOUND, NOT_LISTED, UNIDENTIFIED, Age
from app.tools.provenance import (
    API_REASON_NO_CODE,
    API_REASON_PARTIAL,
    API_REASON_TRUNCATED,
    SK_API_DIRECT,
    SK_FILE,
    api_flag_note,
)

TOOL = "check_contraindications"
MAX_CODES_PER_DRUG = 40          # 성분 단위 입력(모든 제형 코드)의 조회 폭주 상한
MAX_API_CODES_PER_DRUG = 2       # 쌍당 API 호출 = 최대 4회
# AG-01-04 A·AG-01-09 A: 한 약의 API 성분 코드가 한도를 넘어 묻지 않은 성분이 있으면 "파일에만 있음"·"같음"을 말하지 않는다
# (병용 쌍은 API_PAIR_INCOMPLETE로, 성분 단위 연령·임부는 API_FAIL로 바꾼다)
_TRUNCATED_FORBIDDEN_FLAGS = ("FILE_ONLY", "API_SAME")
FLAG_LOOKUP_FAILED = "LOOKUP_FAILED"


@dataclass
class Drug:
    key: str                      # 근거 ID에 쓰는 약 키(품목기준코드·성분명·코드)
    label: str                    # 표시용: 사용자 입력 이름, 이름 없이 코드만 오면 사전 제품명(`_resolve`)
    ok: bool = False              # 판정에 쓸 코드가 있다
    kids_codes: list[str] = field(default_factory=list)
    api_codes: list[str] = field(default_factory=list)
    unit: str = "product"         # product | ingredient | code
    flags: list[str] = field(default_factory=list)   # 식별 못 했을 때의 사유 꼬리표
    notes: list[str] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)  # 되묻기 후보(최대 5)
    partial: bool = False         # 일부 성분만 판정 코드가 있다 → 못 찾은 것을 "목록에 없음"으로 말하지 않는다(BE-10-06)


# --------------------------------------------------------------------------- 식별

def _usable_codes(c: Candidate) -> list[str]:
    if c.matched_by == MATCHED_BY_INGREDIENT:
        return list(c.kids_codes)  # 성분 단위 입력은 성분코드를 그대로 판정한다(H17)
    if c.code_status == "linked":
        return list(c.usable_kids_codes) if c.form_match is not None else list(c.kids_codes)  # 성분 이름 연결 제품은 제형 맞는 코드만(BE-10-12)
    if c.code_status == "component_only":
        return list(c.usable_kids_codes)  # form_match=match 코드만(BE-10-08·09)
    return []


PARTIAL_NOTE = "이 제품의 일부 성분만 목록 조회에 쓸 수 있어 '목록에 없음'으로 말하지 않음(나머지 성분은 확인하지 못함)"


def _from_candidate(label: str, c: Candidate, n_components: int = 0) -> Drug:
    unit = "ingredient" if c.matched_by == MATCHED_BY_INGREDIENT else "product"
    key = c.item_seq or (c.ingredients[0].display if c.ingredients else c.name)
    d = Drug(key=str(key), label=label, unit=unit, api_codes=list(c.api_codes))
    codes = list(dict.fromkeys(_usable_codes(c)))[:MAX_CODES_PER_DRUG]
    if codes:
        d.ok, d.kids_codes = True, codes
        if c.code_status == "component_only":
            if c.note:
                d.notes.append(c.note)  # 일부 성분만 제형이 맞은 경우의 참고 노트
            usable = sum(1 for m in c.component_matches if m.usable_for_judgment)
            if usable < max(n_components, len(c.component_matches), 1):
                d.partial = True
                d.notes.append(PARTIAL_NOTE)
        return d
    d.flags.append(FLAG_CODE_NOT_LINKED)
    if c.code_status == "component_only" or c.form_match is not None:
        d.flags.append(FLAG_REFERENCE_ONLY)  # 다른 제형에서 목록에 있음, 이 제품 판정 아님
        if c.note:
            d.notes.append(c.note)
    return d


def _api_to_kids(ctx: ToolContext, code: str) -> list[str]:
    return [k for ing in ctx.drug_dict.ingredients if code in ing.get("api_codes", []) for k in ing.get("kids_codes", [])]


def _dict_product_name(ctx: ToolContext, item_seq: str | None) -> str | None:
    """품목기준코드의 사전 확정 제품명. 사전에 없거나 이름이 비면 None(지어내지 않는다)."""
    i = ctx.drug_dict._by_seq.get(item_seq or "")
    if i is None:
        return None
    name = str(ctx.drug_dict.products[i].get("name") or "").strip()
    return name or None


def _resolve(ctx: ToolContext, arg: DrugArg) -> Drug:
    # 표시명: 사용자가 적은 이름 > 품목기준코드의 사전 제품명 > 코드(AG-10-07 A, 이슈 F3). 이름 없이 코드만 오면(되묻기·보정으로 확정된 약)
    # 표시명 자리(`drugs`·`subject`·쌍 줄 머리·요약 입력 블록)에 코드가 나가지 않게 사전 이름을 쓴다. 근거 ID·`drug_keys`(`key`)는 그대로다.
    label = arg.name or _dict_product_name(ctx, arg.item_seq) or arg.item_seq or arg.ingredient_code or ""
    if arg.ingredient_code:
        code = arg.ingredient_code
        if KIDS_CODE_RE.match(code):
            return Drug(key=code, label=label, ok=True, kids_codes=[code], unit="code")
        kids = list(dict.fromkeys(_api_to_kids(ctx, code)))[:MAX_CODES_PER_DRUG]  # DUR API 코드 → KIDS 코드(사전)
        if kids:
            return Drug(key=code, label=label, ok=True, kids_codes=kids, api_codes=[code], unit="code")
        return Drug(key=code, label=label, unit="code", flags=[FLAG_CODE_NOT_LINKED], api_codes=[code])
    if arg.item_seq:
        i = ctx.drug_dict._by_seq.get(arg.item_seq)
        if i is None:
            return Drug(key=arg.item_seq, label=label, flags=[FLAG_CODE_NOT_LINKED])
        res = ctx.drug_dict.lookup_name(ctx.drug_dict.products[i]["name"], top_k=20)
        c = next((x for x in res.candidates if x.item_seq == arg.item_seq), None) or ctx.drug_dict._product_candidate(i, 1.0, "exact")
        return _from_candidate(label, c, len(ctx.drug_dict.products[i].get("ingr_keys", [])))
    res = ctx.drug_dict.lookup_name(arg.name or "", top_k=5)
    if res.empty:
        return Drug(key=label, label=label, flags=[])  # 약을 찾지 못함(UNIDENTIFIED, 되묻기 후보 없음)
    sigs = {(tuple(_usable_codes(c)), c.code_status, c.matched_by) for c in res.candidates}
    if res.match_type == "bm25" or (res.needs_clarification and not res.resolved and len(sigs) > 1):
        cands = [{"name": c.name, "item_seq": c.item_seq, "matched_by": c.matched_by, "prescription": c.prescription} for c in res.candidates]
        return Drug(key=label, label=label, flags=[FLAG_AMBIGUOUS_NAME], candidates=cands)
    c0 = res.candidates[0]
    i0 = ctx.drug_dict._by_seq.get(c0.item_seq or "")
    return _from_candidate(label, c0, len(ctx.drug_dict.products[i0].get("ingr_keys", [])) if i0 is not None else 0)


# --------------------------------------------------------------------------- 항목 만들기

def _extra(drugs: list[Drug], codes: list[str] | None = None, notes: list[str] | None = None) -> dict[str, Any]:
    return {
        "drugs": [d.label for d in drugs], "drug_keys": [d.key for d in drugs], "source_kind": SK_FILE, "queried_at_utc": None,
        "cause_codes": list(codes or []), "notes": list(dict.fromkeys(n for d in drugs for n in d.notes + (notes or []))),
        "unit": "ingredient" if any(d.unit == "ingredient" for d in drugs) else "product", "matched_by": None,
    }


def _merged(kind: str, results: list[lookup.Item], evidence_id: str, drugs: list[Drug]) -> list[dict[str, Any]]:
    """같은 약(쌍)의 코드별 조회를 한 묶음으로. FOUND는 코드 쌍마다 항목, 없으면 NOT_LISTED 하나."""
    found = [r for r in results if r.status == FOUND]
    if found:
        return [{**r.to_dict(), **_extra(drugs, list(r.subject))} for r in found]
    first = results[0]
    d = {**first.to_dict(), **_extra(drugs)}
    if len(results) > 1:
        d["evidence_id"] = evidence_id
        d["subject"] = [x.label for x in drugs]
    d["codes_checked"] = len(results)
    if any(x.partial for x in drugs):  # 일부 성분만 조회했다면 NOT_LISTED가 아니다(확인하지 못한 성분이 있다)
        d.update(status=UNIDENTIFIED, source=None, as_of=None, dataset_key=None, source_kind=None, flags=[*d["flags"], FLAG_CODE_NOT_LINKED])
    return [d]


def _unidentified_drug_item(d: Drug, kind: str) -> dict[str, Any]:
    return {
        "kind": kind, "status": UNIDENTIFIED, "subject": [d.label], "evidence_id": f"identify:{d.key}" if kind == "identify" else f"{kind}:{d.key}",
        "source": None, "as_of": None, "queried_at_utc": None, "flags": list(d.flags), "matches": [], "dataset_key": None,
        "source_kind": None, "input_name": d.label, "drugs": [d.label], "drug_keys": [d.key], "notes": list(d.notes),
        "candidates": list(d.candidates), "retried": False,
    }


def _pair_not_checked(a: Drug, b: Drug) -> dict[str, Any]:
    return {
        "kind": "contra_pair", "status": UNIDENTIFIED, "subject": [a.label, b.label], "evidence_id": f"contra_pair:{a.key}:{b.key}",
        "source": None, "as_of": None, "queried_at_utc": None, "flags": ["PAIR_NOT_CHECKED"], "matches": [], "dataset_key": None,
        "source_kind": None, "drugs": [a.label, b.label], "drug_keys": [a.key, b.key], "notes": [],
    }


# --------------------------------------------------------------------------- API 병기

def _api_failed() -> DurResult:
    return DurResult(ok=False, kind="usjnt", level="ingr", source_name=SOURCE_INGR, error=None)


def _api_call(ctx: ToolContext, a: Drug, b: Drug) -> tuple[DurResult | None, str | None]:
    """쌍의 API 결과 하나로 합친다. (결과, 미완결 꼬리표). 한쪽 성분코드가 없으면 호출하지 않는다(H20).
    결과가 None이면 **한 번도 호출하지 않은 것**이다(조회용 코드가 없음, AG-01-10 A의 `NO_API_CODE`)."""
    if not a.api_codes or not b.api_codes:
        return None, "API_PAIR_INCOMPLETE"
    results: list[DurResult] = []
    for x, y in product(a.api_codes[:MAX_API_CODES_PER_DRUG], b.api_codes[:MAX_API_CODES_PER_DRUG]):
        if not (DUR_CODE_RE.match(x) and DUR_CODE_RE.match(y)):
            continue
        try:
            results.append(ctx.api_pair_fn(x, y))  # type: ignore[misc]
        except Exception:  # noqa: BLE001 - API 실패는 예외가 아니라 꼬리표다
            results.append(_api_failed())
    if not results:
        return None, "API_PAIR_INCOMPLETE"
    failed = [r for r in results if not r.ok]
    rows = [row for r in results if r.ok for row in r.rows]
    partial = next((r.partial for r in failed if r.partial), None) or ("A" if failed and len(failed) < len(results) else None)
    merged = DurResult(
        ok=not failed, kind="usjnt", level="ingr", rows=rows, truncated=any(r.truncated for r in results), source_name=SOURCE_INGR,
        queried_at_utc=next((r.queried_at_utc for r in results if r.queried_at_utc), None),
        request_hashes=[h for r in results for h in r.request_hashes], partial=partial, error=next((r.error for r in failed if r.error), None),
    )
    return merged, None


def _codes_truncated(*drugs: Drug) -> bool:
    """한도(`MAX_API_CODES_PER_DRUG`)를 넘어 API에 묻지 않는 성분 코드가 있는 약이 있는가."""
    return any(len(d.api_codes) > MAX_API_CODES_PER_DRUG for d in drugs)


def _attach_api(ctx: ToolContext, a: Drug, b: Drug, file_items: list[dict[str, Any]], out: list[dict[str, Any]]) -> None:
    flag: str | None
    api_info: dict[str, Any]
    result: DurResult | None = None
    truncated = _codes_truncated(a, b)
    if ctx.api_pair_fn is None:
        flag, api_info = "API_FAIL", {"outcome": "API_UNAVAILABLE"}
    else:
        result, incomplete = _api_call(ctx, a, b)
        if result is None:  # 조회용 코드가 없어 호출 0회: 실패가 아니라 "묻지 않음"이다(AG-01-10 A)
            flag, api_info = incomplete, {"outcome": "API_UNAVAILABLE", "reason": API_REASON_NO_CODE}
        else:
            file_item = lookup.Item("contra_pair", FOUND if any(i["status"] == FOUND for i in file_items) else NOT_LISTED, (a.key, b.key), "", None, None,
                                    matches=[m for i in file_items for m in i.get("matches", [])])
            cc = cross_check(file_item, result)
            flag = cc.api_flag
            api_info = {"outcome": cc.outcome, "dates_differ": cc.dates_differ, "file_notice_dates": cc.file_notice_dates,
                        "api_notice_dates": cc.api_notice_dates, "queried_at_utc": result.queried_at_utc, "request_hashes": result.request_hashes}
            if flag == "API_PAIR_INCOMPLETE":  # 조회한 것 중 일부가 실패했다(쌍의 한쪽)
                api_info["reason"] = API_REASON_PARTIAL
    if truncated:  # 묻지 않은 성분 쌍이 있다: 대조가 끝나지 않았으므로 "파일에만 있음"·"같음"으로 말하지 않는다(파일 판정은 그대로)
        api_info["codes_truncated"] = True
        if flag in _TRUNCATED_FORBIDDEN_FLAGS:
            flag = "API_PAIR_INCOMPLETE"
            api_info["reason"] = API_REASON_TRUNCATED
    note = api_flag_note(flag, api_info.get("reason")) if flag else None  # 사유별 노트(AG-01-10 A). 꼬리표 이름·계약은 그대로다
    for it in file_items:
        it["api"] = api_info
        if flag:
            it["flags"] = [*it["flags"], flag]
            it["notes"] = [*it.get("notes", []), note]
    if result is not None and result.ok and result.rows:
        codes = sorted(f"{x}" for x in {*a.api_codes[:MAX_API_CODES_PER_DRUG], *b.api_codes[:MAX_API_CODES_PER_DRUG]})
        eid = f"dur_ingr:{codes[0]}:{codes[-1]}"
        rows = [{"row_key": r.evidence_id or f"{n}", "row_evidence_id": f"{eid}#{(r.evidence_id or str(n))[:12]}", "content": r.content, "remark": r.remark,
                 "notice_date": r.notification_date, "ingr_code": r.ingr_code, "pair_ingr_code": r.pair_ingr_code} for n, r in enumerate(result.rows)]
        out.append({
            "kind": "contra_pair", "status": FOUND, "subject": [a.label, b.label], "evidence_id": eid, "source": SOURCE_INGR, "as_of": None,
            "queried_at_utc": result.queried_at_utc or "unknown", "flags": [flag] if flag else [], "matches": rows, "dataset_key": "dur_ingr",
            "source_kind": SK_API_DIRECT, "drugs": [a.label, b.label], "drug_keys": [a.key, b.key], "cause_codes": codes,
            "notes": [note] if flag else [],
        })


# --------------------------------------------------------------------------- API 병기: 성분 단위 연령·임부

_AGE_BASE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(주|개월|세)\s*(미만|이하|이상)")


def _api_age_applies(base: str | None, age: Age) -> bool:
    """API `AGE_BASE`(예 `12세 미만`)가 사용자 나이에 해당하는지. 해석할 수 없으면 해당하는 것으로 본다(놓치지 않는 쪽)."""
    m = _AGE_BASE_RE.search(base or "")
    if not m:
        return True
    return lookup._age_hit(age.days, m.group(3), age_to_days(float(m.group(1)), m.group(2)))


def _api_single_call(fn: Any, codes: list[str]) -> DurResult | None:
    """성분코드마다 호출해 한 결과로 합친다. 코드가 없거나 하나라도 실패하면 실패 결과(rows 비움)다."""
    codes = [c for c in codes[:MAX_API_CODES_PER_DRUG] if DUR_CODE_RE.match(c)]
    if fn is None or not codes:
        return None
    results: list[DurResult] = []
    for c in codes:
        try:
            results.append(fn(c))
        except Exception:  # noqa: BLE001 - API 실패는 예외가 아니라 꼬리표다
            results.append(DurResult(ok=False, kind="age", level="ingr", source_name=SOURCE_INGR))
    if any(not r.ok for r in results):
        return DurResult(ok=False, kind=results[0].kind, level="ingr", source_name=SOURCE_INGR)
    return DurResult(ok=True, kind=results[0].kind, level="ingr", rows=[x for r in results for x in r.rows], source_name=SOURCE_INGR,
                     truncated=any(r.truncated for r in results), queried_at_utc=next((r.queried_at_utc for r in results if r.queried_at_utc), None),
                     request_hashes=[h for r in results for h in r.request_hashes])


def _attach_api_single(ctx: ToolContext, d: Drug, kind: str, age: Age | None, file_items: list[dict[str, Any]], out: list[dict[str, Any]]) -> None:
    """성분 하나의 연령·임부 파일 항목에 API 결과를 병기한다. 파일 판정은 바꾸지 않는다(RFP 5.1절 (7))."""
    if all(i["status"] == UNIDENTIFIED for i in file_items):
        return  # 파일이 판정하지 못한 항목은 병기 대상이 아니다(꼬리표 없음)
    fn = ctx.api_age_fn if kind == "age" else ctx.api_pregnancy_fn
    result = _api_single_call(fn, d.api_codes)
    if result is not None and result.ok and kind == "age" and age is not None:
        result = result.model_copy(update={"rows": [r for r in result.rows if _api_age_applies(r.age_base, age)]})
    if result is None or (not result.ok):
        flag, api_info = "API_FAIL", {"outcome": "API_UNAVAILABLE"}
        # 조회 함수는 있는데 이 성분에 조회용 코드가 없어 호출 0회: 실패가 아니라 "묻지 않음"이다(AG-01-10 A). 조회를 끈 실행(fn 없음)에는 사유를 적지 않는다
        if fn is not None and not any(DUR_CODE_RE.match(c) for c in d.api_codes[:MAX_API_CODES_PER_DRUG]):
            api_info["reason"] = API_REASON_NO_CODE
    else:
        status = FOUND if any(i["status"] == FOUND for i in file_items) else NOT_LISTED
        cc = cross_check({"status": status, "matches": [m for i in file_items for m in i.get("matches", [])]}, result)
        flag = cc.api_flag
        api_info = {"outcome": cc.outcome, "dates_differ": cc.dates_differ, "file_notice_dates": cc.file_notice_dates,
                    "api_notice_dates": cc.api_notice_dates, "queried_at_utc": result.queried_at_utc, "request_hashes": result.request_hashes}
    if _codes_truncated(d):  # AG-01-09 A: 묻지 않은 성분이 있다. "파일에만 있음"·"같음"으로 말하지 않는다(파일 판정·호출 수·outcome은 그대로)
        api_info["codes_truncated"] = True
        if flag in _TRUNCATED_FORBIDDEN_FLAGS:
            flag = "API_FAIL"  # 성분 단위 항목은 계약상 API_PAIR_INCOMPLETE를 쓰지 못한다(H20). API_ONLY·API_FAIL은 그대로 둔다
            api_info["reason"] = API_REASON_TRUNCATED
    note = api_flag_note(flag, api_info.get("reason")) if flag else None  # 사유별 노트(AG-01-10 A)
    for it in file_items:
        it["api"] = api_info
        if flag:
            it["flags"] = [*it["flags"], flag]
            it["notes"] = [*it.get("notes", []), note]
    if result is not None and result.ok and result.rows:
        code = sorted(d.api_codes[:MAX_API_CODES_PER_DRUG])[0]
        eid = f"dur_ingr:{kind}:{code}"
        rows = [{"row_key": r.evidence_id or f"{n}", "row_evidence_id": f"{eid}#{(r.evidence_id or str(n))[:12]}", "content": r.content, "remark": r.remark,
                 "notice_date": r.notification_date, "ingr_code": r.ingr_code, "grade": r.grade, "age_base": r.age_base} for n, r in enumerate(result.rows)]
        out.append({
            "kind": kind, "status": FOUND, "subject": [d.label], "evidence_id": eid, "source": SOURCE_INGR, "as_of": None,
            "queried_at_utc": result.queried_at_utc or "unknown", "flags": [flag] if flag else [], "matches": rows, "dataset_key": "dur_ingr",
            "source_kind": SK_API_DIRECT, "drugs": [d.label], "drug_keys": [d.key], "cause_codes": list(d.api_codes[:MAX_API_CODES_PER_DRUG]),
            "notes": [note] if flag else [],
        })


# --------------------------------------------------------------------------- 도구

def check_contraindications(args: CheckContraArgs, ctx: ToolContext) -> dict[str, Any]:
    if ctx.conn_factory is None:
        raise RuntimeError("conn_factory가 주입되지 않았다")
    drugs = [_resolve(ctx, a) for a in args.drugs]
    items: list[dict[str, Any]] = []
    age = Age(args.age.value, args.age.unit) if args.age else None
    kinds_wanted = [k for k, on in (("pregnancy", args.pregnancy), ("age", age is not None)) if on]

    for d in drugs:  # 식별·코드 연결 못 한 약
        if not d.ok:
            items.append(_unidentified_drug_item(d, "identify"))
            for k in kinds_wanted:
                items.append(_unidentified_drug_item(d, k))

    ok_drugs = [d for d in drugs if d.ok]
    conn = ctx.conn_factory()
    api_pairs: list[tuple[Drug, Drug, list[dict[str, Any]]]] = []
    single_api: list[tuple[Drug, str, list[dict[str, Any]]]] = []  # 성분 단위 연령·임부 API 병기 대상
    try:
        for a, b in combinations(drugs, 2):  # 모든 쌍
            if not (a.ok and b.ok):
                items.append(_pair_not_checked(a, b))  # 조회하지 못한 쌍 ≠ 금기 목록에 없음
                continue
            res = [lookup.lookup_pair(conn, x, y, ctx.paramstyle) for x, y in product(a.kids_codes, b.kids_codes) if x != y]
            if not res:  # 같은 성분끼리만 있어 쌍 조회 대상이 없다 → 성분 중복으로 따로 기록(아래)
                continue
            pair_items = _merged("contra_pair", res, f"contra_pair:{a.key}:{b.key}", [a, b])
            items.extend(pair_items)
            if ctx.api_enabled:
                api_pairs.append((a, b, pair_items))
        for d in ok_drugs:
            if args.pregnancy:
                preg = _merged("pregnancy", [lookup.lookup_pregnancy(conn, c, ctx.paramstyle) for c in d.kids_codes], f"pregnancy:{d.key}", [d])
                items.extend(preg)
                if ctx.api_enabled:
                    single_api.append((d, "pregnancy", preg))
            if age is not None:
                aged = _merged("age", [lookup.lookup_age(conn, c, age, ctx.paramstyle) for c in d.kids_codes], f"age:{d.key}", [d])
                items.extend(aged)
                if ctx.api_enabled:
                    single_api.append((d, "age", aged))
            if args.include_cautions:
                for kind in lookup._CAUTION_KINDS:
                    items.extend(_merged(kind, [lookup.lookup_caution(conn, c, kind, ctx.paramstyle) for c in d.kids_codes], f"{kind}:{d.key}", [d]))
    except Exception as exc:  # noqa: BLE001 - DB 오류 내용은 응답에 싣지 않고 예외 종류만 남긴다(비밀 비노출). 판정하지 못했으므로 UNIDENTIFIED
        items = [i for i in items if i["status"] == UNIDENTIFIED]
        for d in ok_drugs:
            it = _unidentified_drug_item(Drug(d.key, d.label, flags=[FLAG_LOOKUP_FAILED]), "identify")
            it["error_type"] = type(exc).__name__
            items.append(it)
        return _finish(drugs, items)
    finally:
        close = getattr(conn, "close", None)
        if callable(close):
            close()

    api_extra: list[dict[str, Any]] = []
    for a, b, pair_items in api_pairs:
        _attach_api(ctx, a, b, pair_items, api_extra)
    for d, kind, file_items in single_api:
        _attach_api_single(ctx, d, kind, age, file_items, api_extra)
    items.extend(api_extra)

    # 성분 중복(확장, 마지막 순서): 두 약이 같은 성분코드를 가지면 기록
    for a, b in combinations(ok_drugs, 2):
        same = sorted(set(a.kids_codes) & set(b.kids_codes))
        if same:
            items.append({
                "kind": "dup_ingredient", "status": FOUND, "subject": [a.label, b.label], "evidence_id": f"dup_ingredient:{a.key}:{b.key}",
                "source": SRC_KIDS, "as_of": AS_OF_KIDS, "queried_at_utc": None, "flags": [], "matches": [], "dataset_key": "dup_ingredient",
                "source_kind": SK_FILE, "drugs": [a.label, b.label], "drug_keys": [a.key, b.key], "cause_codes": same, "notes": [],
            })
    return _finish(drugs, items)


def _finish(drugs: list[Drug], items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "items": items, "input_units": {d.key: ("ingredient" if d.unit == "ingredient" else "product") for d in drugs if d.ok},
        "known_ids": sorted(known_ids(items)),
    }
