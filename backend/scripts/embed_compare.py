"""BE-10 임베딩 모델 비교 시험(RFP-15-05). 사전 문서를 임베딩하고 BM25·임베딩·하이브리드를 개발용 질의 세트로 견준다.

하위 명령(작업 위치 `backend/`):
  queries                       개발용 질의 세트 생성(`data/mock/dict/dev_queries.json`, 시드 고정, 호출 0)
  plan                          호출 수·토큰·예상 비용만 출력(호출 0)
  run --model small|large --max-usd 0.5   실호출. 캐시(`app.llm.cache`)·원장(`app.llm.ledger`)·하드 상한을 거친다
  report                        저장된 벡터로 지표를 계산해 `embed_compare_report.json`·`.md`를 쓴다(호출 0)

규칙(지시서 2026-11-10):
- 질의 세트는 **개발용**이다. 평가 세트·시험셋을 쓰지 않는다(RFP-26-04). 정답은 생성 규칙으로 확정한다.
- 키는 환경변수 OPENAI_API_KEY(없으면 `app.config` 설정)로만 읽고 출력하지 않는다.
- 상한: `--max-usd`(이 실행 몫)와 개발 원장(dev 2.5 USD) 둘 다 넘기지 않는다. 넘기려 하면 호출 전에 중단한다.
  이미 캐시된 배치는 호출·비용 없이 건너뛰므로 중단 뒤 같은 명령을 다시 실행하면 이어서 한다.
- 토큰 수는 tiktoken이 있으면 쓰고, 없으면 문자 수 기반 **근사**다(보고에 방법을 적는다).
- 단가(USD/100만 토큰): text-embedding-3-small 0.02, large 0.13(platform.openai.com 모델 문서, 2026-11-10 웹검색 확인).
  `gpt-6-luna`는 임베딩 엔드포인트를 지원하지 않아 small이 기준, large가 비교 후보다.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import random
import re
import sys
import time
import types
from array import array
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.llm.cache import cache_mode, cached_openai_call  # noqa: E402
from app.llm.ledger import BudgetExceeded, CostLedger  # noqa: E402
from app.security.redact import install_excepthook  # noqa: E402
from app.tools.drug_dict import DEFAULT_DICT_PATH, DrugDict, char_ngrams, normalize_name  # noqa: E402

DICT_DIR = Path(DEFAULT_DICT_PATH).parent
EMB_DIR = DICT_DIR / "embeddings"
QUERIES_PATH = DICT_DIR / "dev_queries.json"
REPORT_JSON = DICT_DIR / "embed_compare_report.json"
REPORT_MD = DICT_DIR / "embed_compare_report.md"

MODELS = {"small": "text-embedding-3-small", "large": "text-embedding-3-large"}
PRICE_PER_M = {"small": 0.02, "large": 0.13}  # USD / 100만 토큰
ENDPOINT = "https://api.openai.com/v1/embeddings"
BATCH_SIZE = 2048  # 엔드포인트 입력 개수 상한
QUERY_SEED = 20261110
PER_TYPE = 50
RRF_K = 60
DEPTH = 100  # 융합·지표에 쓰는 후보 깊이
ESTIMATE_MARGIN = 1.0  # 근사 토큰은 이미 보수적으로 잡았다(아래). 하드 상한은 호출 전 추정으로 막는다

QUERY_TYPES = ("typo_drop", "typo_swap", "spacing", "brand_prefix", "ingredient_ko", "english")
TYPE_LABELS = {
    "typo_drop": "오탈자(자모 탈락)",
    "typo_swap": "오탈자(자모 치환)",
    "spacing": "띄어쓰기 변형",
    "brand_prefix": "브랜드 접두만",
    "ingredient_ko": "성분명→제품(성분 단위)",
    "english": "영문 입력",
}

_HANGUL = re.compile(r"[가-힣]")
_CLEAN_BODY = re.compile(r"[가-힣0-9A-Za-z .%]+")  # 짝이 안 맞는 괄호 등 잡음이 든 이름은 질의 재료에서 뺀다


class CapReached(RuntimeError):
    """`--max-usd` 하드 상한을 넘기려 할 때(호출 전 중단)."""


# --------------------------------------------------------------------------- 토큰·비용 어림

def estimate_tokens(text: str) -> float:
    """문자 수 기반 근사. 한글 음절 1.7토큰, 그 밖의 문자 0.35토큰(보수적으로 크게 잡음). tiktoken 대용."""
    h = len(_HANGUL.findall(text))
    return h * 1.7 + (len(text) - h) * 0.35


def count_tokens(texts: Sequence[str]) -> tuple[float, str]:
    """(토큰 수, 방법). tiktoken이 있고 인코딩을 불러오면 그 값, 아니면 문자 수 근사."""
    try:
        import tiktoken  # type: ignore[import-not-found]

        enc = tiktoken.get_encoding("cl100k_base")
        return float(sum(len(enc.encode(t)) for t in texts)), "tiktoken(cl100k_base)"
    except Exception:  # noqa: BLE001 - 미설치·오프라인 인코딩 파일 없음 모두 근사로 대체
        return sum(estimate_tokens(t) for t in texts), "문자 수 근사(한글 음절 1.7·기타 0.35 토큰/자, tiktoken 없음)"


def batches(items: Sequence[str], size: int | None = None) -> list[list[str]]:
    size = size or BATCH_SIZE
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def cost_usd(tokens: float, size: str) -> float:
    return tokens * PRICE_PER_M[size] / 1e6


# --------------------------------------------------------------------------- 한글 자모 조작(오탈자 합성)

_S_BASE, _S_END = 0xAC00, 0xD7A3
_VOWEL_SWAP = {8: 13, 13: 8, 1: 5, 5: 1, 4: 0, 0: 4, 20: 5, 9: 11, 11: 9, 18: 20, 2: 6, 6: 2}  # ㅗ↔ㅜ ㅐ↔ㅔ ㅓ↔ㅏ ㅣ→ㅔ …(21 중성 인덱스)
_LEAD_SWAP = {0: 15, 15: 0, 3: 16, 16: 3, 7: 17, 17: 7, 12: 14, 14: 12, 9: 10, 10: 9}  # ㄱ↔ㅋ ㄷ↔ㅌ ㅂ↔ㅍ ㅈ↔ㅊ ㅅ↔ㅆ


def _decompose(ch: str) -> tuple[int, int, int] | None:
    o = ord(ch)
    if not (_S_BASE <= o <= _S_END):
        return None
    o -= _S_BASE
    return o // (21 * 28), (o % (21 * 28)) // 28, o % 28


def _compose(lead: int, vowel: int, tail: int) -> str:
    return chr(_S_BASE + (lead * 21 + vowel) * 28 + tail)


def drop_jamo(text: str, rng: random.Random) -> str | None:
    """받침이 있는 음절 하나를 골라 받침을 뗀다(자모 탈락). 받침이 없으면 None."""
    idx = [i for i, ch in enumerate(text) if (d := _decompose(ch)) and d[2] != 0]
    if not idx:
        return None
    i = rng.choice(idx)
    d = _decompose(text[i])
    assert d is not None
    return text[:i] + _compose(d[0], d[1], 0) + text[i + 1 :]


def swap_jamo(text: str, rng: random.Random) -> str | None:
    """음절 하나의 모음 또는 초성을 비슷한 자모로 바꾼다(자모 치환). 바꿀 수 있는 음절이 없으면 None."""
    cands: list[tuple[int, str]] = []
    for i, ch in enumerate(text):
        d = _decompose(ch)
        if not d:
            continue
        if d[1] in _VOWEL_SWAP:
            cands.append((i, "v"))
        if d[0] in _LEAD_SWAP:
            cands.append((i, "l"))
    if not cands:
        return None
    i, kind = rng.choice(cands)
    d = _decompose(text[i])
    assert d is not None
    lead, vowel, tail = d
    if kind == "v":
        vowel = _VOWEL_SWAP[vowel]
    else:
        lead = _LEAD_SWAP[lead]
    return text[:i] + _compose(lead, vowel, tail) + text[i + 1 :]


# --------------------------------------------------------------------------- 개발용 질의 세트

def _name_body(name: str) -> str:
    """제품명에서 수출명 괄호·성분 병기 괄호를 뗀 본문(질의 합성 재료)."""
    return normalize_name_keep_spaces(name)


def normalize_name_keep_spaces(name: str) -> str:
    s = re.sub(r"\((?:수출명|수출용)[^)]*\)", "", name or "")
    s = re.sub(r"_\([^)]*\)\s*$", "", s)
    s = re.sub(r"[(（\[][^)）\]]*[)）\]]", "", s)
    return " ".join(s.split())


def _ingredient_ko(ing: dict[str, Any]) -> str | None:
    for nm in ing["names"][:6]:  # 임베딩 문서에 실제로 들어가는 이름만 쓴다
        if _HANGUL.search(nm):
            return nm
    return None


def build_dev_queries(dd: DrugDict, seed: int = QUERY_SEED, per_type: int = PER_TYPE) -> list[dict[str, Any]]:
    """사전에서 규칙으로 질의를 합성한다. 같은 사전·시드면 결과가 같다. 정답은 `answer`에 담는다.

    answer.item_seqs: 정답 제품 item_seq(같은 이름 제품 전부). answer.ingredient_ids: 정답 성분 id.
    answer.ingredient_products_ok: 성분 질의에서 그 성분을 가진 제품도 정답으로 센다.
    """
    rng = random.Random(seed)  # noqa: S311 - 재현용 시드 고정(암호 용도 아님)
    products = dd.products
    key_to_seqs: dict[str, list[str]] = {}
    for p in products:
        if p.get("item_seq"):
            key_to_seqs.setdefault(normalize_name(p["name"]), []).append(p["item_seq"])

    # 제품 후보: 판매 중, 본문에 한글 4음절 이상, 정규화 키가 유일한 제품 이름 하나당 한 번만
    pool = [i for i, p in enumerate(products) if p.get("item_seq") and not p.get("cancelled") and len(_HANGUL.findall(_name_body(p["name"]))) >= 4 and _CLEAN_BODY.fullmatch(_name_body(p["name"]))]
    seen: set[str] = set()
    uniq: list[int] = []
    for i in sorted(pool):
        k = normalize_name(products[i]["name"])
        if k not in seen:
            seen.add(k)
            uniq.append(i)
    rng.shuffle(uniq)
    used: set[int] = set()
    out: list[dict[str, Any]] = []

    def add(qtype: str, query: str, answer: dict[str, Any], source: str, rule: str) -> None:
        out.append({"id": f"{qtype}-{sum(1 for o in out if o['type'] == qtype) + 1:03d}", "type": qtype, "query": query, "answer": answer, "source": source, "rule": rule})

    def product_answer(i: int) -> dict[str, Any]:
        return {"item_seqs": sorted(key_to_seqs.get(normalize_name(products[i]["name"]), [products[i]["item_seq"]])), "ingredient_ids": [], "ingredient_products_ok": False}

    def draw(transform: Callable[[str], str | None], qtype: str, rule: str) -> None:
        n = 0
        for i in uniq:
            if n >= per_type:
                break
            if i in used:
                continue
            body = _name_body(products[i]["name"])
            q = transform(body)
            if not q or q == body or normalize_name(q) == normalize_name(products[i]["name"]):
                continue
            used.add(i)
            add(qtype, q, product_answer(i), products[i]["item_seq"], rule)
            n += 1

    draw(lambda b: drop_jamo(b, rng), "typo_drop", "제품명 본문의 받침 하나 탈락")
    draw(lambda b: swap_jamo(b, rng), "typo_swap", "제품명 본문의 모음 또는 초성 하나를 비슷한 자모로 치환")

    def spacing(b: str) -> str | None:
        flat = b.replace(" ", "")
        if len(flat) < 5:
            return None
        cuts = [c for c in range(2, len(flat) - 1) if _HANGUL.match(flat[c - 1]) and _HANGUL.match(flat[c])]
        if not cuts:
            return None
        cut = rng.choice(cuts)
        spaced = flat[:cut] + " " + flat[cut:]
        return spaced if spaced != b else None

    draw(spacing, "spacing", "제품명 본문의 공백을 없앤 뒤 임의 위치에 하나 삽입")

    # 브랜드 접두만: 기본형 키 앞 3~4자. 이 접두로 시작하는 제품이 60개 이하여야 한다(정답 집합 크기 제한)
    base_keys = [(normalize_name(p["name"], keep_paren=False), i) for i, p in enumerate(products)]
    n = 0
    for i in uniq:
        if n >= per_type:
            break
        if i in used:
            continue
        bk = normalize_name(products[i]["name"], keep_paren=False)
        hang = _HANGUL.findall(bk)
        if len(hang) < 5:
            continue
        plen = rng.choice((3, 4))
        prefix = bk[:plen]
        if not all(_HANGUL.match(c) for c in prefix):
            continue
        seqs = sorted({products[j]["item_seq"] for k, j in base_keys if k.startswith(prefix) and products[j].get("item_seq")})
        if not 1 <= len(seqs) <= 60:
            continue
        used.add(i)
        add("brand_prefix", prefix, {"item_seqs": seqs, "ingredient_ids": [], "ingredient_products_ok": False}, products[i]["item_seq"], f"기본형 이름 앞 {plen}자, 정답=그 접두의 모든 제품")
        n += 1

    # 성분 질의: 성분 하나짜리, 한글 이름이 있는 성분. 한글 입력과 영문 입력은 서로 다른 성분에서 뽑는다.
    ing_pool = [j for j, ing in enumerate(dd.ingredients) if len(ing["components"]) == 1 and _ingredient_ko(ing) and ing["components"][0].get("en")]
    rng.shuffle(ing_pool)
    for j in ing_pool[:per_type]:
        add("ingredient_ko", _ingredient_ko(dd.ingredients[j]) or "", {"item_seqs": [], "ingredient_ids": [j], "ingredient_products_ok": True}, f"ingredient:{j}", "성분 한글명, 정답=그 성분 문서 또는 그 성분을 가진 제품")
    for j in ing_pool[per_type : per_type * 2]:
        add("english", dd.ingredients[j]["components"][0]["en"], {"item_seqs": [], "ingredient_ids": [j], "ingredient_products_ok": True}, f"ingredient:{j}", "성분 영문명, 정답=그 성분 문서 또는 그 성분을 가진 제품")
    return out


def queries_fingerprint(queries: Sequence[dict[str, Any]]) -> str:
    raw = json.dumps([(q["id"], q["query"]) for q in queries], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- .npy 입출력(numpy 없이)

def write_npy(path: Path, values: array, n: int, dim: int) -> None:
    """float32 행렬(n×dim)을 .npy v1.0으로 쓴다. `values`는 array('f')."""
    if len(values) != n * dim:
        raise ValueError("값 개수가 n*dim과 다르다")
    header = f"{{'descr': '<f4', 'fortran_order': False, 'shape': ({n}, {dim}), }}"
    pad = 64 - ((10 + len(header) + 1) % 64)
    header = header + " " * (pad % 64) + "\n"
    body = array("f", values)
    if sys.byteorder == "big":
        body.byteswap()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        f.write(b"\x93NUMPY\x01\x00" + len(header).to_bytes(2, "little") + header.encode("latin1"))
        body.tofile(f)
    os.replace(tmp, path)


def read_npy(path: Path) -> tuple[array, int, int]:
    """write_npy가 쓴 파일을 읽는다. (값, n, dim)."""
    import ast

    with open(path, "rb") as f:
        if f.read(6) != b"\x93NUMPY":
            raise ValueError(f"npy가 아니다: {path.name}")
        major = f.read(2)[0]
        hlen = int.from_bytes(f.read(2 if major == 1 else 4), "little")
        meta = ast.literal_eval(f.read(hlen).decode("latin1").strip())
        if meta["descr"] != "<f4" or meta["fortran_order"]:
            raise ValueError("float32 C-순서만 지원한다")
        n, dim = meta["shape"]
        vals = array("f")
        vals.fromfile(f, n * dim)
    if sys.byteorder == "big":
        vals.byteswap()
    return vals, n, dim


def decode_b64_vectors(items: Sequence[str]) -> array:
    """OpenAI `encoding_format=base64` 응답(float32 리틀엔디언)을 한 array로 이어 붙인다."""
    out = array("f")
    for s in items:
        a = array("f")
        a.frombytes(base64.b64decode(s))
        if sys.byteorder == "big":
            a.byteswap()
        out.extend(a)
    return out


# --------------------------------------------------------------------------- 임베딩 호출(캐시·원장·상한 경유)

def resolve_key() -> str | None:
    """환경변수 우선, 없으면 설정(.env)에서. 값은 반환만 하고 출력하지 않는다."""
    from luna_probe import resolve_openai_key  # 지연 import: 시험·plan에서는 쓰지 않는다

    return resolve_openai_key()


def _ensure_cache_importable() -> None:
    """llm_cache가 불러오는 `_common`은 anthropic을 import한다. 백엔드 venv에 없으면 빈 모듈로 대신한다(이 스크립트는 Anthropic을 호출하지 않는다)."""
    try:
        import anthropic  # noqa: F401
    except ImportError:
        sys.modules["anthropic"] = types.ModuleType("anthropic")


def http_embed(model_id: str, texts: list[str], key: str) -> dict[str, Any]:
    """실제 호출 1회. JSON 직렬화 가능한 응답 {"data": [b64...], "tokens": int}를 돌려준다. 키는 헤더로만 쓴다."""
    import httpx

    r = httpx.post(
        ENDPOINT,
        json={"model": model_id, "input": texts, "encoding_format": "base64"},
        headers={"Authorization": f"Bearer {key}"},
        timeout=180,
    )
    if r.status_code != 200:
        raise RuntimeError(f"임베딩 호출 실패 status={r.status_code} body={r.text[:200]}")
    body = r.json()
    rows = sorted(body["data"], key=lambda d: d["index"])
    return {"data": [d["embedding"] for d in rows], "tokens": int(body["usage"]["total_tokens"])}


class Embedder:
    """배치 임베딩. 호출마다 (1) --max-usd 하드 상한, (2) 개발 원장 guard, (3) 캐시를 거친다."""

    def __init__(self, size: str, max_usd: float, fetch: Callable[[str, list[str]], dict[str, Any]], ledger: CostLedger | None = None) -> None:
        self.size, self.model_id = size, MODELS[size]
        self.max_usd = max_usd
        self._fetch = fetch
        self.ledger = ledger or CostLedger()
        self.spent = 0.0  # 이 실행에서 실제로 쓴 비용
        self.calls = 0
        self.cached_batches = 0
        self.tokens = 0

    def embed_batch(self, texts: list[str], tag: str) -> list[str]:
        est = cost_usd(sum(estimate_tokens(t) for t in texts) * ESTIMATE_MARGIN, self.size)
        called: list[int] = []

        def fetch() -> dict[str, Any]:
            if self.spent + est > self.max_usd:  # 실호출 직전 하드 상한(캐시 적중이면 여기까지 오지 않는다)
                raise CapReached(f"--max-usd ${self.max_usd:.2f} 초과 예상: 이 실행 ${self.spent:.4f} + 이번 배치 추정 ${est:.4f}. 호출 전에 중단했다")
            resp = self._fetch(self.model_id, texts)
            called.append(1)
            return resp

        def real_cost(resp: dict[str, Any]) -> float:
            return cost_usd(resp["tokens"], self.size)

        messages = [{"role": "user", "content": texts}]
        resp = cached_openai_call(
            self.model_id, messages, {"encoding_format": "base64"}, fetch, cost_fn=real_cost, estimate_usd=est, ledger=self.ledger, tag=tag
        )
        if called:
            self.calls += 1
            self.tokens += resp["tokens"]
            self.spent += real_cost(resp)
            if self.spent > self.max_usd:
                raise CapReached(f"--max-usd ${self.max_usd:.2f} 도달(실제 ${self.spent:.4f}). 이후 배치는 호출하지 않는다")
        else:
            self.cached_batches += 1
        return list(resp["data"])


def embed_texts(emb: Embedder, texts: Sequence[str], tag: str) -> tuple[array, int]:
    """texts 전체를 배치로 임베딩해 (이어 붙인 값, 차원)을 돌려준다."""
    out = array("f")
    dim = 0
    for bi, chunk in enumerate(batches(texts)):
        vecs = decode_b64_vectors(emb.embed_batch(chunk, f"{tag}:{bi}"))
        if len(vecs) % len(chunk):
            raise ValueError("응답 벡터 수가 입력 수와 맞지 않는다")
        dim = len(vecs) // len(chunk)
        out.extend(vecs)
    return out, dim


# --------------------------------------------------------------------------- 검색 시스템

def _topk_python(qvecs: array, dvecs: array, nq: int, nd: int, dim: int, k: int) -> list[list[int]]:
    """numpy 없이 코사인 상위 k(시험·작은 입력용). 큰 입력은 numpy를 쓴다."""

    def norm(v: Sequence[float]) -> float:
        return math.sqrt(sum(x * x for x in v)) or 1.0

    docs = [dvecs[i * dim : (i + 1) * dim] for i in range(nd)]
    dn = [norm(d) for d in docs]
    out = []
    for qi in range(nq):
        q = qvecs[qi * dim : (qi + 1) * dim]
        qn = norm(q)
        sims = [(sum(a * b for a, b in zip(q, docs[i], strict=True)) / (qn * dn[i]), i) for i in range(nd)]
        sims.sort(key=lambda t: (-t[0], t[1]))
        out.append([i for _, i in sims[:k]])
    return out


def dense_topk(qvecs: array, dvecs: array, nq: int, nd: int, dim: int, k: int = DEPTH) -> list[list[int]]:
    """질의별 코사인 상위 k 문서 번호(동점은 번호 순)."""
    try:
        import numpy as np
    except ImportError:
        return _topk_python(qvecs, dvecs, nq, nd, dim, k)
    q = np.frombuffer(qvecs, dtype=np.float32).reshape(nq, dim)
    d = np.frombuffer(dvecs, dtype=np.float32).reshape(nd, dim)
    q = q / np.maximum(np.linalg.norm(q, axis=1, keepdims=True), 1e-12)
    d = d / np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-12)
    out: list[list[int]] = []
    kk = min(k, nd)
    for lo in range(0, nq, 64):
        sims = q[lo : lo + 64] @ d.T
        part = np.argpartition(-sims, kk - 1, axis=1)[:, :kk]
        for r in range(part.shape[0]):
            idx = part[r]
            order = sorted(idx.tolist(), key=lambda i: (-float(sims[r, i]), i))
            out.append(order)
    return out


def bm25_topk(dd: DrugDict, query: str, k: int = DEPTH) -> list[int]:
    """사전의 문자 n-gram BM25(문서 번호 = 제품 뒤 성분). 점수 0은 제외한다."""
    scores = dd._bm25.scores(char_ngrams(normalize_name(query)))
    return [d for d, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]


def rrf(rankings: Sequence[Sequence[int]], k: int = RRF_K, depth: int = DEPTH) -> list[int]:
    """단순 RRF: 점수 = Σ 1/(k+순위). 동점은 문서 번호 순."""
    acc: dict[int, float] = {}
    for ranking in rankings:
        for r, d in enumerate(ranking[:depth], start=1):
            acc[d] = acc.get(d, 0.0) + 1.0 / (k + r)
    return [d for d, _ in sorted(acc.items(), key=lambda kv: (-kv[1], kv[0]))][:depth]


# --------------------------------------------------------------------------- 지표

def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 95% 구간. n=0이면 (0, 1)."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, center - half), min(1.0, center + half)


def gold_doc_sets(dd: DrugDict, queries: Sequence[dict[str, Any]]) -> list[set[int]]:
    """질의별 정답 문서 번호 집합(제품 번호 = 인덱스, 성분 번호 = 제품 수 + 인덱스)."""
    n_prod = len(dd.products)
    by_seq = {p["item_seq"]: i for i, p in enumerate(dd.products) if p.get("item_seq")}
    by_ing: dict[int, list[int]] = {}
    for i, p in enumerate(dd.products):
        for j in p.get("ingredient_ids", []):
            by_ing.setdefault(j, []).append(i)
    out = []
    for q in queries:
        a = q["answer"]
        gold = {by_seq[s] for s in a["item_seqs"] if s in by_seq}
        for j in a["ingredient_ids"]:
            gold.add(n_prod + j)
            if a.get("ingredient_products_ok"):
                gold.update(by_ing.get(j, []))
        out.append(gold)
    return out


def tally(rankings: Sequence[Sequence[int]], golds: Sequence[set[int]], types: Sequence[str]) -> dict[str, dict[str, int]]:
    """유형별·전체 {n, top1, top5} 정수 집계."""
    res: dict[str, dict[str, int]] = {t: {"n": 0, "top1": 0, "top5": 0} for t in (*QUERY_TYPES, "all")}
    for ranking, gold, t in zip(rankings, golds, types, strict=True):
        for key in (t, "all"):
            cell = res[key]
            cell["n"] += 1
            cell["top1"] += bool(ranking[:1] and ranking[0] in gold)
            cell["top5"] += any(d in gold for d in ranking[:5])
    return res


def with_intervals(counts: dict[str, dict[str, int]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for t, c in counts.items():
        cell: dict[str, Any] = {"n": c["n"], "small_n": c["n"] <= 8}
        for m in ("top1", "top5"):
            lo, hi = wilson(c[m], c["n"])
            cell[m] = {"k": c[m], "n": c["n"], "rate": round(c[m] / c["n"], 4) if c["n"] else None, "wilson95": [round(lo, 4), round(hi, 4)]}
        out[t] = cell
    return out


# --------------------------------------------------------------------------- 명령

def load_or_build_queries(dd: DrugDict) -> list[dict[str, Any]]:
    if QUERIES_PATH.exists():
        data = json.loads(QUERIES_PATH.read_text(encoding="utf-8"))
        if data.get("dict_version") == dd.version:
            return data["queries"]
    return build_dev_queries(dd)


def cmd_queries(args: argparse.Namespace) -> int:
    dd = DrugDict.load()
    qs = build_dev_queries(dd, seed=args.seed)
    payload = {"dict_version": dd.version, "seed": args.seed, "per_type": PER_TYPE, "purpose": "개발용(평가 세트·시험셋 아님, RFP-26-04)",
               "fingerprint": queries_fingerprint(qs), "queries": qs}
    QUERIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    QUERIES_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = {t: sum(1 for q in qs if q["type"] == t) for t in QUERY_TYPES}
    print(f"질의 {len(qs)}개 저장: {QUERIES_PATH.name} 유형별 {counts}")
    return 0


def plan_numbers(dd: DrugDict, queries: Sequence[dict[str, Any]]) -> dict[str, Any]:
    docs = dd.doc_texts()
    qtexts = [q["query"] for q in queries]
    dtok, method = count_tokens(docs)
    qtok, _ = count_tokens(qtexts)
    n_doc_batches = len(batches(docs))
    n_q_batches = len(batches(qtexts))
    out: dict[str, Any] = {
        "docs": len(docs), "doc_chars": sum(len(t) for t in docs), "queries": len(qtexts), "token_method": method,
        "doc_tokens": round(dtok), "query_tokens": round(qtok), "doc_batches": n_doc_batches, "query_batches": n_q_batches, "models": {},
    }
    for size in MODELS:
        out["models"][size] = {
            "model": MODELS[size], "calls": n_doc_batches + n_q_batches, "price_per_1M_usd": PRICE_PER_M[size],
            "est_usd_docs": round(cost_usd(dtok, size), 5), "est_usd_queries": round(cost_usd(qtok, size), 6), "est_usd_total": round(cost_usd(dtok + qtok, size), 5),
        }
    return out


def cmd_plan(args: argparse.Namespace) -> int:
    dd = DrugDict.load()
    qs = load_or_build_queries(dd)
    p = plan_numbers(dd, qs)
    print(f"사전 {dd.version}: 문서 {p['docs']:,}개(제품 {len(dd.products):,} + 성분 {len(dd.ingredients):,}), 질의 {p['queries']}개")
    print(f"토큰 어림 방법: {p['token_method']}")
    print(f"문서 토큰 ≈ {p['doc_tokens']:,}, 질의 토큰 ≈ {p['query_tokens']:,}")
    print(f"배치: 문서 {p['doc_batches']}회 + 질의 {p['query_batches']}회 (배치 {BATCH_SIZE})")
    for size, m in p["models"].items():
        print(f"- {m['model']} ({size}): 호출 {m['calls']}회, 단가 ${m['price_per_1M_usd']}/1M, 예상 ${m['est_usd_total']} (문서 ${m['est_usd_docs']} + 질의 ${m['est_usd_queries']})")
    print("호출 0(plan은 OpenAI를 부르지 않는다). 토큰 근사는 보수적이라 실제는 이보다 적을 수 있다.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    size = args.model
    if args.max_usd <= 0:
        print("--max-usd는 0보다 커야 한다")
        return 2
    out = EMB_DIR / f"{MODELS[size]}.npy"
    if out.exists() and not args.force:
        print(f"{out.name}이 이미 있다. 이 모델은 한 번만 실행한다(다시 만들려면 --force, 캐시가 있으면 호출 없이 재구성된다).")
        return 0
    key = resolve_key()
    if not key:
        print("OPENAI_API_KEY를 환경변수나 .env 설정에서 찾지 못했다.")
        return 2
    if os.environ.get("MEDIAGENT_EVAL", "").strip() in ("", "0", "false", "False"):
        os.environ.setdefault("LLM_CACHE", "record")  # 캐시 없이 돌려 재시작 시 비용이 중복되는 것을 막는다
    if cache_mode() == "off":
        print("LLM_CACHE=off에서는 실행하지 않는다(재시작 시 중복 비용). LLM_CACHE=record로 실행한다.")
        return 2
    _ensure_cache_importable()

    dd = DrugDict.load()
    qs = load_or_build_queries(dd)
    docs = dd.doc_texts()
    emb = Embedder(size, args.max_usd, lambda model_id, texts: http_embed(model_id, texts, key))
    t0 = time.perf_counter()
    try:
        dvec, dim = embed_texts(emb, docs, f"be10-docs-{size}")
        qvec, qdim = embed_texts(emb, [q["query"] for q in qs], f"be10-queries-{size}")
    except (CapReached, BudgetExceeded) as exc:
        print(f"중단: {exc}")
        print(f"이 실행 비용 ${emb.spent:.4f}, 호출 {emb.calls}회, 캐시 적중 배치 {emb.cached_batches}개. 같은 명령을 다시 실행하면 캐시된 배치는 건너뛴다.")
        return 3
    if dim != qdim:
        print("문서와 질의 벡터 차원이 다르다")
        return 1
    write_npy(out, dvec, len(docs), dim)
    write_npy(EMB_DIR / f"{MODELS[size]}.queries.npy", qvec, len(qs), dim)
    meta = {"model": MODELS[size], "dim": dim, "docs": len(docs), "queries": len(qs), "dict_version": dd.version, "queries_fingerprint": queries_fingerprint(qs),
            "run_calls": emb.calls, "run_cached_batches": emb.cached_batches, "run_tokens": emb.tokens, "run_usd": round(emb.spent, 6),
            "seconds": round(time.perf_counter() - t0, 1)}
    (EMB_DIR / f"{MODELS[size]}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"완료 {out.name}: 문서 {len(docs):,} × {dim}차원, 호출 {emb.calls}회(캐시 적중 {emb.cached_batches}), 토큰 {emb.tokens:,}, 비용 ${emb.spent:.4f}")
    return 0


def _load_model(size: str, dd: DrugDict, qs: Sequence[dict[str, Any]]) -> tuple[array, array, int] | None:
    base = EMB_DIR / MODELS[size]
    mp = Path(f"{base}.meta.json")
    if not (Path(f"{base}.npy").exists() and Path(f"{base}.queries.npy").exists() and mp.exists()):
        return None
    meta = json.loads(mp.read_text(encoding="utf-8"))
    if meta["dict_version"] != dd.version or meta["queries_fingerprint"] != queries_fingerprint(qs):
        raise SystemExit(f"{MODELS[size]} 벡터가 현재 사전·질의 세트와 맞지 않는다(사전 버전 또는 질의 지문 불일치). 다시 run 한다.")
    dvec, nd, dim = read_npy(Path(f"{base}.npy"))
    qvec, nq, qdim = read_npy(Path(f"{base}.queries.npy"))
    if nd != len(dd.products) + len(dd.ingredients) or nq != len(qs) or dim != qdim:
        raise SystemExit(f"{MODELS[size]} 벡터 모양이 맞지 않는다")
    return dvec, qvec, dim


def evaluate(dd: DrugDict, qs: Sequence[dict[str, Any]], vectors: dict[str, tuple[array, array, int]]) -> dict[str, Any]:
    golds = gold_doc_sets(dd, qs)
    types = [q["type"] for q in qs]
    bm = [bm25_topk(dd, q["query"]) for q in qs]
    systems: dict[str, list[list[int]]] = {"BM25 단독": bm}
    n_doc = len(dd.products) + len(dd.ingredients)
    for size, (dvec, qvec, dim) in vectors.items():
        dense = dense_topk(qvec, dvec, len(qs), n_doc, dim)
        systems[f"임베딩 단독({size})"] = dense
        systems[f"하이브리드 BM25+{size} (RRF)"] = [rrf([b, d]) for b, d in zip(bm, dense, strict=True)]
    return {name: with_intervals(tally(r, golds, types)) for name, r in systems.items()}


def render_md(report: dict[str, Any]) -> str:
    lines = [
        "# BE-10 임베딩 비교 시험 결과 (개발용 질의 세트, 측정 전 참고값)", "",
        f"- 사전: `{report['dict_version']}`, 문서 {report['docs']:,}개, 질의 {report['queries']}개(시드 {report['seed']}, 지문 `{report['queries_fingerprint']}`)",
        "- 질의는 사전 제품명에서 규칙으로 합성한 **개발용**이다. 평가 세트·시험셋이 아니며(RFP-26-04) 이 표를 평가 수치로 쓰지 않는다.",
        "- 숫자는 k/n과 Wilson 95% 구간이다. 칸당 n이 8 이하이면 유의성을 주장하지 않는다(9.1절). 시스템 간 차이는 구간이 겹치면 구분하지 못한 것으로 읽는다.",
        "- 정답: 제품 질의는 같은 이름 제품 전부, 접두 질의는 그 접두의 제품 전부, 성분 질의는 그 성분 문서 또는 그 성분을 가진 제품.", "",
        "## 전체 (top-1 / top-5)", "", "| 시스템 | top-1 | top-5 |", "|---|---|---|",
    ]

    def cell(c: dict[str, Any]) -> tuple[str, str]:
        t1, t5 = c["top1"], c["top5"]
        flag = " (n≤8)" if c["small_n"] else ""
        return f"{t1['k']}/{t1['n']} [{t1['wilson95'][0]:.2f}–{t1['wilson95'][1]:.2f}]{flag}", f"{t5['k']}/{t5['n']} [{t5['wilson95'][0]:.2f}–{t5['wilson95'][1]:.2f}]{flag}"

    for name, res in report["systems"].items():
        a, b = cell(res["all"])
        lines.append(f"| {name} | {a} | {b} |")
    for t in QUERY_TYPES:
        lines += ["", f"## {TYPE_LABELS[t]} (n={next(iter(report['systems'].values()))[t]['n']})", "", "| 시스템 | top-1 | top-5 |", "|---|---|---|"]
        for name, res in report["systems"].items():
            a, b = cell(res[t])
            lines.append(f"| {name} | {a} | {b} |")
    if report.get("missing_models"):
        lines += ["", f"미실행 모델(벡터 없음): {', '.join(report['missing_models'])}"]
    if report.get("run_meta"):
        lines += ["", "## 실행 기록", ""]
        for m in report["run_meta"].values():
            lines.append(f"- {m['model']}: {m['dim']}차원, 실행 호출 {m['run_calls']}회, 토큰 {m['run_tokens']:,}, 비용 ${m['run_usd']}")
    return "\n".join(lines) + "\n"


def cmd_report(args: argparse.Namespace) -> int:
    dd = DrugDict.load()
    qs = load_or_build_queries(dd)
    vectors: dict[str, tuple[array, array, int]] = {}
    missing = []
    run_meta = {}
    for size in MODELS:
        v = _load_model(size, dd, qs)
        if v is None:
            missing.append(MODELS[size])
        else:
            vectors[size] = v
            run_meta[size] = json.loads(Path(f"{EMB_DIR / MODELS[size]}.meta.json").read_text(encoding="utf-8"))
    report = {
        "dict_version": dd.version, "docs": len(dd.products) + len(dd.ingredients), "queries": len(qs), "seed": QUERY_SEED,
        "queries_fingerprint": queries_fingerprint(qs), "purpose": "개발용 비교. 평가 수치로 쓰지 않는다", "missing_models": missing, "run_meta": run_meta,
        "systems": evaluate(dd, qs, vectors),
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    REPORT_MD.write_text(render_md(report), encoding="utf-8")
    print(f"저장: {REPORT_JSON.name}, {REPORT_MD.name} (시스템 {len(report['systems'])}종, 미실행 {missing or '없음'})")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("queries")
    q.add_argument("--seed", type=int, default=QUERY_SEED)
    q.set_defaults(fn=cmd_queries)
    sub.add_parser("plan").set_defaults(fn=cmd_plan)
    r = sub.add_parser("run")
    r.add_argument("--model", choices=sorted(MODELS), required=True)
    r.add_argument("--max-usd", type=float, required=True)
    r.add_argument("--force", action="store_true")
    r.set_defaults(fn=cmd_run)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    install_excepthook()  # S-05: 키를 쓰는 스크립트의 예외·logging 출력 가리기
    raise SystemExit(main())
