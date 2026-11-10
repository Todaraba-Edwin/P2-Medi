"""BE-10-08 제형 분류와 `form_match` 비교(오프라인, 네트워크 없음).

목적: 성분 단위 보조 조회(`all_forms`)가 성분 이름만 같고 제형·용도가 다른 KIDS 코드를 끌어오는 오탐을 막는다
(예: 경구 정제 ↔ 주사제 코드, 안구 관류액 ↔ 서방정·주사제). 일반 규칙만 쓰며 특정 제품 이름에 맞추지 않는다(RFP-26-04).

- 제품 쪽: 제품명 접미(규칙) → (없으면) 허가 `prduct_type` 효능군 힌트 → (없으면) unknown.
- KIDS 코드 쪽: 성분코드 뒤 3자리 접미(ATB·BIJ·ACH …)의 공식 코드표를 열람하지 못했으므로, KIDS 제품코드→제품명 쌍에서
  접미별 제품명 제형 분포를 세어 **측정으로 추정**한다(`infer_code_forms`). 모호한 접미는 제형 `None`(경로만) 또는 unknown.
- 비교: `match`(경로·제형군 같음) / `route_only`(경로만 같음) / `mismatch`(경로가 다름) / `unknown`(한쪽을 모름).
  판정에 쓰는 것은 `match`뿐이다(안전 쪽: 확인 못 하면 UNIDENTIFIED, "금기 없음"으로 읽지 않는다).
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Any

# 투여 경로
R_ORAL, R_INJ, R_TOPICAL, R_EYE, R_OTHER = "경구", "주사", "외용", "안과", "기타"
ROUTES = (R_ORAL, R_INJ, R_TOPICAL, R_EYE, R_OTHER)

FM_MATCH, FM_ROUTE_ONLY, FM_MISMATCH, FM_UNKNOWN = "match", "route_only", "mismatch", "unknown"
USABLE = {FM_MATCH}  # 이 값일 때만 금기 판정에 쓴다

NOTE_MISMATCH = "다른 제형({forms})에서 목록에 있음, 이 제품 판정 아님"
NOTE_ROUTE_ONLY = "같은 투여 경로의 다른 제형({forms})에서 목록에 있음, 이 제품 판정 아님"
NOTE_UNKNOWN = "제품 제형 또는 목록 코드의 제형을 알 수 없어 이 제품 판정에 쓰지 않음(참고)"

# --------------------------------------------------------------------------- 이름 → (경로, 형태, 제형군)

_PAREN_RE = re.compile(r"[(（\[][^()（）\[\]]*[)）\]]")  # 가장 안쪽 괄호. 중첩(`(아리피프라졸(미분화))`)은 반복해서 벗긴다
_KIDS_TAIL_RE = re.compile(r"_\([^)]*\)\s*$")
_STRENGTH_TAIL_RE = re.compile(
    r"(?:[\d.,/\s%~\-·+]|밀리그램|밀리그람|마이크로그램|마이크로그람|그램|그람|밀리리터|리터|국제단위|단위|mg|ug|mcg|μg|㎍|㎎|㎖|g|ml|l|iu|포|병|앰플|바이알|시린지)+$",
    re.IGNORECASE)

# (형태, 경로, 제형군) — 같은 접미끼리는 긴 것이 먼저(정렬해서 쓴다). 제형군은 비교 단위다.
_G_TAB, _G_ER_TAB, _G_EC_TAB = "정제", "서방정", "장용정"
_G_CAP, _G_ER_CAP, _G_EC_CAP = "캡슐", "서방캡슐", "장용캡슐"
_G_POWDER, _G_GRAN, _G_SYRUP, _G_SUSP, _G_SOL = "산제·분말", "과립", "시럽", "현탁액", "액"
_FORMS: tuple[tuple[str, str, str], ...] = (
    # 주사
    ("주사액", R_INJ, "주사제"), ("주사제", R_INJ, "주사제"), ("주사용", R_INJ, "주사제"), ("주사", R_INJ, "주사제"), ("수액제", R_INJ, "주사제"),
    ("수액", R_INJ, "주사제"), ("프리필드", R_INJ, "주사제"), ("주입액", R_INJ, "주사제"), ("주", R_INJ, "주사제"),
    # 경구 정제·캡슐
    ("서방정", R_ORAL, _G_ER_TAB), ("방출조절정", R_ORAL, _G_ER_TAB), ("서방캡슐", R_ORAL, _G_ER_CAP), ("서방캅셀", R_ORAL, _G_ER_CAP),
    ("장용정", R_ORAL, _G_EC_TAB), ("장용캡슐", R_ORAL, _G_EC_CAP), ("장용캅셀", R_ORAL, _G_EC_CAP),
    ("필름코팅정", R_ORAL, _G_TAB), ("코팅정", R_ORAL, _G_TAB), ("당의정", R_ORAL, _G_TAB), ("구강붕해정", R_ORAL, _G_TAB),
    ("구강붕해필름", R_ORAL, "필름"), ("구강용해필름", R_ORAL, "필름"), ("츄어블정", R_ORAL, _G_TAB), ("저작정", R_ORAL, _G_TAB), ("발포정", R_ORAL, _G_TAB), ("분산정", R_ORAL, _G_TAB), ("설하정", R_ORAL, _G_TAB),
    ("정제", R_ORAL, _G_TAB), ("정", R_ORAL, _G_TAB),
    ("연질캡슐", R_ORAL, _G_CAP), ("경질캡슐", R_ORAL, _G_CAP), ("캡슐", R_ORAL, _G_CAP), ("캅셀", R_ORAL, _G_CAP),
    # 경구 산제·액
    ("건조시럽", R_ORAL, _G_SYRUP), ("시럽", R_ORAL, _G_SYRUP), ("현탁액", R_ORAL, _G_SUSP), ("현탁용분말", R_ORAL, _G_SUSP), ("내복액", R_ORAL, _G_SOL),
    ("엘릭서", R_ORAL, _G_SOL), ("드링크", R_ORAL, _G_SOL), ("과립", R_ORAL, _G_GRAN), ("세립", R_ORAL, _G_GRAN), ("산제", R_ORAL, _G_POWDER),
    ("분말", R_ORAL, _G_POWDER), ("산", R_ORAL, _G_POWDER), ("환", R_ORAL, "환제"), ("트로키", R_ORAL, "트로키"), ("껌", R_ORAL, "껌"),
    ("젤리", R_ORAL, "젤리"), ("스틱", R_ORAL, "스틱"),
    # 안과
    ("점안액", R_EYE, "점안액"), ("점안제", R_EYE, "점안액"), ("안약", R_EYE, "점안액"), ("점안", R_EYE, "점안액"), ("안액", R_EYE, "점안액"),
    ("안연고", R_EYE, "안연고"), ("안겔", R_EYE, "안연고"),
    # 외용
    ("관류액", R_TOPICAL, "관류액"), ("세척액", R_TOPICAL, "관류액"), ("세정액", R_TOPICAL, "관류액"), ("소독액", R_TOPICAL, "관류액"),
    ("외용액", R_TOPICAL, "외용액"), ("도포액", R_TOPICAL, "외용액"), ("로션", R_TOPICAL, "로션"), ("연고", R_TOPICAL, "연고"), ("크림", R_TOPICAL, "크림"),
    ("겔", R_TOPICAL, "겔"), ("젤", R_TOPICAL, "겔"), ("패취", R_TOPICAL, "패취"), ("플라스타", R_TOPICAL, "패취"), ("카타플라스마", R_TOPICAL, "패취"),
    ("파스", R_TOPICAL, "패취"), ("첩부제", R_TOPICAL, "패취"), ("폼", R_TOPICAL, "폼"), ("리니멘트", R_TOPICAL, "외용액"),
    # 기타(흡입·비강·질·직장·귀)
    ("점비액", R_OTHER, "비강"), ("비액", R_OTHER, "비강"), ("점이액", R_OTHER, "점이"), ("흡입액", R_OTHER, "흡입"), ("흡입제", R_OTHER, "흡입"),
    ("스프레이", R_OTHER, "스프레이"), ("에어로솔", R_OTHER, "스프레이"), ("좌제", R_OTHER, "좌제"), ("좌약", R_OTHER, "좌제"), ("질정", R_OTHER, "질정"),
    ("관장액", R_OTHER, "관장"),
)
_FORMS = tuple(sorted(_FORMS, key=lambda f: -len(f[0])))
_STRONG = {f for f, _r, _g in _FORMS if len(f) >= 2 or f == "정"} - {"점안", "안약", "분말", "폼", "스틱", "젤리", "껌", "트로키", "산제", "세립", "과립"}  # 끝에서 몇 글자 떨어져도 인정하는 형태(짧은 모호어 제외)
_TAIL_ALLOWANCE = 3  # 형태 뒤에 올 수 있는 브랜드 꼬리 글자 수(예: `게보린정 에스`)
_ER_TOKEN_RE = re.compile(r"(?:이알|에스알|엑스알|엑스엘|ER|SR|XR|XL)\s*(정|캡슐|캅셀)$", re.IGNORECASE)
_EN_FORM_RE = re.compile(r"\b(tab(?:let)?s?|cap(?:sule)?s?|inj(?:ection)?|syr(?:up)?|oint(?:ment)?|cream|gel)\.?$", re.IGNORECASE)
_EN_MAP = {"tab": "정", "cap": "캡슐", "inj": "주사", "syr": "시럽", "oint": "연고", "cream": "크림", "gel": "겔"}

# 허가 `prduct_type`(효능군 이름)에서 형태 정보가 확실한 것만 힌트로 쓴다. 제품명에서 경로를 못 정했을 때의 보조다.
_TYPE_HINTS: tuple[tuple[str, str], ...] = (("안과용제", R_EYE), ("관류용제", R_TOPICAL), ("관류", R_TOPICAL))


def _clean(name: str) -> tuple[str, str]:
    """(괄호·KIDS 꼬리·함량 꼬리를 뗀 이름, 괄호 안 내용을 이은 문자열)."""
    s = unicodedata.normalize("NFKC", name or "")
    s = _KIDS_TAIL_RE.sub("", s)
    inner_parts: list[str] = []
    while True:
        found = _PAREN_RE.findall(s)
        if not found:
            break
        inner_parts += [f[1:-1] for f in found]
        s = _PAREN_RE.sub("", s)
    inner, s = " ".join(inner_parts), s.strip()
    for _ in range(3):
        t = _STRENGTH_TAIL_RE.sub("", s).strip()
        if t == s:
            break
        s = t
    return s, inner


def _find(s: str) -> tuple[str, str, str] | None:
    """이름 끝에서 제형 단어를 찾는다. 끝 정확 일치 → 서방 토큰 → 영문 → 끝에서 몇 글자 안의 강한 형태."""
    if not s:
        return None
    m = _ER_TOKEN_RE.search(s)
    if m:
        return ("서방정" if m.group(1) == "정" else "서방캡슐", R_ORAL, _G_ER_TAB if m.group(1) == "정" else _G_ER_CAP)
    for f, r, g in _FORMS:
        if s.endswith(f):
            return f, r, g
    m = _EN_FORM_RE.search(s)
    if m:
        ko = _EN_MAP[next(k for k in _EN_MAP if m.group(1).lower().startswith(k))]
        for f, r, g in _FORMS:
            if f == ko:
                return f, r, g
    tail = s[-(_TAIL_ALLOWANCE + 6):]
    best: tuple[int, tuple[str, str, str]] | None = None
    for f, r, g in _FORMS:
        if f in _STRONG:
            idx = tail.rfind(f)
            if idx >= 0:
                end = idx + len(f)
                if len(tail) - end <= _TAIL_ALLOWANCE and (best is None or end > best[0] or (end == best[0] and len(f) > len(best[1][0]))):
                    best = (end, (f, r, g))
    return best[1] if best else None


def classify_product_form(name: str, product_type: str | None = None) -> dict[str, str | None]:
    """제품명(·효능군 힌트)에서 `{route, form, group, src}`를 만든다. 못 정하면 값은 None, src는 `none`.

    `route`만 정해지고 형태를 모를 수 있다(`group` None). 일반 `…액`은 경로가 여럿이라 이름만으로는 경로 None이며,
    효능군 힌트(안과용제·관류용제)가 있으면 그 경로를 쓴다.
    """
    base, inner = _clean(name)
    hit = _find(base)
    src = "name"
    if hit is None and inner:  # 괄호 안에 제형이 적힌 경우(`XX(정제)`)만 보조로 본다
        hit, src = _find(inner.strip()), "name_paren"
    if hit is not None:
        form, route, group = hit
        return {"route": route, "form": form, "group": group, "src": src}
    if base.endswith("액"):
        for kw, route in _TYPE_HINTS:
            if product_type and kw in product_type:
                return {"route": route, "form": "액", "group": "관류액" if route == R_TOPICAL else "점안액", "src": "product_type"}
        return {"route": None, "form": "액", "group": _G_SOL, "src": "ambiguous_liquid"}
    for kw, route in _TYPE_HINTS:
        if product_type and kw in product_type:
            return {"route": route, "form": None, "group": None, "src": "product_type"}
    return {"route": None, "form": None, "group": None, "src": "none"}


# --------------------------------------------------------------------------- KIDS 코드 접미 → 제형(측정으로 추정)

DOMINANT_ROUTE_SHARE = 0.8  # 접미의 경로를 정하는 최소 비율(분류된 이름 중)
DOMINANT_GROUP_SHARE = 0.6  # 접미의 제형군을 정하는 최소 비율
MIN_CLASSIFIED = 5  # 분류된 이름이 이보다 적으면 추정하지 않는다(unknown)


def infer_code_forms(pairs: Iterable[tuple[str, str]]) -> dict[str, dict[str, Any]]:
    """(성분코드 9자리, 제품명) 쌍 → {접미: {route, group, n, classified, route_share, group_share, confidence, top}}.

    접미 = 코드 뒤 3자리. 공식 제형 코드표가 아니라 제품명 접미 분포로 추정한 값이며 `method`에 그렇게 남긴다.
    """
    route_c: dict[str, Counter[str]] = defaultdict(Counter)
    group_c: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)
    total: Counter[str] = Counter()
    for code, name in pairs:
        code = (code or "").strip()
        if len(code) != 9:
            continue
        suf = code[6:]
        total[suf] += 1
        c = classify_product_form(name)
        if c["route"]:
            route_c[suf][c["route"]] += 1
            if c["group"]:
                group_c[suf][(c["route"], c["group"])] += 1
    out: dict[str, dict[str, Any]] = {}
    for suf, n in total.items():
        rc, gc = route_c.get(suf, Counter()), group_c.get(suf, Counter())
        classified = sum(rc.values())
        route = group = None
        rs = gs = 0.0
        if classified >= MIN_CLASSIFIED:
            r, rn = rc.most_common(1)[0]
            rs = rn / classified
            if rs >= DOMINANT_ROUTE_SHARE:
                route = r
                routed = {k: v for k, v in gc.items() if k[0] == r}
                gn_total = sum(routed.values())
                if gn_total:
                    (gr, g), gn = max(routed.items(), key=lambda kv: kv[1])
                    gs = gn / gn_total
                    if gs >= DOMINANT_GROUP_SHARE and gr == r:
                        group = g
        conf = "high" if route and rs >= 0.95 and group is not None and gs >= 0.85 else ("medium" if route else "low")
        out[suf] = {"route": route, "group": group, "n": n, "classified": classified, "route_share": round(rs, 3), "group_share": round(gs, 3),
                    "confidence": conf, "top": [[f"{k[0]}/{k[1]}", v] for k, v in gc.most_common(4)], "method": "measured:name-suffix-distribution"}
    return out


def code_form(code: str, form_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    e = form_map.get((code or "")[6:]) or {}
    return {"route": e.get("route"), "group": e.get("group"), "confidence": e.get("confidence", "low")}


# --------------------------------------------------------------------------- 비교

def compare_forms(product: dict[str, Any] | None, code: dict[str, Any] | None) -> str:
    """제품 제형(`classify_product_form` 결과)과 코드 제형(`code_form`)을 비교해 `form_match` 값을 돌려준다."""
    pr = (product or {}).get("route")
    cr = (code or {}).get("route")
    if not pr or not cr:
        return FM_UNKNOWN
    if pr != cr:
        return FM_MISMATCH
    pg, cg = (product or {}).get("group"), (code or {}).get("group")
    if pg and cg and pg == cg:
        return FM_MATCH
    return FM_ROUTE_ONLY


_RANK = {FM_MATCH: 3, FM_ROUTE_ONLY: 2, FM_MISMATCH: 1, FM_UNKNOWN: 0}


def best_match(results: Iterable[str]) -> str:
    """코드 여럿의 비교 결과 중 가장 강한 것. 하나라도 `match`면 match, 코드가 없으면 unknown."""
    return max(results, key=lambda r: _RANK[r], default=FM_UNKNOWN)


def label(form: dict[str, Any] | None) -> str:
    """사람이 읽는 제형 이름(`경구/정제`). 모르면 `?`."""
    f = form or {}
    return "/".join(x for x in (f.get("route"), f.get("group")) if x) or "?"


def forms_rules_signature() -> str:
    """분류 규칙의 해시. 규칙이 바뀌면 사전 버전이 바뀌게 빌더가 해시에 넣는다."""
    parts = [list(_FORMS), sorted(_STRONG), _TAIL_ALLOWANCE, _STRENGTH_TAIL_RE.pattern, _ER_TOKEN_RE.pattern, _EN_FORM_RE.pattern, list(_TYPE_HINTS),
             DOMINANT_ROUTE_SHARE, DOMINANT_GROUP_SHARE, MIN_CLASSIFIED]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
