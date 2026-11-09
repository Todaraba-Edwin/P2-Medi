"""풀의 오탈자 짝을 variants.py 규칙(오탈자 14·축약 3·표기 3 비율)으로 다시 만든다. LLM 호출 없음."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import _common as c
import variants as V
for name in ("dev", "test"):
    p = c.OUT / f"pool_{name}.jsonl"
    rows = [json.loads(l) for l in open(p)]
    n = {"오탈자": 0, "축약": 0, "표기": 0}
    for r in rows:
        for k in ("typo_question", "typo_name"):
            r.pop(k, None)
        if r["type"].startswith("정상-") and r["type"] not in ("정상-응급", "정상-목록에없는약") and r.get("questions"):
            nm = r["products"][0]
            if nm in r["questions"][0]:
                v, out = V.make(nm, r["id"])
                if out != nm:
                    r.update(variant=v, variant_name=out, variant_question=r["questions"][0].replace(nm, out, 1))
                    n[v] += 1
    with open(p, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(name, n)
