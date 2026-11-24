"""AG-13-45 A(U-26 C-1, 2026-11-24): 도구 인자를 Router 확정 집합에 묶는다(순수 함수, LLM·DB·네트워크 호출 0).

사용자가 되묻기에서 고른 약(`USER_CONFIRMED`)이 있는 차례에서, 모델이 `check_contraindications`에 넘긴 `drugs[]` 중 **Router가 정리한 약과 무관한**
항목(질문 속 어느 엔티티와도 이름이 같지 않고 확정 집합에 없는 `item_seq`)을 버리고, 확정 엔티티는 `item_seq`로 보강한다. 모델을 다시 부르지 않고
개수만 이벤트로 남긴다(`registry.IGNORED_ARGS`의 `ARG_IGNORED` 선례). 입구 조건은 "확정 엔티티가 있을 때"뿐이라 확정이 없는 평가 경로(평가는
`confirmed_item_seqs`를 쓰지 않는다)와 첫 질문 경로의 인자는 한 글자도 바뀌지 않는다.

규칙(엔티티 = 이번 차례 Router 상태 `entities`):
- `item_seq`가 있는 항목: 그 코드가 **RESOLVED 엔티티의 `item_seq`**일 때만 남긴다. 아니면 버린다(비선택 후보의 코드).
- `item_seq` 없이 `name`만 있는 항목: 이름(정규화)이 어느 엔티티의 원문·정규화 이름·확정 제품 이름과 **같으면** 남긴다. 어느 엔티티와도 같지 않으면 버린다.
  같은 이름의 엔티티가 확정(`USER_CONFIRMED`)이고 코드가 있으면 `item_seq`를 붙인다(이름 없이 코드로 조회하도록 모델이 이름을 바꿔 넘겨도 확정 제품이 조회된다).
  NOT_FOUND·모호·오탈자 의심 엔티티와 같은 이름은 그대로 둔다(영향 없음).
- `ingredient_code`만 있는 항목: 어느 약인지 알 수 없어 그대로 둔다(성분 단위 조회는 이 규칙의 대상이 아니다).
- 같은 확정 제품을 가리키는 항목이 둘 이상이면 첫 항목만 남긴다.
- 남은 항목이 하나도 없으면(모델이 전부 무관한 약을 넘김) RESOLVED 엔티티의 `item_seq`로 대신 채운다(`fallback`).
값(이름·코드)은 이벤트에 남기지 않고 개수만 남긴다. 한계: `identify_drug` 인자·`item_seq` 인자 도구(`get_label_section`·`search_label`)는 이 규칙의 대상이 아니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.tools.drug_dict import DrugDict, normalize_name

FLAG_USER_CONFIRMED = "USER_CONFIRMED"  # `router.FLAG_USER_CONFIRMED`와 같은 값(순환 import를 피하려고 여기서 다시 적는다. 시험이 같은 값인지 본다)
STATUS_RESOLVED = "RESOLVED"
CONFINED_TOOLS = frozenset({"check_contraindications"})
EVENT_ARG_CONFINED = "ARG_CONFINED"


@dataclass(frozen=True)
class ConfineResult:
    args: dict[str, Any]
    n_dropped: int = 0     # 버린 항목 수(무관한 `item_seq`·이름, 중복)
    n_added: int = 0       # `item_seq`를 붙인 항목 수(확정 엔티티 보강)
    fallback: bool = False  # 남은 항목이 없어 RESOLVED 엔티티로 대신 채움

    @property
    def changed(self) -> bool:
        return bool(self.n_dropped or self.n_added or self.fallback)

    def event(self, tool: str) -> dict[str, Any]:
        """내용 없는 개수만 담은 이벤트(H21)."""
        return {"rule": "H21", "event": EVENT_ARG_CONFINED, "tool": tool, "n_dropped": self.n_dropped, "n_added": self.n_added,
                "fallback": self.fallback}


def _is_resolved(e: dict[str, Any]) -> bool:
    return e.get("status") == STATUS_RESOLVED and bool(e.get("item_seq"))


def has_confirmed(entities: list[dict[str, Any]] | None) -> bool:
    """사용자가 되묻기에서 고른 약으로 확정된 엔티티가 있는가(이 규칙의 입구 조건)."""
    return any(isinstance(e, dict) and FLAG_USER_CONFIRMED in (e.get("flags") or []) and _is_resolved(e) for e in entities or [])


def resolved_seqs(entities: list[dict[str, Any]] | None) -> list[str]:
    """RESOLVED 엔티티의 품목기준코드(나온 순서, 중복 제거). `_result_summary`의 Router 쌍 한정(C-3)도 같은 집합을 쓴다."""
    return list(dict.fromkeys(str(e["item_seq"]) for e in entities or [] if isinstance(e, dict) and _is_resolved(e)))


def _product_name(dd: DrugDict, seq: str) -> str | None:
    i = dd._by_seq.get(seq)
    name = str(dd.products[i].get("name") or "").strip() if i is not None else ""
    return name or None


def confine_check_args(args: dict[str, Any], entities: list[dict[str, Any]] | None, dd: DrugDict) -> ConfineResult:
    """`check_contraindications` 인자를 확정 집합에 묶는다. 입구 조건(`has_confirmed`)이 아니거나 모양이 낯설면 인자를 그대로 돌려준다."""
    ents = [e for e in entities or [] if isinstance(e, dict)]
    drugs = args.get("drugs") if isinstance(args, dict) else None
    if not has_confirmed(ents) or not isinstance(drugs, list) or not drugs:
        return ConfineResult(args)
    seqs = set(resolved_seqs(ents))
    # 정규화 이름 → 엔티티. 원문·정규화 이름과 RESOLVED 엔티티의 사전 제품 이름이 모두 키다
    by_name: dict[str, dict[str, Any]] = {}
    for e in ents:
        names = [e.get("raw"), e.get("normalized")]
        if _is_resolved(e):
            names.append(_product_name(dd, str(e["item_seq"])))
        for n in names:
            if isinstance(n, str) and n.strip():
                by_name.setdefault(normalize_name(n), e)

    kept: list[Any] = []
    seen_confirmed: set[str] = set()
    n_dropped = n_added = 0
    for d in drugs:
        if not isinstance(d, dict):
            kept.append(d)  # 모양이 낯설면 건드리지 않는다(검증은 도구가 한다)
            continue
        seq, name = d.get("item_seq"), d.get("name")
        target: dict[str, Any] | None = None
        augmented = False
        if isinstance(seq, str) and seq:
            if seq not in seqs:
                n_dropped += 1  # 확정·정리된 약이 아닌 코드(비선택 후보)
                continue
            target = next((e for e in ents if _is_resolved(e) and e["item_seq"] == seq), None)
        elif isinstance(name, str) and name.strip():
            target = by_name.get(normalize_name(name))
            if target is None:
                n_dropped += 1  # 질문 속 어느 약과도 무관한 이름
                continue
            if FLAG_USER_CONFIRMED in (target.get("flags") or []) and _is_resolved(target):
                d = {**d, "item_seq": target["item_seq"]}
                augmented = True
        confirmed_seq = str(d.get("item_seq") or "")
        if confirmed_seq and target is not None and FLAG_USER_CONFIRMED in (target.get("flags") or []):
            if confirmed_seq in seen_confirmed:
                n_dropped += 1  # 같은 확정 제품을 두 번 넘김
                continue
            seen_confirmed.add(confirmed_seq)
        n_added += augmented
        kept.append(d)
    fallback = False
    if not kept:
        kept = [{"item_seq": s} for s in resolved_seqs(ents)]
        fallback = True
    res = ConfineResult({**args, "drugs": kept}, n_dropped, n_added, fallback)
    return res if res.changed else ConfineResult(args)
