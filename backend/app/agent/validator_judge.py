"""AG-07 Validator 2단계: LLM 근거 대조 판정기(프롬프트 판정, **기본 꺼짐**, AG-13 개선 후보).

규칙 검사(`validator.validate`) 다음에 남은 문장(`kept`)마다 "근거 데이터 블록이 이 문장을 뒷받침하는가"를 모델에게 묻고,
뒷받침하지 않거나(UNSUPPORTED) 근거와 반대인(CONTRADICTED) 문장을 지운다. 규칙으로는 못 잡는 근거 없는 일반 주장
("이 성분은 혈관을 확장시켜…")이 대상이다(AG-07 §2 첫 조건의 (프롬프트 판정) 부분).

- **기본 꺼짐**: `JUDGE_ENABLED_DEFAULT = False`. 꺼져 있으면 모델을 부르지 않고 입력을 그대로 돌려준다(이벤트도 없음).
  그래프(`graph/nodes.py`)·평가 러너·서비스 기본 경로는 이 모듈을 부르지 않는다. 연결은 AG-13에서 조건(C3) 하나로만 켠다.
- 판정은 지우기만 한다. 문장을 고쳐 쓰거나 새 문장을 만들지 않는다(고정 문구·판정 항목 줄은 `finalize`가 코드로 붙인다).
- 실패하면 열어 둔다(fail-open): 모델 오류·출력 스키마 위반·문장 순번 불일치면 규칙 검사 결과를 그대로 두고 이벤트만 남긴다.
  규칙 검사(안전 단정·복용 지시·등급값 등, H2·H6·H7·H22·H24)는 이미 끝난 뒤라 안전 장치는 약해지지 않는다.
- 대상: claim_type `fact`·`conclusion` 문장. `guidance`(확인 권유)는 근거 대조 대상이 아니라 보내지 않는다.
- 이벤트 dict는 내용 없는 집계다(문장 원문·사유 글을 넣지 않는다). 모델 출력의 사유도 코드(`reason_code`)만 받는다.
- 모델은 `invoke(messages)`가 dict(구조화 출력)·`JudgeOutput`·JSON 문자열·`.content`가 있는 메시지 중 하나를 돌려주면 된다
  (실제는 `llm.make_chat_model(..., purpose="summary").with_structured_output(judge_json_schema(), method="json_schema", strict=True)`).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from app.agent.tools.contract import render_data_block
from app.agent.validator import _sent  # noqa: PLC2701 — Sentence·dict를 같은 모양으로 읽는 보조를 재사용
from app.llm.prompts import PROMPTS_DIR, split_frontmatter

JUDGE_ENABLED_DEFAULT = False
PROMPT_REF = "validator_judge@v1"
JUDGED_CLAIM_TYPES = frozenset({"fact", "conclusion"})

SUPPORTED, UNSUPPORTED, CONTRADICTED = "SUPPORTED", "UNSUPPORTED", "CONTRADICTED"
# 검사 이름(validator.Issue.check와 같은 자리). 처리는 모두 문장 삭제(DROPPED)
LLM_UNSUPPORTED = "LLM_UNSUPPORTED"
LLM_CONTRADICTED = "LLM_CONTRADICTED"
_CHECK_BY_VERDICT = {UNSUPPORTED: LLM_UNSUPPORTED, CONTRADICTED: LLM_CONTRADICTED}
# 판정기 자체가 실패한 사유(fail-open, 문장은 지우지 않는다)
JUDGE_ERROR = "JUDGE_ERROR"
JUDGE_SCHEMA_INVALID = "JUDGE_SCHEMA_INVALID"
JUDGE_INDEX_MISMATCH = "JUDGE_INDEX_MISMATCH"

PASS, FIXED, FAIL = "PASS", "FIXED", "FAIL"


class JudgeVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    verdict: Literal["SUPPORTED", "UNSUPPORTED", "CONTRADICTED"]
    # 사유 코드만 받는다(자유 글 금지): 근거에 없는 내용·근거와 다른 값·근거 밖 일반 지식·해당 없음
    reason_code: Literal["NOT_IN_EVIDENCE", "VALUE_DIFFERS", "OUTSIDE_KNOWLEDGE", "NONE"]


class JudgeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdicts: list[JudgeVerdict]


def judge_json_schema() -> dict[str, Any]:
    """`with_structured_output(method="json_schema")`에 넘기는 strict 스키마(이름 포함 dict)."""
    from app.agent.llm import to_strict_schema  # langchain_openai import를 판정기를 켤 때만 하도록 늦춘다

    return {"name": "validator_judge", "strict": True, "schema": to_strict_schema(JudgeOutput.model_json_schema())}


def load_prompt(prompts_dir: Path = PROMPTS_DIR, ref: str = PROMPT_REF) -> str:
    """프롬프트 파일 본문(프런트매터 제외)."""
    _, body = split_frontmatter((prompts_dir / f"{ref}.md").read_text(encoding="utf-8"))
    return body.strip()


@dataclass
class JudgeResult:
    status: str = PASS
    kept: list[Any] = field(default_factory=list)
    dropped: list[tuple[int, str]] = field(default_factory=list)   # (입력 문장 순번, 검사 이름)
    calls: int = 0
    skipped: bool = False
    events: list[dict[str, Any]] = field(default_factory=list)


def build_messages(sentences: Sequence[Any], items: list[dict[str, Any]], prompt: str) -> tuple[list[Any], list[int]]:
    """(모델 메시지, 판정에 보낸 문장 순번). 근거와 답 문장을 각각 데이터 블록으로 감싼다(블록 안 지시는 데이터, H8)."""
    from langchain_core.messages import HumanMessage, SystemMessage

    sents = [_sent(s) for s in sentences]
    targets = [i for i, s in enumerate(sents) if s.claim_type in JUDGED_CLAIM_TYPES]
    rows = [{"index": i, "text": sents[i].text, "evidence_ids": sents[i].evidence_ids} for i in targets]
    user = render_data_block("evidence", items) + "\n\n" + render_data_block("answer_sentences", rows)
    return [SystemMessage(prompt), HumanMessage(user)], targets


def parse_output(raw: Any) -> JudgeOutput | None:
    """모델 출력(dict·JudgeOutput·JSON 문자열·메시지)을 검증한다. 맞지 않으면 None."""
    if isinstance(raw, JudgeOutput):
        return raw
    content = getattr(raw, "content", raw)
    try:
        if isinstance(content, (str, bytes)):
            return JudgeOutput.model_validate_json(content)
        return JudgeOutput.model_validate(content)
    except ValidationError:
        return None


def run_judge(
    sentences: Sequence[Any],
    items: list[dict[str, Any]],
    *,
    model: Any = None,
    enabled: bool = JUDGE_ENABLED_DEFAULT,
    prompt: str | None = None,
) -> JudgeResult:
    """규칙 검사를 통과한 문장(`ValidationResult.kept`)을 LLM으로 근거 대조한다. 꺼져 있으면 아무것도 하지 않는다.

    - PASS: 지운 문장 없음(판정기 실패로 열어 둔 경우 포함). FIXED: 일부를 지웠다. FAIL: 입력이 있었는데 남은 문장이 없다
      (그래프에 연결하면 기존 `ALL_SENTENCES_DROPPED`와 같은 되감기·폴백 경로를 탄다).
    """
    sents = list(sentences)
    res = JudgeResult(kept=sents)
    if not enabled:
        res.skipped = True
        return res
    if model is None:
        raise ValueError("판정기를 켰는데 model이 없다")
    messages, targets = build_messages(sents, items, prompt if prompt is not None else load_prompt())
    if not targets:
        res.events.append({"rule": "H1", "event": "VALIDATOR_JUDGE", "status": PASS, "judged": 0, "dropped": 0, "calls": 0})
        return res
    res.calls = 1
    try:
        raw = model.invoke(messages)
    except Exception:  # noqa: BLE001 — 모델 오류는 열어 둔다(규칙 검사 결과 유지). 예외 글은 기록하지 않는다(내용·키 비노출)
        return _open(res, JUDGE_ERROR, len(targets))
    out = parse_output(raw)
    if out is None:
        return _open(res, JUDGE_SCHEMA_INVALID, len(targets))
    by_index = {v.index: v for v in out.verdicts}
    if len(by_index) != len(out.verdicts) or set(by_index) != set(targets):
        return _open(res, JUDGE_INDEX_MISMATCH, len(targets))
    drop = {i: _CHECK_BY_VERDICT[v.verdict] for i, v in by_index.items() if v.verdict != SUPPORTED}
    res.dropped = sorted(drop.items())
    res.kept = [s for i, s in enumerate(sents) if i not in drop]
    if drop:
        res.status = FAIL if not res.kept else FIXED
    reasons: dict[str, int] = {}
    for _, check in res.dropped:
        reasons[check] = reasons.get(check, 0) + 1
    res.events.append({"rule": "H1", "event": "VALIDATOR_JUDGE", "status": res.status, "judged": len(targets),
                       "dropped": len(drop), "calls": res.calls, "reasons": reasons})
    return res


def _open(res: JudgeResult, why: str, judged: int) -> JudgeResult:
    res.events.append({"rule": "H1", "event": "VALIDATOR_JUDGE", "status": PASS, "judged": judged, "dropped": 0,
                       "calls": res.calls, "open_reason": why})
    return res


# ---------------------------------------------------------------------------------------- 실측 CLI(외부 호출, 승인 뒤에만)
def pair_items(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """`data/mock/validator_pairs` 쌍의 청크를 판정기 입력 항목 모양으로 바꾼다(합성 mock, 평가 세트 아님)."""
    return [{"evidence_id": c["id"], "status": "FOUND", "source_kind": "FILE", "layer": c.get("layer"), "title": c.get("title"),
             "text": c.get("text"), "as_of": c.get("as_of")} for c in bundle.get("chunks") or []]


def pair_sentences(pair: dict[str, Any]) -> list[dict[str, Any]]:
    """쌍의 문장 → 판정기 문장(근거 ID가 있으면 fact, 없으면 guidance로 보고 판정에서 뺀다)."""
    return [{"text": s["text"], "evidence_ids": list(s.get("cited_ids") or []), "claim_type": "fact" if s.get("cited_ids") else "guidance"}
            for s in pair.get("sentences") or []]


def main(argv: list[str] | None = None) -> int:
    """`PYTHONPATH=. .venv/bin/python -m app.agent.validator_judge --pairs <jsonl> --categories a,b --yes --max-usd 0.05`

    OpenAI를 부른다(`--yes` 없으면 거부). 비용은 개발 원장(`CostLedger`, bucket `dev`)이 호출 전 guard로 막는다.
    출력은 쌍 ID·기대·판정 집계만(문장 원문 없음).
    """
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--categories", default="unsupported_general_claim,pass_base")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-usd", type=float, default=0.05)
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    if not a.yes:
        print("외부 호출이 있다. 승인 뒤 --yes로 실행한다.", file=sys.stderr)
        return 2
    from app.agent.llm import LedgerCallback, make_chat_model
    from app.config import Settings
    from app.llm.ledger import CostLedger

    cats = set(a.categories.split(","))
    pairs = [p for p in (json.loads(x) for x in Path(a.pairs).read_text(encoding="utf-8").splitlines() if x.strip()) if p.get("category") in cats]
    if a.limit:
        pairs = pairs[: a.limit]
    cb = LedgerCallback(CostLedger(), bucket="dev")
    model = make_chat_model(Settings(), purpose="summary", callbacks=[cb]).with_structured_output(
        judge_json_schema(), method="json_schema", strict=True)
    prompt = load_prompt()
    tally = {"bad_caught": 0, "bad_n": 0, "good_kept": 0, "good_n": 0, "open": 0}
    for p in pairs:
        if cb.cost_usd >= a.max_usd:
            print(f"상한 {a.max_usd} USD 도달, 중단", file=sys.stderr)
            break
        r = run_judge(pair_sentences(p), pair_items(p["bundle"]), model=model, enabled=True, prompt=prompt)
        want = {v["sentence_idx"] for v in (p.get("expected") or {}).get("violations") or [] if not v.get("detectable_by_rules", True)}
        got = {i for i, _ in r.dropped}
        tally["open"] += any("open_reason" in e for e in r.events)
        if want:
            tally["bad_n"] += 1
            tally["bad_caught"] += want <= got
        else:
            tally["good_n"] += 1
            tally["good_kept"] += not got
        print(json.dumps({"pair_id": p.get("pair_id"), "want": sorted(want), "dropped": sorted(got)}, ensure_ascii=False))
    print(json.dumps({**tally, "calls": cb.calls, "cost_usd": round(cb.cost_usd, 6)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
