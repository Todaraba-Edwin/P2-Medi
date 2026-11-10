"""mock 5개 세트(M1~M5)를 처음부터 다시 검증하고, 세트별 비용을 호출 기록(mock/calls.jsonl)에서 집계해 manifest에 반영한다. API 호출 없음.
사용법: python evaluation/mock_gen/verify_all.py   → mock/verify_report.json
"""
import collections, json, re, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import _common as C, meta, trajectory as T, judge_schema as JS, validator_probe as VP  # noqa: E402

ROOT = meta.ROOT
OUT = meta.OUT
rep = {}


def jl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8")]


# ---- 공통: 모든 레코드에 mock 표시·모델·세트 버전 ----
def stamp_ok(recs):
    return sum(1 for r in recs if r.get("mock") is True and r.get("set_version") and r.get("generated_by"))


# ---- M2 ----
tr = jl(OUT / "traces/traces.jsonl")
bad = [r["case_id"] for r in tr if T.score(r)["verdict"] != r["expected_verdict"]["verdict"] or set(r["expected_verdict"]["reasons"]) != set(T.score(r)["reasons"])]
rep["M2"] = dict(n=len(tr), stamped=stamp_ok(tr), rescore_mismatch=bad, by_verdict=dict(collections.Counter(r["expected_verdict"]["verdict"] for r in tr)))

# ---- M1 (구조·문장 규칙·스트림 순서·파일 원본 대조는 m1_chat --finalize가 수행) ----
p = subprocess.run([sys.executable, str(Path(__file__).parent / "m1_chat.py"), "--finalize"], capture_output=True, text=True)
resp = jl(OUT / "chat_responses/responses.jsonl")
idx = json.load(open(OUT / "chat_responses/index.json"))
rep["M1"] = dict(n=len(resp), stamped=stamp_ok(resp), finalize_output=p.stdout.strip().splitlines()[-1], checks_ok=sum(1 for i in idx if i["checks_ok"]),
                 llm_points=sum(i.get("llm_points") or 0 for i in idx), fallback_points=sum(i.get("fallback_points") or 0 for i in idx),
                 emergency_first_event=all(json.loads(open(OUT / f"chat_responses/streams/{r['id']}.jsonl", encoding="utf-8").readline())["event"] == "emergency" for r in resp if r["response"] and r["response"]["emergency"]["detected"]))

# ---- M3 ----
j = jl(OUT / "judge_outputs/judge_outputs.jsonl") + jl(OUT / "judge_outputs/judge_outputs_extra.jsonl")
bad = []
for r in j:
    for a in r["attempts"]:
        c = JS.classify(a["raw_output"], r["rubric_family"])
        if (c["strict_ok"], c["lenient_ok"], c["errors"]) != (a["strict_ok"], a["lenient_ok"], a["errors"]):
            bad.append(r["case_id"])
    if r["kind"] == "valid_output" and JS.validate(r["parsed"], r["rubric_family"]):
        bad.append(r["case_id"])
extra = [r for r in j if r.get("source") == "extra"]
valid = [r for r in j if r["kind"] == "valid_output"]
rep["M3"] = dict(n=len(j), stamped=stamp_ok(j), by_kind=dict(collections.Counter(r["kind"] for r in j)), reparse_mismatch=sorted(set(bad)),
                 valid_by_rubric=dict(collections.Counter(r["rubric_family"] for r in valid)),
                 label_mismatch_vs_construction=sum(1 for r in valid if r["parsed"]["overall_pass"] != r["expected_pass_by_construction"]),
                 label_mismatch_ids=[r["case_id"] for r in valid if r["parsed"]["overall_pass"] != r["expected_pass_by_construction"]],
                 extra_n=len(extra), extra_mismatch=sum(1 for r in extra if r["construction_label_mismatch"]))

# ---- M4 ----
import m4_templates as M4  # noqa: E402
qt = jl(OUT / "question_templates/question_templates.jsonl")
names_re = M4.product_names_re()
spec = {(s["type"], s["subtype"]): s for s in M4.SPECS}
bad = []
for r in qt:
    v, _ = M4.check_template(r["template"], spec[(r["type"], r["subtype"])], names_re, [])
    if v:
        bad.append((r["id"], v))
rep["M4"] = dict(n=len(qt), stamped=stamp_ok(qt), rule_violations=bad, by_type=dict(collections.Counter(r["type"] for r in qt)),
                 by_subtype=dict(collections.Counter(f"{r['type']}/{r['subtype']}" for r in qt)))

