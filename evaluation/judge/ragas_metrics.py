"""AG-11 Ragas 3지표(PJ2-RFP.md 9.3절: 검색 정확도 = Context Precision·Recall, 답변 충실도 = Faithfulness)를 `ragas` 패키지 없이
judge(`sonnet_judge.SonnetJudge`, 루브릭 J1·J2) 위에 같은 정의로 계산한다(RFP-26 §7.2 "부적합하면 같은 정의를 자체 rubric judge로 구현").

정의(Ragas 문서의 공식 그대로, 지표 정의는 9.3절을 바꾸지 않는다):
  - Faithfulness = (답의 주장 중 근거 청크로 뒷받침되는 수) / (답의 주장 수). 주장은 J1 규칙(권유·고정 문구·질문 제외)으로 센다
    → RFP-28 §8.3의 "Ragas가 권유 문장까지 주장으로 세어 좋은 답도 0.5~0.875"를 J1 규칙으로 해소한다. 주장 0개면 None(분모 없음).
  - Context Precision@K = Σ_k (precision@k × v_k) / (관련 청크 수), v_k = k번째 청크가 정답 근거(reference)와 관련(J2 `chunks`).
    관련 청크가 0개면 None. 청크 순서 = 검색 순위.
  - Context Recall = (정답 근거의 주장 중 청크로 돌릴 수 있는 수) / (정답 근거의 주장 수)(J2 `reference_claims`). 주장 0개면 None.
  - 근거 청크 ID Recall(코드, LLM 없음, RFP-26-02): 정답 근거 ID 목록(`answer_evidence.evidence_ids`) 중 도구가 돌려준·인용된 ID에 든 비율.
    `contra_pair:A:B`는 코드 순서와 무관하게 본다(`eval_metrics._norm_eid`). 근거 묶음 Recall(멀티홉, 하나라도 빠지면 실패)은 같은 입력의 all-or-nothing.
  - C0(LLM 단독, 9.5절): 검색 컨텍스트가 없어 Precision·Recall은 **해당 없음**(None)이고 Faithfulness는 정답 근거 청크를 컨텍스트로 준다
    (`mode="reference_as_context"`).
  - 대상 문항(9.3절 "근거 검색이 필요한 정상·모호 문항"): `ragas_applicable`. 모호 문항은 되묻기로 끝나 주장·검색이 없으면 세 값이 모두 None이라
    분모에서 빠진다(결정 후보, 보고 참조).
집계는 평균·n·표준편차와 정규 근사 95% 구간(잠정, 9.3절 "평균 점수와 구간")이다. 이 모듈은 외부 호출을 하지 않는다(judge를 주입받는다).
"""

from __future__ import annotations

import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
for p in (str(HERE.parent), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import eval_metrics as M  # noqa: E402
import sonnet_judge as SJ  # noqa: E402

RAGAS_VERSION = "ragas-rubric@v1"  # 이 모듈의 계산 규칙 버전(결과 파일에 기록, 측정 중 변경 금지)
RAGAS_BRANCHES = ("정상", "모호")  # 9.3절 대상 문항
MODE_RETRIEVED, MODE_REFERENCE = "retrieved", "reference_as_context"
Z95 = M.Z95


# --------------------------------------------------------------------------- 공식(순수 함수)

def faithfulness(supported: Sequence[bool]) -> float | None:
    return round(sum(map(bool, supported)) / len(supported), 4) if supported else None


def context_precision(relevant: Sequence[bool]) -> float | None:
    """Σ_k precision@k·v_k / Σ v_k. 예: [T, F, T] → (1/1 + 2/3) / 2 = 0.8333."""
    hits = 0
    acc = 0.0
    for k, v in enumerate(relevant, 1):
        if v:
            hits += 1
            acc += hits / k
    return round(acc / hits, 4) if hits else None


def context_recall(attributed: Sequence[bool]) -> float | None:
    return round(sum(map(bool, attributed)) / len(attributed), 4) if attributed else None


def chunk_id_recall(expected_ids: Iterable[str], got_ids: Iterable[str]) -> dict[str, Any]:
    """근거 청크 ID Recall(코드). 반환 k/n·비율·빠진 ID·묶음(all-or-nothing) 여부. 기대 ID가 없으면 n=0·rate None."""
    want = {M._norm_eid(str(x)) for x in expected_ids if x}
    got = {M._norm_eid(str(x)) for x in got_ids if x}
    missing = sorted(x for x in want if x not in got)
    k, n = len(want) - len(missing), len(want)
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "missing": missing, "bundle_complete": (not missing) if n else None}


# --------------------------------------------------------------------------- 문항 하나

def ragas_applicable(item: Mapping[str, Any]) -> bool:
    return item.get("branch_label") in RAGAS_BRANCHES


