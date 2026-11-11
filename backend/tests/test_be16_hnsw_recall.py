"""BE-16-06 로컬 recall 측정 스크립트의 순수 함수 시험(작은 합성 벡터, 데이터 파일·네트워크 불필요)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import hnsw_recall_local as R  # noqa: E402


def _toy() -> np.ndarray:
    # 2차원 단위원 위의 점들: 각도 0°, 10°, 20°, 90°, 180°
    deg = np.radians([0, 10, 20, 90, 180])
    return R.normalize(np.stack([np.cos(deg), np.sin(deg)], axis=1) * np.array([[1.0], [2.0], [3.0], [0.5], [1.0]]))


def test_normalize_unit_and_zero_row() -> None:
    x = R.normalize(np.array([[3.0, 4.0], [0.0, 0.0]]))
    assert np.allclose(np.linalg.norm(x[0]), 1.0)
    assert np.allclose(x[1], 0.0)  # 0 벡터는 나누기 오류 없이 그대로


def test_exact_topk_excludes_self_and_orders_by_cosine() -> None:
    xn = _toy()
    assert R.exact_topk(xn, [0], k=3) == [[1, 2, 3]]  # 크기와 무관하게 코사인(각도)만 본다
    assert R.exact_topk(xn, [4], k=2) == [[3, 2]]


def test_exact_topk_respects_allowed_and_short_sets() -> None:
    xn = _toy()
    got = R.exact_topk(xn, [0, 0], k=3, allowed=[np.array([0, 3, 4]), np.array([0])])
    assert got == [[3, 4], []]  # 허용 집합 안에서만, 자기 자신은 빠짐


def test_recall_hits_and_recall_at_k() -> None:
    assert R.recall_hits([1, 2, 3], [3, 2, 9], k=3) == 2
    assert R.recall_hits([1, 2, 3, 4], [4, 5, 6], k=3) == 0  # 근사 결과도 top-k까지만 본다
    hit, den = R.recall_at_k([[1, 2], [7], []], [[1, 2], [7, 8], []], k=10)
    assert (hit, den) == (3, 4)  # 정답 수가 k보다 적으면 그 수만 분모


def test_recall_at_k_length_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        R.recall_at_k([[1]], [[1], [2]])


def test_stratified_sample_is_balanced_and_deterministic() -> None:
    groups = {"L1": list(range(0, 10)), "L2": list(range(100, 103)), "L3": list(range(200, 250))}
    a = R.stratified_sample(groups, 10, seed=7)
    assert a == R.stratified_sample(groups, 10, seed=7)
    counts = {k: sum(1 for g, _ in a if g == k) for k in groups}
    assert counts == {"L1": 4, "L2": 3, "L3": 3}  # 나머지 1은 앞 층, L2는 층 크기(3)로 잘림
    assert all(r in groups[g] for g, r in a)


def test_post_filter_drops_self_and_keeps_order() -> None:
    assert R.post_filter([5, 1, 9, 2, 7], ok={1, 2, 5, 7}, self_id=5, k=2) == [1, 2]
    assert R.post_filter([3, 4], ok={9}, self_id=0) == []


def test_hnsw_matches_exact_on_small_set() -> None:
    hnswlib = pytest.importorskip("hnswlib")
    assert hnswlib is not None
    rng = np.random.default_rng(0)
    xn = R.normalize(rng.normal(size=(300, 16)))
    idx = R.build_index(xn)
    q = [0, 50, 150]
    exact = R.exact_topk(xn, q, k=5)
    approx = []
    for qi in q:
        got, ms = R.query_one(idx, xn, qi, k=6, ef=200)
        approx.append([g for g in got if g != qi][:5])
        assert ms >= 0
    assert R.recall_at_k(approx, exact, k=5) == (15, 15)
