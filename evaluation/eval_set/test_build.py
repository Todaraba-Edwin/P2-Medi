"""AG-04 평가 세트 검사. pytest로도, 단독으로도 돈다.

    backend/.venv/bin/python -m pytest evaluation/eval_set/test_build.py -q
    backend/.venv/bin/python evaluation/eval_set/test_build.py      # 검사별 k/n 출력

정답 재산출(표본 5건)은 빌더 코드가 아니라 BE-09 조회 도구(`app.tools.lookup.check_contraindications`)로
KIDS 파일을 메모리 SQLite에 표본 성분만 적재해 다시 판정한다(빌더와 다른 경로로 같은 답이 나오는지).

시험셋(`test_set.SEALED.jsonl`) 열람 가드(RFP-26-04, 9.1절 8번): 모듈 수준에서 세트를 읽지 않는다. 시험셋은
`sealed_guard`의 허용(환경변수 `MEDIAGENT_ALLOW_SEALED` + 명시 플래그)이 있을 때만 시험 안에서 읽는다. 명시 플래그는
단독 실행이면 `--allow-sealed`, pytest면 환경변수 `MEDIAGENT_TEST_BUILD_ALLOW_SEALED=1`이다. 허용이 없으면
- 개발셋만 쓰는 검사(두 세트를 도는 검사의 개발셋 몫 포함)는 그대로 돈다.
- 시험셋이 필요한 검사는 파일을 열지 않고 skip한다(`test_sealed_checks_need_permission`가 skip 사유를 남긴다).
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _p in (ROOT / "backend", ROOT / "evaluation", HERE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import build_eval_set as B  # noqa: E402
import sealed_guard as G  # noqa: E402

from app.db.loaders import (  # noqa: E402
    apply_schema,
    insert_records,
    iter_csv,
    iter_json_array,
    normalize_age,
    normalize_contra_json,
    normalize_pregnancy,
)
from app.tools.lookup import Age, check_contraindications  # noqa: E402

TOOLS = set(B.ALL_TOOLS)
REQUIRED = ["id", "set", "set_version", "question", "branch_label", "composition_group", "subtype",
            "expected_response_type", "required_elements", "answer", "answer_evidence", "ingredient_codes",
            "reference", "expected_path", "reliability_core", "golden", "multihop", "variant", "generator",
            "provisional", "human_review"]
LABELS = {"정상", "오탈자", "모호", "오정보", "근거 없음", "범위 외", "응급"}
GENERATORS = {"upstage", "haiku", "code", "human"}
RESULTS: list[tuple[str, int, int]] = []  # (검사, 통과 k, 대상 n)


FLAG_ENV = "MEDIAGENT_TEST_BUILD_ALLOW_SEALED"  # pytest용 명시 플래그(단독 실행은 --allow-sealed)
_CLI_FLAG = False  # 단독 실행에서 --allow-sealed를 주면 True


def sealed_flag() -> bool:
    return _CLI_FLAG or os.environ.get(FLAG_ENV, "") == "1"


def sealed_allowed() -> bool:
    return G.sealed_allowed(allow_sealed=sealed_flag())


def load(name: str) -> list[dict]:
    """가드를 거쳐 읽는다. 시험셋인데 허용이 없으면 파일을 열기 전에 `SealedAccessError`."""
    return G.load_jsonl(B.OUT[name], allow_sealed=sealed_flag())


@functools.cache
def dev_items() -> list[dict]:
    return load("dev")


@functools.cache
def _test_items_cached() -> list[dict]:
    return load("test")


def test_items() -> list[dict]:
    """시험셋 문항. 허용이 없으면 열지 않고 skip한다."""
    if not sealed_allowed():
        pytest.skip(f"시험셋 열람 허용 없음(RFP-26-04): 환경변수 {G.SEALED_ENV}와 명시 플래그({FLAG_ENV}=1 또는 --allow-sealed)가 모두 필요")
    return _test_items_cached()


test_items.__test__ = False  # 이름이 test_로 시작하지만 시험이 아니다(pytest 수집 제외)


def sets() -> dict[str, list[dict]]:
    """두 세트를 도는 검사용. 허용이 없으면 개발셋만 돌린다(시험셋 몫은 열지 않음)."""
    out = {"dev": dev_items()}
    if sealed_allowed():
        out["test"] = _test_items_cached()
    return out


def test_sealed_checks_need_permission():
    """허용이 없으면 skip으로 남겨 시험셋 몫을 건너뛴 사실이 요약에 보이게 한다."""
    test_items()


def record(name: str, k: int, n: int) -> None:
    RESULTS.append((name, k, n))
    assert k == n, f"{name}: {k}/{n}"  # noqa: S101  (시험 단언)


# --------------------------------------------------------------------------- 구성

def test_counts_by_group():
    for s, items in sets().items():
        want = dict(B.COMPOSITION, **B.EXTRA[s])
        got = Counter(x["composition_group"] for x in items)
        ok = sum(got.get(g, 0) == n for g, n in want.items()) + (set(got) <= set(want))
        record(f"[{s}] 유형별 문항 수 = 9.2절 표", ok, len(want) + 1)


def test_branch_four_types_20():
    for s, items in sets().items():
        got = Counter(x["branch_label"] for x in items)
        record(f"[{s}] 분기 4유형 각 20(오탈자·모호·오정보·근거 없음)",
               sum(got[t] == 20 for t in ("오탈자", "모호", "오정보", "근거 없음")), 4)


def test_labels_and_generators():
    for s, items in sets().items():
        record(f"[{s}] 분기 라벨·생성기 값 유효", sum(x["branch_label"] in LABELS and x["generator"] in GENERATORS
                                              for x in items), len(items))


def test_required_fields():
    for s, items in sets().items():
        missing = [(x.get("id"), f) for x in items for f in REQUIRED if f not in x]
        empty_q = [x["id"] for x in items if not x["question"].strip()]
        record(f"[{s}] 필수 필드 누락 0·질문 비어 있음 0", len(items) - len({m[0] for m in missing} | set(empty_q)), len(items))


def test_ids_unique_and_version():
    for s, items in sets().items():
        ids = [x["id"] for x in items]
        record(f"[{s}] id 고유·세트 버전 고정", sum(1 for x in items if x["set"] == s and x["set_version"] == B.SET_VERSION)
               if len(set(ids)) == len(ids) else 0, len(items))


# --------------------------------------------------------------------------- 분리·안전 핵심·골든

def keys(items: list[dict]) -> set[str]:
    out = set()
    for x in items:
        out |= B.Builder.keys_of(x["ingredient_codes"])
        if x["composition_group"] == "모호":
            out.add(x["answer"]["ambiguous_name"])
    return out


def test_dev_test_disjoint():
    kt = keys(test_items())  # 허용 확인(없으면 skip)을 먼저
    kd = keys(dev_items())
    record("개발셋·시험셋 약·성분 쌍(단일 성분·모호 이름 포함) 비중복", len(kd | kt) - len(kd & kt), len(kd | kt))


def test_no_duplicate_questions():
    qt = {x["question"] for x in test_items()}  # 허용 확인(없으면 skip)을 먼저
    qd = {x["question"] for x in dev_items()}
    record("두 세트에 같은 질문 문장 없음", len(qd | qt) - len(qd & qt), len(qd | qt))


def test_reliability_core():
    core = [x for x in test_items() if x["reliability_core"]]
    by = Counter(x["composition_group"] for x in core)
    ok = (len(core) == 40) + (by["정상-응급"] == 10) + (by["정상-목록에없는약"] == 10) + (by["오정보"] == 20) \
        + (not any(x["reliability_core"] for x in dev_items()))
    record("reliability_core: 시험셋 40(응급 10·목록에 없는 약 10·오정보 20), 개발셋 0", ok, 5)


def test_golden():
    src = [x["golden_source"] or "" for x in test_items() if x["golden"] or x.get("golden_excluded")]
    want = [f"RFP-21 §4.8 #{i}" for i in range(1, 6)]
    ok = sum(any(s.startswith(w) for s in src) for w in want) + (not any(x["golden"] for x in dev_items()))
    record("골든: RFP-21 §4.8 5문항 모두 시험셋, 개발셋 0", ok, 6)


def test_multihop():
    tcs = {x["multihop"]["tc"]: x for x in test_items() if x["multihop"]}
    ok = sum(tc in tcs and len(tcs[tc]["multihop"]["evidence_chunks"]) >= 2 for tc in ("TC-15", "TC-21", "TC-22", "TC-23"))
    ok += tcs.get("TC-23", {}).get("multihop", {}).get("extension") is True
    record("멀티홉 TC-15·21·22·23 표시·근거 청크 2개 이상·TC-23 확장 표시", ok, 5)


def test_m_grade_age_preg_multi():
    for s, items in sets().items():
        m = sum(1 for x in items if x["composition_group"] == "정상-임부" and any(
            mm["grade"] == "M" for it in x["answer"]["items"] if it["kind"] == "pregnancy" for mm in it["matches"]))
        multi = sum(1 for x in items if x["composition_group"].startswith("정상") and len(x["ingredient_codes"]) >= 3)
        ok = (m >= 5) + (multi >= 1) + any(x["composition_group"] == "정상-연령" for x in items) \
            + any(x["composition_group"] == "정상-임부" for x in items)
        record(f"[{s}] 정상: M 등급 5개 이상·3개 이상 약·연령·임부 포함", ok, 4)


def test_oos_injection_and_stop():
    for s, items in sets().items():
        oos = [x for x in items if x["composition_group"] == "범위 외"]
        inj = sum(x["subtype"] == "인젝션" for x in oos)
        stop = [x for x in oos if x["subtype"] in ("복용 중단·감량", "의료진 우회")]
        ok = (4 <= inj <= 6) + (4 <= len(stop) <= 6) + all(x["bad_answer_sample"] for x in stop)
        record(f"[{s}] 범위 외: 인젝션 5 안팎·중단·감량·의료진 우회 5 안팎(불량 답 견본 있음)", ok, 3)


# --------------------------------------------------------------------------- 오탈자 짝·경로·잠정

def test_typo_pairs():
    for s, items in sets().items():
        by_id = {x["id"]: x for x in items}
        typos = [x for x in items if x["composition_group"] == "오탈자"]
        ok = sum(1 for x in typos if x["pair_of"] in by_id and by_id[x["pair_of"]]["composition_group"].startswith("정상-")
                 and by_id[x["pair_of"]]["answer"] == x["answer"] and x["variant"] in ("오탈자", "축약", "표기")
                 and x["question"] != by_id[x["pair_of"]]["question"])
        record(f"[{s}] 오탈자 20문항이 정상 문항과 짝(같은 정답, 다른 질문)", ok, len(typos))
        v = Counter(x["variant"] for x in typos)
        record(f"[{s}] variant 오탈자 14±2·축약+표기 6±2", (12 <= v["오탈자"] <= 16) + (4 <= v["축약"] + v["표기"] <= 8), 2)


def test_expected_path_schema():
    for s, items in sets().items():
        def good(p):
            return (set(p) == {"required", "recommended", "forbidden", "order", "max_model_calls"}
                    and set(p["required"]) | set(p["recommended"]) | set(p["forbidden"]) <= TOOLS
                    and not (set(p["required"]) & set(p["forbidden"]))
                    and all(len(o) == 2 and set(o) <= TOOLS for o in p["order"])
                    and p["max_model_calls"] == B.MAX_MODEL_CALLS)
        record(f"[{s}] 기대 경로 스키마(RFP-26 §7.6) 유효", sum(good(x["expected_path"]) for x in items), len(items))
        need_judge = [x for x in items if x["composition_group"] in
                      ("정상-병용", "정상-연령", "정상-임부", "정상-목록에없는약", "정상-응급", "오탈자")]
        record(f"[{s}] 판정 문항은 check_contraindications 필수",
               sum("check_contraindications" in x["expected_path"]["required"] for x in need_judge), len(need_judge))
        oos = [x for x in items if x["composition_group"] == "범위 외"]
        record(f"[{s}] 범위 외는 도구 전부 금지", sum(set(x["expected_path"]["forbidden"]) == TOOLS for x in oos), len(oos))


def test_provisional_marks():
    for s, items in sets().items():
        amb = [x for x in items if x["composition_group"] == "모호" and not (x["golden"] or x.get("golden_excluded"))]
        abbr = [x for x in items if x["variant"] == "축약"]
        record(f"[{s}] 모호(골든 제외)·축약 문항 provisional 표시(BE-10 전)",
               sum(bool(x["provisional"] and x["provisional_reason"]) for x in amb + abbr), len(amb + abbr))


def test_review_sample_ratio():
    for s, items in sets().items():
        n = sum(x["human_review"]["sample"] for x in items)
        record(f"[{s}] 사람 검수 표본 15~20%", int(0.15 * len(items) <= n <= 0.20 * len(items)), 1)


def test_manifest_hash():
    man = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    names = ("dev", "test") if sealed_allowed() else ("dev",)  # 시험셋 바이트는 허용이 있을 때만 읽는다
    ok = sum(hashlib.sha256(G.read_bytes(B.OUT[s], allow_sealed=sealed_flag())).hexdigest() == man["sets"][s]["sha256"]
             for s in names)
    record(f"manifest sha256이 파일과 일치(동결 확인용, {'·'.join(names)})", ok, len(names))


# --------------------------------------------------------------------------- 정답 재산출(BE-09 lookup)

def pick_sample(items: list[dict]) -> list[dict]:
    """판정 문항에서 해시 순으로 5건: 병용 해당 1·목록에 없음 1·임부 2·연령 1."""
    want = [("정상-병용", 1), ("정상-목록에없는약", 1), ("정상-임부", 2), ("정상-연령", 1)]
    out = []
    for g, n in want:
        c = [x for x in items if x["composition_group"] == g and x["ingredient_codes"] and x["answer"]["items"]]
        c.sort(key=lambda x: B.sha(x["id"] + "rederive"))
        out += c[:n]
    return out


def test_rederive_sample():
    sample = pick_sample(test_items())
    codes = {c for x in sample for c in x["ingredient_codes"]}
    conn = sqlite3.connect(":memory:")
    apply_schema(conn)
    insert_records(conn, "pregnancy_contra", (r for r in map(normalize_pregnancy, iter_csv(B.F_PREG))
                                              if r and r["ingr_code"] in codes))
    insert_records(conn, "age_contra", (r for r in map(normalize_age, iter_csv(B.F_AGE)) if r and r["ingr_code"] in codes))
    insert_records(conn, "contra_pair", (r for r in map(normalize_contra_json, iter_json_array(B.F_COMBO))
                                         if r and r["code_a"] in codes and r["code_b"] in codes))
    ok = 0
    for x in sample:
        prof = x["profile"]
        age = Age(prof["age"]["value"], prof["age"]["unit"]) if prof.get("age") else None
        multi = len(x["ingredient_codes"]) >= 2
        res = check_contraindications(conn, x["ingredient_codes"], age=age, pregnancy=prof.get("pregnant", False)).to_dict()
        got = sorted((i["kind"], tuple(i["subject"]), i["status"],
                      tuple(sorted({m.get("grade") or m.get("notice_no") or "" for m in i["matches"]})))
                     for i in res["items"] if multi or i["kind"] != "contra_pair")
        exp = sorted((i["kind"], tuple(i["subject"]), i["status"],
                      tuple(sorted({m.get("grade") or m.get("notice_no") or "" for m in i["matches"]})))
                     for i in x["answer"]["items"])
        ok += got == exp
    record("정답 재산출(BE-09 check_contraindications, 표본 5건)", ok, len(sample))


ALL = [v for k, v in sorted(globals().items())
       if k.startswith("test_") and callable(v) and getattr(v, "__test__", True)]

if __name__ == "__main__":
    _CLI_FLAG = "--allow-sealed" in sys.argv[1:]
    fails = 0
    for fn in ALL:
        try:
            fn()
        except AssertionError as e:
            fails += 1
            print("FAIL", fn.__name__, e)
        except pytest.skip.Exception as e:
            print("SKIP", fn.__name__, e)
    for name, k, n in RESULTS:
        print(f"{'통과' if k == n else '실패'} {k}/{n}  {name}")
    print(f"검사 {len(RESULTS)}개 중 통과 {sum(k == n for _, k, n in RESULTS)}, 실패 {sum(k != n for _, k, n in RESULTS)}")
    sys.exit(1 if fails else 0)
