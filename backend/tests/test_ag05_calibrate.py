"""AG-05-01: `backend/scripts/calibrate_router.py`의 집계·구간 계산·격자 선택 규칙 단위 시험(합성 소재료, 파일·외부 호출 없음)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

import calibrate_router as C  # noqa: E402

from app.agent import router as R  # noqa: E402
from app.tools.drug_dict import MATCH_BM25, MATCH_PREFIX  # noqa: E402


def test_wilson_basic():
    lo, hi = C.wilson(0, 0)
    assert (lo, hi) == (0.0, 1.0)
    lo, hi = C.wilson(10, 10)
    assert hi == 1.0 and 0.65 < lo < 0.75  # 10/10의 Wilson 하한은 약 0.72
    lo, hi = C.wilson(5, 10)
    assert lo < 0.5 < hi


def test_fmt_marks_small_n():
    assert "†" in C.fmt(3, 8)
    assert "†" not in C.fmt(9, 20)
    assert "n=0" in C.fmt(0, 0)


def test_grid_is_030_to_090_step_005():
    assert C.GRID[0] == 0.30 and C.GRID[-1] == 0.90 and len(C.GRID) == 13
    assert all(abs((b - a) - 0.05) < 1e-9 for a, b in zip(C.GRID, C.GRID[1:], strict=False))


def test_status_at_only_bm25_depends_on_threshold():
    o = C.Obs(C.KIND_TYPO, R.ST_AMBIGUOUS, 0.5, MATCH_BM25)
    assert C.status_at(o, 0.4) == R.ST_AMBIGUOUS
    assert C.status_at(o, 0.5) == R.ST_TYPO  # top <= t
    p = C.Obs(C.KIND_AMBIG, R.ST_AMBIGUOUS, 0.9, MATCH_PREFIX)
    assert C.status_at(p, 0.3) == R.ST_AMBIGUOUS == C.status_at(p, 0.9)
    assert C.status_at(C.Obs(C.KIND_REAL, None), 0.6) is None


def _synthetic() -> list[C.Obs]:
    return [
        # 오탈자 4개: BM25 점수 0.2, 0.4, 0.55, 0.7
        *[C.Obs(C.KIND_TYPO, R.ST_AMBIGUOUS, s, MATCH_BM25) for s in (0.2, 0.4, 0.55, 0.7)],
        C.Obs(C.KIND_TYPO, None),  # 못 잡음: 분모에서 빠진다
        # 모호 2개(접두), 1개 BM25 0.5
        C.Obs(C.KIND_AMBIG, R.ST_AMBIGUOUS, 0.9, MATCH_PREFIX),
        C.Obs(C.KIND_AMBIG, R.ST_AMBIGUOUS, 0.5, MATCH_BM25),
        # 정상 3개: 1개 불필요 되묻기
        C.Obs(C.KIND_REAL, R.ST_RESOLVED, None, "exact"),
        C.Obs(C.KIND_REAL, R.ST_RESOLVED, None, "normalized"),
        C.Obs(C.KIND_REAL, R.ST_AMBIGUOUS, None, MATCH_PREFIX),
        # 가상 2개
        C.Obs(C.KIND_FAKE, R.ST_NOT_FOUND),
        C.Obs(C.KIND_FAKE, R.ST_AMBIGUOUS, 0.3, MATCH_BM25),
    ]


def test_measure_counts():
    r = C.measure(_synthetic(), 0.5)
    assert r.typo_recall == (2, 4)  # 0.2, 0.4
    assert r.typo_clarify == (4, 4)
    assert r.ambig_clarify == (2, 2) and r.ambig_as_typo == (1, 2)  # 0.5 <= 0.5
    assert r.real_unneeded == (1, 3)
    assert r.fpr == (1, 3)  # 음성 = 되묻기로 간 모호 2 + 정상 1, 그중 TYPO는 모호 BM25(0.5) 1
    assert r.fake_notfound == (1, 2)


def test_choose_keeps_current_when_intervals_overlap():
    rows = [C.measure(_synthetic(), t) for t in C.GRID]
    chosen, why = C.choose_threshold(rows, 0.6)
    assert chosen == 0.6 and ("불충분" in why or "같음" in why or "상한" in why)


def _row(t: float, recall: tuple[int, int], fpr: tuple[int, int]) -> C.GridRow:
    z = (0, 1)
    return C.GridRow(t, recall, recall, z, z, z, fpr, z)


def test_choose_changes_when_intervals_disjoint():
    rows = [_row(0.5, (2, 100), (0, 100)), _row(0.6, (5, 100), (0, 100)), _row(0.7, (95, 100), (0, 100))]
    chosen, why = C.choose_threshold(rows, 0.6)
    assert chosen == 0.7 and "겹치지 않" in why


def test_choose_respects_fpr_cap():
    rows = [_row(0.6, (50, 100), (0, 100)), _row(0.8, (99, 100), (50, 100))]  # 0.8은 FPR 50% → 후보 아님
    chosen, _ = C.choose_threshold(rows, 0.6)
    assert chosen == 0.6


def test_choose_tie_prefers_closest_to_current():
    rows = [_row(0.5, (90, 100), (0, 100)), _row(0.6, (90, 100), (0, 100)), _row(0.9, (90, 100), (0, 100))]
    chosen, why = C.choose_threshold(rows, 0.6)
    assert chosen == 0.6 and "같음" in why


def test_choose_no_candidate_keeps_current():
    rows = [_row(0.6, (50, 100), (60, 100))]
    chosen, why = C.choose_threshold(rows, 0.6)
    assert chosen == 0.6 and "상한" in why


def test_expected_products_labels():
    typo = {"composition_group": "오탈자", "products": ["가나정", "다라정"], "variant_name": "가나정"}
    assert C.expected_products(typo) == [("가나정", C.KIND_TYPO), ("다라정", C.KIND_REAL)]
    amb = {"composition_group": "모호", "products": ["마바"]}
    assert C.expected_products(amb) == [("마바", C.KIND_AMBIG)]
    fake = {"composition_group": "근거 없음", "products": ["사아"], "answer": {"fake_name": "사아"}}
    assert C.expected_products(fake) == [("사아", C.KIND_FAKE)]
    topic = {"composition_group": "근거 없음", "products": ["사아"], "answer": {"topic": "x"}}
    assert C.expected_products(topic) == [("사아", C.KIND_REAL)]
    assert C.expected_products({"composition_group": "범위 외", "products": ["아자"]}) == []
    assert C.expected_products({"composition_group": "정상-병용", "products": ["x", "y"]}) == [("x", C.KIND_REAL), ("y", C.KIND_REAL)]


def test_match_entity_by_containment():
    def ent(raw: str) -> R.Entity:
        return R.Entity(raw=raw, normalized=raw, status="NOT_FOUND", branch="근거 없음")

    ents = [ent("엉뚱"), ent("임프란타연질캡슐")]
    assert C.match_entity("임프란타연질캡슐 25mg", ents) is ents[1]  # 공백 제거 뒤 포함
    assert C.match_entity("전혀다른정", ents) is None


def test_collect_restores_threshold(monkeypatch):
    monkeypatch.setattr(R, "TYPO_SCORE_MAX", 0.6)
    C.collect([], None, 0.3)  # type: ignore[arg-type]
    assert R.TYPO_SCORE_MAX == 0.6


def test_dev_set_never_touches_sealed():
    src = (ROOT / "backend" / "scripts" / "calibrate_router.py").read_text(encoding="utf-8")
    assert 'dev_set.jsonl' in src
    assert "open(" not in src.replace("SEALED", "") or "test_set" not in src.split("DEV_SET =")[1].split("\n")[0]
    assert "test_set.SEALED" not in src.split('"""', 2)[2]  # 독스트링 밖에서 시험셋 경로를 쓰지 않는다