# ---- M5 ----
vp = jl(OUT / "validator_pairs/validator_pairs.jsonl")
bad = []
for r in vp:
    want = {(v["sentence_idx"], v["code"]) for v in r["expected"]["violations"] if v["detectable_by_rules"]}
    got = VP.probe(r)
    extra_ = {x for x in got - want if x[1] not in r["expected"].get("also_acceptable_codes", [])}
    if (want - got) or extra_:
        bad.append(r["pair_id"])
rep["M5"] = dict(n=len(vp), stamped=stamp_ok(vp), probe_mismatch=bad, by_verdict=dict(collections.Counter(r["expected"]["verdict"] for r in vp)),
                 by_tier=dict(collections.Counter(r["tier"] for r in vp)), semantic_only=sum(1 for r in vp for v in r["expected"]["violations"] if not v["detectable_by_rules"]))

# ---- 비용: 호출 기록을 세트별로 집계, 원장과 대조 ----
calls = jl(C.CALLS)
tot = sum(c["usd"] for c in calls)
led = json.load(open(C.LEDGER))["usd"]
by = collections.defaultdict(float)
for c in calls:
    by[c["tag"].split("-")[0]] += c["usd"]
byset = {"M1": by["m1"], "M3": by["m3"], "M4": by["m4"], "M5": by["m5"]}
rep["cost"] = dict(calls=len(calls), calls_sum_usd=round(tot, 4), ledger_usd=led, diff=round(tot - led, 6), cap_usd=C.CAP_USD, by_set={k: round(v, 4) for k, v in byset.items()},
                   by_model=dict(collections.Counter(c["model"] for c in calls)), debug_calls=sum(1 for c in calls if "debug" in c["tag"]))
for sdir, key in (("chat_responses", "M1"), ("judge_outputs", "M3"), ("question_templates", "M4"), ("validator_pairs", "M5")):
    mf = OUT / sdir / "manifest.json"
    m = json.loads(mf.read_text(encoding="utf-8"))
    m["cost_usd"] = round(byset[key], 4)
    m["cost_note"] = "data/mock/calls.jsonl의 태그(m1-/m3-/m4-/m5-) 합계. 디버그 호출과 재생성 비용 포함"
    if key == "M3":
        m["counts"].update(total=len(j), valid_main=len(valid) - len(extra), valid_extra=len(extra), label_mismatch_vs_construction=rep["M3"]["label_mismatch_vs_construction"], extra_mismatch=rep["M3"]["extra_mismatch"])
        m["extra_file"] = "judge_outputs_extra.jsonl (evaluation/mock_gen/m3b_extra.py: J4 경계 사례(RFP-28-01)·J1(M1 요약/M5 결함 답변)·J5(M1 근거 없음))"
        m["rubric_wording_note"] = ("본 파일(dry 시험 기반)은 사전 시험의 dry1 문구로 채점했다. RFP-26 §7.5 J1 경계 사례 ③(조회 결과의 부정도 근거로 센다)이 프롬프트에 없어 "
                                    "extra의 J1 중 '목록에 없음' 주장이 unsupported로 판정된 사례가 있다 → judge 보정(RFP-26-03) 때 확인할 것")
    mf.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
# 세트 manifest 존재
rep["manifests"] = {d.name: (d / "manifest.json").exists() for d in OUT.iterdir() if d.is_dir()}

# ---- 비밀·개인정보 검사: 키 모양 문자열, 이메일 ----
leak = []
for f in OUT.rglob("*"):
    if f.is_file() and f.suffix in (".json", ".jsonl", ".md") and f.name != "verify_report.json":
        t = f.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"sk-[A-Za-z0-9_-]{20,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}|SUPABASE_[A-Z_]+=|postgres(ql)?://", t) or re.search(r"[\w.]+@[\w.]+\.[a-z]{2,}", t):
            leak.append(str(f.relative_to(ROOT)))
rep["secret_scan_hits"] = leak
gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
rep["gitignore_has_mock"] = bool(re.search(r"^/?mock/?\s*$", gi, re.M))

ok = (not rep["M2"]["rescore_mismatch"] and rep["M1"]["checks_ok"] == len(idx) and not rep["M3"]["reparse_mismatch"] and not rep["M4"]["rule_violations"] and not rep["M5"]["probe_mismatch"]
      and not leak and rep["cost"]["diff"] == 0 and tot < C.CAP_USD)
rep["ALL_OK"] = ok
(OUT / "verify_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(rep, ensure_ascii=False, indent=1))