def ragas_item(judge: SJ.SonnetJudge, item: Mapping[str, Any], answer: Mapping[str, Any], *, contexts: Sequence[SJ.Context] | None = None,
               tool_evidence_ids: Iterable[str] = (), end_reason: str | None = None, mode: str = MODE_RETRIEVED,
               j1: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """문항 하나의 3지표 + 청크 ID Recall. judge 호출: J1(주장이 있을 때) 1회 + J2(검색 청크가 있을 때, C0는 없음) 1회.
    `contexts`를 주지 않으면 최종 답의 근거 상세에서 만든다(`sonnet_judge.contexts_from_answer`).
    `j1`에 같은 문항·같은 청크로 이미 받은 J1 결과를 주면 다시 부르지 않는다(러너가 안전 응답 채점에서 받은 J1을 넘긴다: 같은 답을 두 번 채점하지 않게)."""
    if mode not in (MODE_RETRIEVED, MODE_REFERENCE):
        raise SJ.JudgeError(f"mode는 {MODE_RETRIEVED}|{MODE_REFERENCE}: {mode!r}")
    ctx = list(contexts) if contexts is not None else SJ.contexts_from_answer(answer)
    if mode == MODE_REFERENCE:
        ctx = [SJ.Context("reference", str(item.get("reference") or ""))] if item.get("reference") else []
    inp = SJ.input_from_item(item, answer, ctx)
    out: dict[str, Any] = {"version": RAGAS_VERSION, "mode": mode, "n_contexts": len(ctx),
                           "faithfulness": None, "context_precision": None, "context_recall": None, "judge": {}}
    if SJ.has_claims(answer, end_reason):
        reused = j1 is not None
        j1 = j1 if j1 is not None else judge.score_rubric("J1", inp)
        out["judge"]["J1"] = {"reused": True, "status": j1.get("status")} if reused else j1  # 재사용이면 원본은 `row["judge"]`에 있다
        if j1.get("status") == SJ.STATUS_OK:
            out["faithfulness"] = faithfulness([bool(c.get("supported")) for c in j1.get("claims") or []])
    if mode == MODE_RETRIEVED and ctx:
        j2 = judge.score_rubric("J2", inp)
        out["judge"]["J2"] = j2
        if j2.get("status") == SJ.STATUS_OK:
            by_id = {str(c.get("id")): bool(c.get("relevant")) for c in j2.get("chunks") or []}
            out["context_precision"] = context_precision([by_id.get(c.id, False) for c in ctx])  # 청크 순서는 우리가 준 순서
            out["context_recall"] = context_recall([bool(c.get("attributed")) for c in j2.get("reference_claims") or []])
    ids = (item.get("answer_evidence") or {}).get("evidence_ids") or []
    cited = [c.get("evidence_id") for c in answer.get("citations") or [] if isinstance(c, Mapping)]
    out["chunk_id_recall"] = chunk_id_recall(ids, [*tool_evidence_ids, *cited])
    out["judge_error"] = any(v.get("status") == SJ.STATUS_ERROR for v in out["judge"].values())  # 재사용 J1의 오류도 센다
    return out


# --------------------------------------------------------------------------- 집계

def _mean_ci(xs: Sequence[float]) -> dict[str, Any]:
    n = len(xs)
    if n == 0:
        return {"n": 0, "mean": None, "sd": None, "ci95": None, "claim": M.claim_level(0)}
    mean = sum(xs) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    half = Z95 * sd / math.sqrt(n) if n > 1 else None
    ci = [round(max(0.0, mean - half), 4), round(min(1.0, mean + half), 4)] if half is not None else None
    return {"n": n, "mean": round(mean, 4), "sd": round(sd, 4), "ci95": ci, "claim": M.claim_level(n),
            "ci_note": "정규 근사(잠정). n≤8이면 유의성 주장 안 함(9.1절 5번)"}


def aggregate_ragas(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """문항별 `ragas_item` 결과 → 지표별 평균·구간(값이 None인 문항은 그 지표의 분모에서 뺀다), 청크 ID Recall k/n(문항 단위 = 모든 기대 ID 포함),
    judge 오류 수. 9.3절 목표는 "기준선 대비 개선"이라 목표 수치가 없다."""
    out: dict[str, Any] = {"version": RAGAS_VERSION, "n_items": len(rows)}
    for key in ("faithfulness", "context_precision", "context_recall"):
        vals = [float(r[key]) for r in rows if r.get(key) is not None]
        out[key] = {**_mean_ci(vals), "n_missing": len(rows) - len(vals)}
    with_ids = [r["chunk_id_recall"] for r in rows if (r.get("chunk_id_recall") or {}).get("n")]
    out["chunk_id_recall"] = {"items_all_ids": M.kn(sum(bool(r["bundle_complete"]) for r in with_ids), len(with_ids)),
                              "ids": M.kn(sum(r["k"] for r in with_ids), sum(r["n"] for r in with_ids)),
                              "note": "코드 채점(LLM 없음). items_all_ids = 기대 근거 ID를 모두 확보한 문항(근거 묶음 Recall과 같은 규칙)"}
    out["judge_errors"] = sum(bool(r.get("judge_error")) for r in rows)
    out["by_mode"] = {m: sum(r.get("mode") == m for r in rows) for m in (MODE_RETRIEVED, MODE_REFERENCE)}
    return out