@pytest.mark.parametrize("k,n", [(0, 5), (5, 5), (3, 20)])
def test_wilson_within_unit_interval(k, n):
    lo, hi = C.wilson(k, n)
    assert 0.0 <= lo <= k / n <= hi <= 1.0


# --------------------------------------------------------------------------- AG-05-02 A: NOT_FOUND 기준값 보정

def test_nf_grid_is_disabled_plus_015_to_060():
    assert C.NF_GRID[0] == 0.0 and C.NF_GRID[1] == 0.15 and C.NF_GRID[-1] == 0.60 and len(C.NF_GRID) == 11


def test_status_at_nf_applies_before_typo_and_only_to_bm25():
    o = C.Obs(C.KIND_FAKE, R.ST_TYPO, 0.3, MATCH_BM25)
    assert C.status_at(o, 0.6, 0.0) == R.ST_TYPO  # 비활성
    assert C.status_at(o, 0.6, 0.3) == R.ST_NOT_FOUND  # top <= nf
    assert C.status_at(o, 0.6, 0.29) == R.ST_TYPO
    p = C.Obs(C.KIND_AMBIG, R.ST_AMBIGUOUS, 0.9, MATCH_PREFIX)
    assert C.status_at(p, 0.6, 0.6) == R.ST_AMBIGUOUS  # 접두 일치는 nf로 안 바뀐다
    assert C.status_at(C.Obs(C.KIND_FAKE, None), 0.6, 0.6) is None


