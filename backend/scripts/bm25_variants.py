"""BE-10 BM25 변형 비교 시험(개발용, 오프라인). 단어 단위 vs 문자 2-gram(현재 구현)·3-gram·2+3-gram(이전 구현).

작업 위치 `backend/`:  python scripts/bm25_variants.py [--cases 5]

공정 비교 규칙:
- 같은 사전(`drug_dict.json`)·같은 개발용 질의(`dev_queries.json`)·같은 BM25(k1=1.5, b=0.75, `app.tools.drug_dict.BM25`).
- 문서 단위는 현재 구현과 같다(제품 이름 하나 = 문서 하나, 성분 이름들 = 문서 하나. 문서 번호 = 제품 뒤 성분).
- 전처리는 `normalize_name`과 같은 단계(NFKC, 수출명 괄호·KIDS 용량 꼬리 제거, 소문자, 단위 통일)를 거친다.
  n-gram 변형은 그 뒤 공백·구두점을 제거한 키에서 n-gram을 만들고(현재 구현 그대로),
  단어 변형은 공백·구두점 제거 **직전**에 그 문자들을 경계로 잘라 토큰으로 쓴다(조사·형태소 처리 없음).
- 외부 API 호출 0, 평가 세트·시험셋 미사용(RFP-26-04).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import tracemalloc
import unicodedata
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from embed_compare import QUERY_TYPES, TYPE_LABELS, gold_doc_sets, queries_fingerprint, tally, with_intervals  # noqa: E402

from app.tools import drug_dict as dd_mod  # noqa: E402
from app.tools.drug_dict import BM25, DEFAULT_DICT_PATH, DrugDict, char_ngrams, normalize_name  # noqa: E402

DICT_DIR = Path(DEFAULT_DICT_PATH).parent
QUERIES_PATH = DICT_DIR / "dev_queries.json"
REPORT_JSON = DICT_DIR / "bm25_variants_report.json"
REPORT_MD = DICT_DIR / "bm25_variants_report.md"
EXPECTED_FINGERPRINT = "4186e100384f3202"
TOP_K = 5
LATENCY_REPEATS = 3

Tokenizer = Callable[[str], list[str]]


# --------------------------------------------------------------------------- 토크나이저

def _pre_strip(text: str) -> str:
    """`normalize_name`의 공백·구두점 제거 직전까지(같은 전처리 단계)."""
    s = unicodedata.normalize("NFKC", text or "")
    s = dd_mod._PAREN_EXPORT_RE.sub("", s)
    s = dd_mod._KIDS_SUFFIX_RE.sub("", s)
    s = s.lower()
    for a, b in dd_mod._UNIT_MAP:
        s = s.replace(a, b)
    return s


def word_tokens(text: str) -> list[str]:
    """공백·구두점을 경계로 자른 단어 토큰. 조사·형태소 처리 없음."""
    return [t for t in dd_mod._STRIP_RE.split(_pre_strip(text)) if t]


def ngram_tokens(sizes: Sequence[int]) -> Tokenizer:
    """정규화 키(공백·구두점 제거)의 문자 n-gram. 현재 구현의 질의 쪽과 같다."""
    return lambda text: char_ngrams(normalize_name(text), sizes)


# 변형 정의: (이름, 질의 토크나이저, 제품 문서 토크나이저, 성분 문서 토크나이저(이름 목록))
def _variants() -> dict[str, tuple[Tokenizer, Tokenizer, Callable[[list[str]], list[str]]]]:
    def ing_words(names: list[str]) -> list[str]:
        return [t for n in names for t in word_tokens(n)]

    def ing_ngrams(sizes: Sequence[int]) -> Callable[[list[str]], list[str]]:
        # 현재 구현: 정규화한 이름들을 공백으로 이어 붙인 문자열에서 n-gram(이름 경계의 공백 포함)
        return lambda names: char_ngrams(" ".join(normalize_name(n) for n in names), sizes)

    out: dict[str, tuple[Tokenizer, Tokenizer, Callable[[list[str]], list[str]]]] = {"word": (word_tokens, word_tokens, ing_words)}
    for name, sizes in (("char2", (2,)), ("char3", (3,)), ("char2_3", (2, 3))):
        out[name] = (ngram_tokens(sizes), ngram_tokens(sizes), ing_ngrams(sizes))
    return out


VARIANT_LABELS = {"word": "단어 단위(공백·구두점 분리)", "char2": "문자 2-gram(현재 구현, BE-10-07 A)", "char3": "문자 3-gram", "char2_3": "문자 2+3-gram(이전 구현)"}


# --------------------------------------------------------------------------- 색인

def build_docs(dd: DrugDict, prod_tok: Tokenizer, ing_tok: Callable[[list[str]], list[str]]) -> list[list[str]]:
    docs = [prod_tok(p["name"]) for p in dd.products]
    docs += [ing_tok(list(i["names"])) for i in dd.ingredients]
    return docs


def build_index(dd: DrugDict, name: str) -> tuple[BM25, dict[str, Any]]:
    """색인을 만들고 크기·시간을 잰다. 메모리는 tracemalloc 피크(색인 객체 + 토큰 목록 포함)와 보존분(색인만)."""
    _, qtok, ing_tok = _variants()[name]
    prod_tok = _variants()[name][1]
    t0 = time.perf_counter()
    docs = build_docs(dd, prod_tok, ing_tok)
    bm = BM25(docs)
    build_s = time.perf_counter() - t0
    n_tokens = sum(len(d) for d in docs)

    tracemalloc.start()
    docs2 = build_docs(dd, prod_tok, ing_tok)
    bm2 = BM25(docs2)
    _, peak = tracemalloc.get_traced_memory()
    del docs2
    retained, _ = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del bm2
    stats = {
        "docs": len(docs), "tokens_total": n_tokens, "tokens_per_doc": round(n_tokens / max(len(docs), 1), 2),
        "unique_tokens": len(bm._postings), "postings": sum(len(p) for p in bm._postings.values()),
        "build_seconds": round(build_s, 3), "index_mb_retained": round(retained / 1e6, 1), "build_peak_mb": round(peak / 1e6, 1),
    }
    return bm, stats


def rank(bm: BM25, qtokens: Sequence[str], k: int = TOP_K) -> list[int]:
    sc = bm.scores(qtokens)
    return [d for d, _ in sorted(sc.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


def latency_ms(bm: BM25, qtok: Tokenizer, queries: Sequence[dict[str, Any]]) -> float:
    """질의 300개 평균 ms(토큰화+채점+정렬). 반복 중 가장 빠른 평균을 쓴다."""
    best = float("inf")
    for _ in range(LATENCY_REPEATS):
        t0 = time.perf_counter()
        for q in queries:
            rank(bm, qtok(q["query"]))
        best = min(best, (time.perf_counter() - t0) / max(len(queries), 1) * 1000)
    return round(best, 3)


# --------------------------------------------------------------------------- 사례

def doc_name(dd: DrugDict, d: int) -> str:
    n = len(dd.products)
    return dd.products[d]["name"] if d < n else dd.ingredients[d - n]["display"]


def pick_cases(
    dd: DrugDict, queries: Sequence[dict[str, Any]], golds: Sequence[set[int]], rankings: dict[str, list[list[int]]], win: str, lose: str, limit: int
) -> list[dict[str, Any]]:
    """`win`은 top-1 성공, `lose`는 top-1 실패인 질의. 유형이 고루 섞이도록 유형 순환으로 고른다."""
    by_type: dict[str, list[int]] = {}
    for i, q in enumerate(queries):
        r_w, r_l = rankings[win][i], rankings[lose][i]
        if r_w and r_w[0] in golds[i] and not (r_l and r_l[0] in golds[i]):
            by_type.setdefault(q["type"], []).append(i)
    chosen: list[int] = []
    pools = {t: list(v) for t, v in by_type.items()}
    while len(chosen) < limit and any(pools.values()):
        for t in QUERY_TYPES:
            if pools.get(t) and len(chosen) < limit:
                chosen.append(pools[t].pop(0))
    return [
        {
            "id": queries[i]["id"], "type": queries[i]["type"], "query": queries[i]["query"],
            "gold": sorted(doc_name(dd, d) for d in list(golds[i])[:3]),
            f"{win}_top1": doc_name(dd, rankings[win][i][0]), f"{lose}_top3": [doc_name(dd, d) for d in rankings[lose][i][:3]],
        }
        for i in chosen
    ]


# --------------------------------------------------------------------------- 실행·보고

def run(n_cases: int) -> dict[str, Any]:
    dd = DrugDict.load()
    payload = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
    queries = payload["queries"]
    fp = queries_fingerprint(queries)
    golds = gold_doc_sets(dd, queries)
    types = [q["type"] for q in queries]
    rankings: dict[str, list[list[int]]] = {}
    results: dict[str, Any] = {}
    for name, (qtok, _, _) in _variants().items():
        bm, stats = build_index(dd, name)
        rankings[name] = [rank(bm, qtok(q["query"])) for q in queries]
        stats["query_ms_avg"] = latency_ms(bm, qtok, queries)
        results[name] = {"label": VARIANT_LABELS[name], "metrics": with_intervals(tally(rankings[name], golds, types)), "index": stats}
        del bm
    return {
        "dict_version": dd.version, "queries": len(queries), "queries_fingerprint": fp, "fingerprint_expected": EXPECTED_FINGERPRINT,
        "fingerprint_ok": fp == EXPECTED_FINGERPRINT, "bm25": {"k1": 1.5, "b": 0.75}, "purpose": "개발용 비교. 평가 수치로 쓰지 않는다",
        "variants": results,
        "cases_word_fail_ngram_ok": pick_cases(dd, queries, golds, rankings, "char2", "word", n_cases),
        "cases_ngram_fail_word_ok": pick_cases(dd, queries, golds, rankings, "word", "char2", n_cases),
        "case_counts": {
            "word_fail_ngram_ok": sum(1 for i in range(len(queries)) if rankings["char2"][i][:1] and rankings["char2"][i][0] in golds[i] and not (rankings["word"][i][:1] and rankings["word"][i][0] in golds[i])),
            "ngram_fail_word_ok": sum(1 for i in range(len(queries)) if rankings["word"][i][:1] and rankings["word"][i][0] in golds[i] and not (rankings["char2"][i][:1] and rankings["char2"][i][0] in golds[i])),
        },
    }


def _cell(c: dict[str, Any]) -> tuple[str, str]:
    t1, t5 = c["top1"], c["top5"]
    return f"{t1['k']}/{t1['n']} [{t1['wilson95'][0]:.2f}–{t1['wilson95'][1]:.2f}]", f"{t5['k']}/{t5['n']} [{t5['wilson95'][0]:.2f}–{t5['wilson95'][1]:.2f}]"


def render_md(rep: dict[str, Any]) -> str:
    v = rep["variants"]
    L = [
        "# BE-10 BM25 변형 비교 (단어 단위 vs 문자 n-gram, 개발용·참고값)", "",
        f"- 사전 `{rep['dict_version']}`, 질의 {rep['queries']}개(지문 `{rep['queries_fingerprint']}`, 기대값 일치: {rep['fingerprint_ok']}), BM25 k1={rep['bm25']['k1']}, b={rep['bm25']['b']} 고정",
        "- 숫자는 k/n [Wilson 95%]. 칸당 n=50이라 구간이 겹치면 구분하지 못한 것으로 읽는다(9.1절). 평가 수치가 아니다(RFP-26-04).", "",
        "## 한계 (먼저 읽는다)", "",
        "- 질의가 **철자 변형 중심**(오탈자 2종·띄어쓰기·접두)으로 설계되어 문자 n-gram에 유리하다. 의미·동의어 질의는 없다.",
        "- 칸당 n=50이다. 5~10%p 차이는 구간에 가려진다. 이 표만으로 우열의 일반성을 주장하지 않는다.",
        "- 단어 변형은 조사·형태소 처리가 없는 가장 단순한 형태다. 형태소 분석기·접두 자르기 변형은 지시서에 따라 제외했다.", "",
        "## 전체", "", "| 변형 | top-1 | top-5 |", "|---|---|---|",
    ]
    for _name, r in v.items():
        a, b = _cell(r["metrics"]["all"])
        L.append(f"| {r['label']} | {a} | {b} |")
    for t in QUERY_TYPES:
        L += ["", f"## {TYPE_LABELS[t]} (n={v['word']['metrics'][t]['n']})", "", "| 변형 | top-1 | top-5 |", "|---|---|---|"]
        for _name, r in v.items():
            a, b = _cell(r["metrics"][t])
            L.append(f"| {r['label']} | {a} | {b} |")
    L += ["", "## 색인 크기·시간·지연", "", "| 변형 | 토큰 수 | 고유 토큰 | posting | 문서당 토큰 | 빌드(s) | 색인 메모리(MB) | 빌드 피크(MB) | 질의 평균(ms) |", "|---|---|---|---|---|---|---|---|---|"]
    for r in v.values():
        s = r["index"]
        L.append(f"| {r['label']} | {s['tokens_total']:,} | {s['unique_tokens']:,} | {s['postings']:,} | {s['tokens_per_doc']} | {s['build_seconds']} | {s['index_mb_retained']} | {s['build_peak_mb']} | {s['query_ms_avg']} |")
    L += ["", "메모리는 tracemalloc 값(Python 객체 기준, 근사). 질의 지연은 토큰화+채점+정렬, 3회 반복 중 최소 평균.", ""]
    cc = rep["case_counts"]
    L += [f"## 사례: 단어 단위 top-1 실패 · 2+3-gram 성공 (전체 {cc['word_fail_ngram_ok']}건 중 유형 순환 표본)", "", "| id | 유형 | 질의 | 정답(최대 3) | 2+3-gram 1위 | 단어 단위 상위 3 |", "|---|---|---|---|---|---|"]
    for c in rep["cases_word_fail_ngram_ok"]:
        L.append(f"| {c['id']} | {c['type']} | {c['query']} | {', '.join(c['gold'])} | {c['char2_top1']} | {' / '.join(c['word_top3'])} |")
    L += ["", f"## 사례: 2+3-gram top-1 실패 · 단어 단위 성공 (전체 {cc['ngram_fail_word_ok']}건 중 유형 순환 표본)", "", "| id | 유형 | 질의 | 정답(최대 3) | 단어 단위 1위 | 2+3-gram 상위 3 |", "|---|---|---|---|---|---|"]
    for c in rep["cases_ngram_fail_word_ok"]:
        L.append(f"| {c['id']} | {c['type']} | {c['query']} | {', '.join(c['gold'])} | {c['word_top1']} | {' / '.join(c['char2_top3'])} |")
    return "\n".join(L) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", type=int, default=5)
    args = ap.parse_args(argv)
    rep = run(args.cases)
    REPORT_JSON.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    REPORT_MD.write_text(render_md(rep), encoding="utf-8")
    print(f"저장: {REPORT_JSON.name}, {REPORT_MD.name} (지문 일치: {rep['fingerprint_ok']})")
    for name, r in rep["variants"].items():
        a = r["metrics"]["all"]
        print(f"{name:7s} top1 {a['top1']['k']}/{a['top1']['n']} top5 {a['top5']['k']}/{a['top5']['n']} 질의 {r['index']['query_ms_avg']}ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
