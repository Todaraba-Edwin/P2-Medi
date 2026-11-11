"""AG-05-01 A: Router `TYPO_SCORE_MAX`(오탈자 의심 기준값)를 AG-04 **개발셋**으로 보정한다. 외부 호출 0.

읽는 것: `evaluation/eval_set/dev_set.jsonl`(개발셋만. 시험셋 `*.SEALED.jsonl`은 열지 않는다), `data/mock/dict/drug_dict.json`.
쓰는 것: 표준 출력(마크다운 표)과 `--out`을 준 경우 그 파일. 사전·개발셋·소스는 고치지 않는다.

기준값 선택 규칙(측정 전에 고정, 2026-11-11):
  양성 = 오탈자 변형 약("오탈자" 문항의 `variant_name`). 음성 = 오탈자가 아닌데 되묻기로 간 약(모호 문항 약 + 정상 문항 중 되묻기가 된 약).
  1) 격자는 0.30~0.90, 0.05 단위.
  2) 후보 값 = 음성 중 TYPO로 잘못 분류된 비율(FPR)이 FPR_CAP(10%) 이하인 격자.
  3) 후보 중 양성 TYPO 재현율이 가장 높은 값을 고른다. 동률이면 현재값(0.6)에 가까운 쪽, 그래도 같으면 낮은 쪽.
  4) 고른 값이 현재값과 다르더라도, 고른 값의 재현율 Wilson 95% 구간이 현재값의 구간과 겹치면 **바꾸지 않는다**("근거 불충분").
  칸당 n≤8이면 유의성을 주장하지 않는다(PJ2-RFP.md 9.1절).

AG-05-02 A: Router `NOT_FOUND_SCORE_MAX`(BM25 1위 점수가 이 이하이면 TYPO가 아니라 NOT_FOUND, 후보 제시는 유지) 보정.
기준값 선택 규칙(측정 전에 고정, 2026-11-11):
  양성 = 가상 약("근거 없음" 문항의 `fake_name`). 오분류 = 오탈자·모호·정상 약이 NOT_FOUND로 간 것.
  1) 격자는 0.15~0.60, 0.05 단위 + 비활성(0.0 = 현재).
  2) 후보 값 = 오탈자 약의 NOT_FOUND 오분류율 ≤ NF_TYPO_CAP(10%) **그리고** 오탈자·모호·정상 전체 NOT_FOUND 오분류율 ≤ NF_ALL_CAP(5%)인 격자.
  3) 후보 중 가상 약 NOT_FOUND 재현율이 가장 높은 값, 동률이면 낮은 값(보수적).
  4) 고른 값의 재현율 Wilson 95% 구간이 비활성(0.0)의 구간과 겹치면 **값을 바꾸지 않고(비활성 유지)** "근거 불충분"으로 보고한다.
  가상 약 n=13이라 유의성을 주장하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent import router  # noqa: E402
from app.tools.drug_dict import MATCH_BM25, MATCH_CONTAINS, MATCH_PREFIX, DrugDict  # noqa: E402

DEV_SET = ROOT / "evaluation" / "eval_set" / "dev_set.jsonl"
DICT_PATH = ROOT / "data" / "mock" / "dict" / "drug_dict.json"
GRID = [round(0.30 + 0.05 * i, 2) for i in range(13)]  # 0.30 ~ 0.90
NF_GRID = [0.0] + [round(0.15 + 0.05 * i, 2) for i in range(10)]  # 0.0(비활성) + 0.15 ~ 0.60
NF_TYPO_CAP = 0.10
NF_ALL_CAP = 0.05
FPR_CAP = 0.10
SMALL_N = 8  # 칸당 n이 이 값 이하면 유의성 주장 금지

KIND_REAL, KIND_TYPO, KIND_AMBIG, KIND_FAKE = "real", "typo", "ambiguous", "fake"
NORMAL_GROUPS = {"정상-병용", "정상-연령", "정상-임부", "정상-목록에없는약", "정상-응급", "오정보"}


# --------------------------------------------------------------------------- 순수 계산(단위 시험 대상)

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 95% 구간. n=0이면 (0, 1)."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def fmt(k: int, n: int) -> str:
    if n == 0:
        return "- (n=0)"
    lo, hi = wilson(k, n)
    mark = " †" if n <= SMALL_N else ""
    return f"{k}/{n} ({k / n:.0%}) [{lo:.0%}~{hi:.0%}]{mark}"


@dataclass
class Obs:
    """약 하나의 관찰. kind=정답 라벨, status=Router가 붙인 엔티티 상태(None이면 엔티티로 못 잡음), top=BM25 1위 점수(없으면 None)."""

    kind: str
    status: str | None
    top: float | None = None
    match_type: str | None = None


def status_at(o: Obs, t: float, nf: float = 0.0) -> str | None:
    """같은 관찰에서 기준값 t(오탈자)·nf(근거 없음)일 때의 상태. BM25 일치만 갈린다(router._entity와 같은 규칙: nf 먼저, 그다음 t)."""
    if o.status is None:
        return None
    if o.match_type == MATCH_BM25 and o.top is not None:
        if o.top <= nf:
            return router.ST_NOT_FOUND
        return router.ST_TYPO if o.top <= t else router.ST_AMBIGUOUS
    return o.status


def clarified(st: str | None) -> bool:
    return st in (router.ST_AMBIGUOUS, router.ST_TYPO)


@dataclass
class GridRow:
    t: float
    typo_recall: tuple[int, int]  # 오탈자 약 중 TYPO 라벨
    typo_clarify: tuple[int, int]  # 오탈자 약 중 되묻기(TYPO·AMBIGUOUS)
    ambig_clarify: tuple[int, int]  # 모호 약 중 되묻기
    ambig_as_typo: tuple[int, int]  # 모호 약 중 TYPO로 분류
    real_unneeded: tuple[int, int]  # 정상 약 중 되묻기
    fpr: tuple[int, int]  # 음성(오탈자 아닌 되묻기 약) 중 TYPO
    fake_notfound: tuple[int, int]  # 가상 약 중 NOT_FOUND


def measure(obs: Iterable[Obs], t: float, nf: float = 0.0) -> GridRow:
    caught = [(o, status_at(o, t, nf)) for o in obs if o.status is not None]
    typo = [s for o, s in caught if o.kind == KIND_TYPO]
    amb = [s for o, s in caught if o.kind == KIND_AMBIG]
    real = [s for o, s in caught if o.kind == KIND_REAL]
    fake = [s for o, s in caught if o.kind == KIND_FAKE]
    neg = [s for s in (*amb, *real) if clarified(s)]  # 오탈자 아닌 약 중 되묻기로 간 것
    return GridRow(
        t=t,
        typo_recall=(sum(s == router.ST_TYPO for s in typo), len(typo)),
        typo_clarify=(sum(clarified(s) for s in typo), len(typo)),
        ambig_clarify=(sum(clarified(s) for s in amb), len(amb)),
        ambig_as_typo=(sum(s == router.ST_TYPO for s in amb), len(amb)),
        real_unneeded=(sum(clarified(s) for s in real), len(real)),
        fpr=(sum(s == router.ST_TYPO for s in neg), len(neg)),
        fake_notfound=(sum(s == router.ST_NOT_FOUND for s in fake), len(fake)),
    )


@dataclass
class NfRow:
    nf: float
    fake_nf: tuple[int, int]  # 가상 약 중 NOT_FOUND(재현율)
    typo_nf: tuple[int, int]  # 오탈자 약 중 NOT_FOUND(오분류)
    ambig_nf: tuple[int, int]  # 모호 약 중 NOT_FOUND(오분류)
    real_nf: tuple[int, int]  # 정상 약 중 NOT_FOUND(오분류)
    all_nf: tuple[int, int]  # 오탈자·모호·정상 전체 중 NOT_FOUND(오분류)
    typo_recall: tuple[int, int]  # 부수 영향: 오탈자 약 중 TYPO(후보 제시로 이어지는 라벨)


def measure_nf(obs: Iterable[Obs], t: float, nf: float) -> NfRow:
    caught = [(o, status_at(o, t, nf)) for o in obs if o.status is not None]
    by = {k: [s for o, s in caught if o.kind == k] for k in (KIND_FAKE, KIND_TYPO, KIND_AMBIG, KIND_REAL)}
    neg = [*by[KIND_TYPO], *by[KIND_AMBIG], *by[KIND_REAL]]
    nfk = lambda xs: (sum(s == router.ST_NOT_FOUND for s in xs), len(xs))  # noqa: E731
    return NfRow(nf, nfk(by[KIND_FAKE]), nfk(by[KIND_TYPO]), nfk(by[KIND_AMBIG]), nfk(by[KIND_REAL]), nfk(neg),
                 (sum(s == router.ST_TYPO for s in by[KIND_TYPO]), len(by[KIND_TYPO])))


def choose_nf(rows: list[NfRow]) -> tuple[float, str]:
    """위 docstring(AG-05-02 A)의 선택 규칙 1~4. 비활성(0.0)을 기준으로 삼는다."""
    base = next(r for r in rows if r.nf == 0.0)
    cand = [r for r in rows if r.nf > 0.0 and _rate(r.typo_nf) <= NF_TYPO_CAP and _rate(r.all_nf) <= NF_ALL_CAP]
    if not cand:
        return 0.0, "오분류 상한을 만족하는 격자 없음 → 비활성 유지"
    best_rate = max(_rate(r.fake_nf) for r in cand)
    best = min((r for r in cand if _rate(r.fake_nf) == best_rate), key=lambda r: r.nf)
    if best_rate <= _rate(base.fake_nf):
        return 0.0, f"후보 {best.nf:.2f}가 비활성보다 가상 약 재현율을 높이지 못함 → 비활성 유지, 근거 불충분"
    lo_b, hi_b = wilson(*best.fake_nf)
    lo_0, hi_0 = wilson(*base.fake_nf)
    if lo_b <= hi_0 and lo_0 <= hi_b:
        return 0.0, f"후보 {best.nf:.2f}의 가상 약 재현율 구간이 비활성의 구간과 겹침 → 값을 바꾸지 않음, 근거 불충분"
    return best.nf, f"후보 {best.nf:.2f}의 가상 약 재현율 구간이 비활성과 겹치지 않음"


def _rate(kn: tuple[int, int]) -> float:
    return kn[0] / kn[1] if kn[1] else 0.0


def choose_threshold(rows: list[GridRow], current: float, fpr_cap: float = FPR_CAP) -> tuple[float, str]:
    """위 docstring의 선택 규칙 1~4. (선택값, 사유)를 돌려준다."""
    cand = [r for r in rows if _rate(r.fpr) <= fpr_cap]
    if not cand:
        return current, "FPR 상한을 만족하는 격자 없음 → 현재값 유지"
    best_recall = max(_rate(r.typo_recall) for r in cand)
    top = [r for r in cand if _rate(r.typo_recall) == best_recall]
    best = min(top, key=lambda r: (abs(r.t - current), r.t))
    if abs(best.t - current) < 1e-9:
        return current, "선택값이 현재값과 같음"
    cur = next((r for r in rows if abs(r.t - current) < 1e-9), None)
    if cur is None:
        return current, "현재값이 격자에 없음 → 유지"
    lo_b, hi_b = wilson(*best.typo_recall)
    lo_c, hi_c = wilson(*cur.typo_recall)
    if lo_b <= hi_c and lo_c <= hi_b:
        return current, f"후보 {best.t:.2f}의 재현율 구간이 현재값 {current:.2f}의 구간과 겹침 → 현 잠정값 유지, 근거 불충분"
    return best.t, f"후보 {best.t:.2f}의 재현율 구간이 현재값과 겹치지 않음"


# --------------------------------------------------------------------------- 개발셋 → 정답 라벨

def _key(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def expected_products(row: dict[str, Any]) -> list[tuple[str, str]]:
    """문항의 (약 이름, 정답 kind). 개발셋 필드에서만 산출한다. 범위 외·모호하지 않은 기타 칸은 제외."""
    g = row.get("composition_group")
    prods = list(row.get("products") or [])
    if g == "오탈자":
        vn = row.get("variant_name")
        return [(p, KIND_TYPO if p == vn else KIND_REAL) for p in prods]
    if g == "모호":
        return [(p, KIND_AMBIG) for p in prods]
    if g == "근거 없음":
        fake = "fake_name" in (row.get("answer") or {})
        return [(p, KIND_FAKE if fake else KIND_REAL) for p in prods]
    if g in NORMAL_GROUPS:
        return [(p, KIND_REAL) for p in prods]
    return []


def verify_kind(dd: DrugDict, name: str, kind: str) -> bool:
    """사전 조회로 정답 라벨을 확인한다. real은 이름이 사전에서 한 제품으로 정확히 맞고, typo·fake는 정확히 맞지 않아야 한다. 모호는 접두·중간 일치로 후보가 둘 이상."""
    r = dd.lookup_name(name, top_k=router.MAX_CLARIFY_OPTIONS)
    exact = (not r.empty) and r.resolved and r.match_type not in (MATCH_BM25, MATCH_PREFIX, MATCH_CONTAINS)
    if kind == KIND_REAL:
        return exact
    if kind in (KIND_TYPO, KIND_FAKE):
        return not exact
    if kind == KIND_AMBIG:
        return (not r.empty) and not r.resolved
    return False


def match_entity(name: str, ents: list[router.Entity]) -> router.Entity | None:
    """기대 약 이름을 덮는 엔티티(공백 제거 후 한쪽이 다른 쪽에 포함, 2자 이상). 여럿이면 가장 긴 raw."""
    nk = _key(name)
    hits = [e for e in ents if len(_key(e.raw)) >= 2 and (_key(e.raw) in nk or nk in _key(e.raw))]
    return max(hits, key=lambda e: len(_key(e.raw))) if hits else None


@dataclass
class Collected:
    obs: list[Obs] = field(default_factory=list)
    n_questions: int = 0
    dropped_label: list[tuple[str, str]] = field(default_factory=list)  # 사전 확인에서 정답 라벨과 어긋나 제외된 (이름, kind)
    missed: list[tuple[str, str, str]] = field(default_factory=list)  # (질문, 기대 약, kind) 엔티티로 못 잡음
    false_ents: list[tuple[str, str]] = field(default_factory=list)  # (질문, 엉뚱한 엔티티 raw)
    prefix_single: list[tuple[str, str, bool]] = field(default_factory=list)  # (질문, raw, ambiguous?) 후보 1개 접두·중간 일치
    n_expected: int = 0
    n_caught: int = 0
    n_entities: int = 0


def collect(rows: list[dict[str, Any]], dd: DrugDict, t: float, nf: float = 0.0) -> Collected:
    old, old_nf = router.TYPO_SCORE_MAX, router.NOT_FOUND_SCORE_MAX
    router.TYPO_SCORE_MAX, router.NOT_FOUND_SCORE_MAX = t, nf
    out = Collected()
    try:
        for row in rows:
            exp = expected_products(row)
            if not exp:
                continue
            out.n_questions += 1
            q = row["question"]
            res = router.route_input(q, dd)
            ents = res.entities
            out.n_entities += len(ents)
            covered: set[int] = set()
            for name, kind in exp:
                if not verify_kind(dd, name, kind):
                    out.dropped_label.append((name, kind))
                    continue
                out.n_expected += 1
                e = match_entity(name, ents)
                if e is None:
                    out.missed.append((q, name, kind))
                    out.obs.append(Obs(kind, None))
                    continue
                out.n_caught += 1
                covered.add(id(e))
                top = e.options[0].score if e.options else None
                out.obs.append(Obs(kind, e.status, top, e.match_type))
            for e in ents:
                if id(e) not in covered:
                    out.false_ents.append((q, e.raw))
                if e.match_type in (MATCH_PREFIX, MATCH_CONTAINS) and e.n_candidates == 1:
                    out.prefix_single.append((q, e.raw, res.ambiguous and e.status == router.ST_AMBIGUOUS))
    finally:
        router.TYPO_SCORE_MAX, router.NOT_FOUND_SCORE_MAX = old, old_nf
    return out


# --------------------------------------------------------------------------- 보고

def render(c: Collected, rows: list[GridRow], current: float, chosen: float, why: str) -> str:
    L: list[str] = []
    L.append(f"### 개발셋 {c.n_questions}문항, 기대 약 {c.n_expected}개(사전 확인 통과), 제외 {len(c.dropped_label)}개")
    L.append(f"- (a) 약 이름 추출 재현율: {fmt(c.n_caught, c.n_expected)}")
    L.append(f"- (a) 정밀도(엔티티 중 기대 약을 덮는 것): {fmt(c.n_entities - len(c.false_ents), c.n_entities)}, 오탐 엔티티 {len(c.false_ents)}개")
    L.append("")
    L.append("### 격자별 지표 († = 칸당 n≤8, 유의성 주장 금지)")
    L.append("| t | 오탈자 TYPO 재현율 | 오탈자 되묻기 | 모호 되묻기 | 모호→TYPO 오분류 | 정상 불필요 되묻기 | 음성 중 TYPO(FPR) | 가상 NOT_FOUND |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        mark = " ◀현재" if abs(r.t - current) < 1e-9 else ""
        L.append(f"| {r.t:.2f}{mark} | {fmt(*r.typo_recall)} | {fmt(*r.typo_clarify)} | {fmt(*r.ambig_clarify)} | {fmt(*r.ambig_as_typo)} | "
                 f"{fmt(*r.real_unneeded)} | {fmt(*r.fpr)} | {fmt(*r.fake_notfound)} |")
    L.append("")
    L.append(f"### 선택: {chosen:.2f} (현재 {current:.2f}) — {why}")
    L.append("")
    L.append("### (c) 후보 1개 접두·중간 일치 되묻기 유지(AG-05-01 A)")
    n1 = len(c.prefix_single)
    k1 = sum(1 for *_, amb in c.prefix_single if amb)
    L.append(f"- 후보가 정확히 1개인 접두·중간 일치 엔티티 {n1}개 중 자동 확정되지 않고 되묻기로 남음: {fmt(k1, n1)}")
    return "\n".join(L)


def render_nf(rows: list[NfRow], current_nf: float, chosen: float, why: str) -> str:
    L = ["### AG-05-02 A: NOT_FOUND 기준값 격자(BM25 1위 점수 ≤ 값이면 NOT_FOUND, 후보 제시 유지. † = 칸당 n≤8, 유의성 주장 금지)",
         "| nf | 가상 약 NOT_FOUND(재현율) | 오탈자→NOT_FOUND | 모호→NOT_FOUND | 정상→NOT_FOUND | 전체 오분류(FPR) | 오탈자 TYPO 유지 |",
         "|---|---|---|---|---|---|---|"]
    for r in rows:
        mark = " ◀현재" if abs(r.nf - current_nf) < 1e-9 else ""
        L.append(f"| {r.nf:.2f}{' (비활성)' if r.nf == 0.0 else ''}{mark} | {fmt(*r.fake_nf)} | {fmt(*r.typo_nf)} | {fmt(*r.ambig_nf)} | {fmt(*r.real_nf)} | "
                 f"{fmt(*r.all_nf)} | {fmt(*r.typo_recall)} |")
    L += ["", f"### 선택: {chosen:.2f} (현재 {current_nf:.2f}) — {why}"]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=None, help="마크다운 결과를 저장할 경로(선택)")
    ap.add_argument("--cases", type=int, default=10, help="오탐·누락 사례 상위 개수")
    a = ap.parse_args()
    if not DICT_PATH.exists():
        print(f"사전 없음: {DICT_PATH}", file=sys.stderr)
        return 2
    rows = [json.loads(line) for line in DEV_SET.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert all(r.get("set") == "dev" for r in rows), "개발셋이 아닌 문항이 섞임"
    dd = DrugDict.load(DICT_PATH)
    current = router.TYPO_SCORE_MAX
    base = collect(rows, dd, current)
    grid = [measure(base.obs, t) for t in GRID]
    # BM25 점수 기반 재계산이 실제 route_input과 같은지 표본 격자에서 교차 확인
    for t in (GRID[0], current, GRID[-1]):
        direct = measure(collect(rows, dd, t).obs, t)
        via = next(g for g in grid if abs(g.t - t) < 1e-9)
        assert direct == via, f"격자 재계산 불일치 t={t}"
    chosen, why = choose_threshold(grid, current)
    text = render(base, grid, current, chosen, why)
    cur_nf = router.NOT_FOUND_SCORE_MAX
    nf_rows = [measure_nf(base.obs, current, v) for v in sorted({*NF_GRID, cur_nf})]
    for v in (NF_GRID[1], cur_nf, NF_GRID[-1]):  # 점수 기반 재계산이 실제 route_input과 같은지 표본 교차 확인
        assert measure_nf(collect(rows, dd, current, v).obs, current, v) == next(r for r in nf_rows if abs(r.nf - v) < 1e-9), f"nf 재계산 불일치 {v}"
    nf_chosen, nf_why = choose_nf(nf_rows)
    text += "\n\n" + render_nf(nf_rows, cur_nf, nf_chosen, nf_why)
    text += "\n\n### 누락 사례(기대 약을 엔티티로 못 잡음)\n" + "\n".join(f"- [{k}] {n} ← {q}" for q, n, k in base.missed[: a.cases])
    text += "\n\n### 오탐 사례(엉뚱한 엔티티)\n" + "\n".join(f"- `{raw}` ← {q}" for q, raw in base.false_ents[: a.cases])
    text += f"\n\n(누락 총 {len(base.missed)}개, 오탐 총 {len(base.false_ents)}개)"
    if base.dropped_label:
        text += "\n\n### 사전 확인에서 제외된 라벨\n" + "\n".join(f"- {n} ({k})" for n, k in base.dropped_label[:20])
    print(text)
    if a.out:
        a.out.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