def _nf_obs() -> list[C.Obs]:
    return [
        *[C.Obs(C.KIND_FAKE, R.ST_TYPO, s, MATCH_BM25) for s in (0.2, 0.3, 0.4)],
        C.Obs(C.KIND_FAKE, R.ST_NOT_FOUND),
        *[C.Obs(C.KIND_TYPO, R.ST_TYPO, s, MATCH_BM25) for s in (0.35, 0.5)],
        C.Obs(C.KIND_AMBIG, R.ST_AMBIGUOUS, 0.9, MATCH_PREFIX),
        C.Obs(C.KIND_REAL, R.ST_RESOLVED, None, "exact"),
    ]


def test_measure_nf_counts():
    r = C.measure_nf(_nf_obs(), 0.6, 0.35)
    assert r.fake_nf == (3, 4)  # 0.2·0.3 + 원래 NOT_FOUND
    assert r.typo_nf == (1, 2)  # 0.35
    assert r.all_nf == (1, 4) and r.typo_recall == (1, 2)
    assert C.measure_nf(_nf_obs(), 0.6, 0.0).fake_nf == (1, 4)


def _nrow(nf: float, fake: tuple[int, int], typo: tuple[int, int], allx: tuple[int, int]) -> C.NfRow:
    z = (0, 1)
    return C.NfRow(nf, fake, typo, z, z, allx, z)


def test_choose_nf_keeps_disabled_when_intervals_overlap():
    rows = [_nrow(0.0, (1, 13), (0, 17), (0, 156)), _nrow(0.2, (3, 13), (1, 17), (1, 156))]
    v, why = C.choose_nf(rows)
    assert v == 0.0 and "근거 불충분" in why


def test_choose_nf_changes_only_when_disjoint_and_within_caps():
    rows = [_nrow(0.0, (5, 100), (0, 100), (0, 100)), _nrow(0.3, (90, 100), (5, 100), (2, 100))]
    v, why = C.choose_nf(rows)
    assert v == 0.3 and "겹치지 않" in why


@pytest.mark.parametrize("typo,allx", [((20, 100), (1, 100)), ((5, 100), (10, 100))])
def test_choose_nf_respects_caps(typo, allx):
    rows = [_nrow(0.0, (5, 100), (0, 100), (0, 100)), _nrow(0.4, (95, 100), typo, allx)]
    v, why = C.choose_nf(rows)
    assert v == 0.0 and "상한" in why


def test_choose_nf_tie_prefers_lower_value():
    rows = [_nrow(0.0, (5, 100), (0, 100), (0, 100)), _nrow(0.2, (90, 100), (1, 100), (1, 100)), _nrow(0.3, (90, 100), (1, 100), (1, 100))]
    assert C.choose_nf(rows)[0] == 0.2


def test_choose_nf_no_gain_keeps_disabled():
    rows = [_nrow(0.0, (5, 13), (0, 17), (0, 17)), _nrow(0.2, (5, 13), (0, 17), (0, 17))]
    v, why = C.choose_nf(rows)
    assert v == 0.0 and "근거 불충분" in why


def test_collect_restores_both_thresholds(monkeypatch):
    monkeypatch.setattr(R, "TYPO_SCORE_MAX", 0.6)
    monkeypatch.setattr(R, "NOT_FOUND_SCORE_MAX", 0.0)
    C.collect([], None, 0.3, 0.2)  # type: ignore[arg-type]
    assert (R.TYPO_SCORE_MAX, R.NOT_FOUND_SCORE_MAX) == (0.6, 0.0)
