"""④ Ragas + Claude Sonnet 5.5 한국어 소량 시험. 실행: ragas 0.4.3 + langchain-community<0.3.32 환경(메인 .venv에서는 import 실패, RFP-28 §7).
S3의 합성 답변(good/unsupported)과 근거를 입력으로 Faithfulness가 한국어에서 동작하고 불량을 낮게 주는지 본다."""
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import _common as c
from langchain_anthropic import ChatAnthropic
from langchain_core.callbacks import BaseCallbackHandler
from ragas.llms import LangchainLLMWrapper
from ragas.dataset_schema import SingleTurnSample
from ragas.metrics import Faithfulness, LLMContextPrecisionWithReference, LLMContextRecall


class Usage(BaseCallbackHandler):
    def __init__(self):
        self.i = self.o = self.n = 0

    def on_llm_end(self, response, **kw):
        for gens in response.generations:
            for g in gens:
                m = getattr(getattr(g, "message", None), "usage_metadata", None) or {}
                self.i += m.get("input_tokens", 0); self.o += m.get("output_tokens", 0); self.n += 1


u = Usage()
llm = LangchainLLMWrapper(ChatAnthropic(model=c.SONNET, max_tokens=2000, thinking={"type": "between_tools"}, callbacks=[u]), bypass_temperature=True)
res = [json.loads(l) for l in open(c.OUT / "judge_dryrun.jsonl")]
pool = {json.loads(l)["id"]: json.loads(l) for l in open(c.OUT / "pool_dev.jsonl")}
picks = []
for r in res:
    if r["rubric"] == "J1" and r["variant"] in ("good", "unsupported", "wrong_value") and len(picks) < 12:
        picks.append(r)
metrics = {"faithfulness": Faithfulness(llm=llm), "ctx_precision": LLMContextPrecisionWithReference(llm=llm), "ctx_recall": LLMContextRecall(llm=llm)}


async def run():
    out = []
    for r in picks:
        b = pool[r["base"]]
        a = b["answer"]
        ctx = [f'{b["source"]}: 제품 {", ".join(b["products"])}, {a["result"]}' + (f', 등급 {a["grade"]}' if a.get("grade") else "") + (f', 상세정보: {a["detail"]}' if a.get("detail") else "")]
        ref = f'{", ".join(b["products"])}은(는) {a["result"]}이다.' + (f' 등급은 {a["grade"]}이다.' if a.get("grade") else "") + (f' 상세정보: {a["detail"]}' if a.get("detail") else "")
        s = SingleTurnSample(user_input=r["q"], response=r["answer"], retrieved_contexts=ctx, reference=ref)
        row = {"base": r["base"], "variant": r["variant"]}
        for k, m in metrics.items():
            try:
                row[k] = await m.single_turn_ascore(s)
            except Exception as e:  # noqa: BLE001
                row[k] = f"ERR {type(e).__name__}: {str(e)[:120]}"
        out.append(row)
        print(row, flush=True)
    return out


out = asyncio.run(run())
cost = u.i * 2 / 1e6 + u.o * 10 / 1e6
led = c.spent() + cost
c.LEDGER.write_text(json.dumps({"usd": round(led, 6)}))
(c.OUT / "ragas_ko.json").write_text(json.dumps(dict(rows=out, tokens=dict(i=u.i, o=u.o, calls=u.n), cost=round(cost, 4)), ensure_ascii=False, indent=1))
print("LLM 호출", u.n, "입력", u.i, "출력", u.o, "비용 $", round(cost, 3), "누적 $", round(led, 3))
