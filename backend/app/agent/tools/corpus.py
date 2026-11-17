"""근거 코퍼스 검색 계층(AG-03 오프라인 골격). 외부 호출·원격 DB 접속 없음.

- `CorpusIndex`: 로컬 청크(jsonl) → 메모리 BM25 문자 2-gram 인덱스 + 메타 필터 색인.
- **사전 필터가 먼저다**: `ChunkFilter`(계층·성분코드·성분명·품목기준코드·`pair_id`·고시번호·기준일…)로 후보 범위를 좁힌 뒤에만 점수를 매긴다.
- 의미(벡터) 검색은 **주입 함수**(`VectorSearchFn`)다. 없으면 BM25 단독이다. 원격 pgvector는 이 프로토콜을 만족하는 어댑터로 붙인다.
- 하이브리드는 RRF(k=60, 깊이 100)로 합친다. 주입된 벡터 결과도 사전 필터 후보 밖이면 버린다(필터 위반 0).
- `expand_chunks`: 찾은 청크의 `parent_id`·`refs`·같은 `pair_id`·같은 품목 같은 절 청크를 **코드가** 붙인다(임베딩으로 추측하지 않는다).

검색은 판정하지 않는다. 금기 여부는 `check_contraindications`만 말한다.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.tools.drug_dict import BM25

DEFAULT_CORPUS_DIR = Path(__file__).resolve().parents[4] / "data" / "mock" / "corpus"
CORPUS_FILES = ("l1_notice.jsonl", "l2_chunks.jsonl", "l3_eyak.jsonl", "l3_prmsn.jsonl")

RRF_K = 60
RRF_DEPTH = 100

_WORD_RE = re.compile(r"[0-9a-z가-힣]+")
_LOCATOR_NO_RE = re.compile(r"#(\d+)\s*$")


def tokenize(text: str) -> list[str]:
    """NFKC·소문자 → 단어별 문자 2-gram(한 글자 단어는 그대로). 단어 경계를 넘는 n-gram은 만들지 않는다."""
    out: list[str] = []
    for w in _WORD_RE.findall(unicodedata.normalize("NFKC", text or "").lower()):
        if len(w) == 1:
            out.append(w)
        else:
            out.extend(w[i : i + 2] for i in range(len(w) - 1))
    return out


def name_key(text: str) -> str:
    """성분명 비교 키: NFKC·소문자·영숫자·한글만."""
    return "".join(_WORD_RE.findall(unicodedata.normalize("NFKC", text or "").lower()))


@dataclass(frozen=True)
class ChunkFilter:
    """검색 전에 후보 범위를 정하는 메타 조건. 값이 있는 칸끼리는 AND, 한 칸 안의 여러 값은 OR."""

    layers: frozenset[str] | None = None
    chunk_kinds: frozenset[str] | None = None
    doc_types: frozenset[str] | None = None
    ingr_codes: frozenset[str] | None = None
    ingr_names: frozenset[str] | None = None   # 성분명(부분 일치, 정규화 키). 성분코드가 없는 L1 행·e약은요 품목명 범위용
    item_seq: str | None = None
    pair_ids: frozenset[str] | None = None
    notice_no: str | None = None
    base_date: str | None = None
    sections: frozenset[str] | None = None     # 라벨 절 이름 정확 일치(e약은요 "상호작용" 등)
    section_prefix: str | None = None          # 허가 상세 절 코드 접두("UD" → `UD 본문`·`UD 1. …`). `sections`와는 OR
    years: frozenset[int] | None = None        # 연도(`year` 칸, FR-03). `year`가 빈(None) 청크는 걸리지 않는다(notice_no·base_date와 같은 규칙)
    issuers: frozenset[str] | None = None      # 부처·발행기관(`issuer` 칸 정확 일치, FR-03). 예: 식품의약품안전처·한국의약품안전관리원

    @property
    def id_scoped(self) -> bool:
        """성분코드·품목·쌍·고시번호 같은 식별 조건이 있어 범위가 이미 좁혀져 있는가."""
        return bool(self.ingr_codes or self.ingr_names or self.item_seq or self.pair_ids or self.notice_no)


@dataclass(frozen=True)
class Hit:
    chunk: dict[str, Any]
    score: float            # RRF 합 점수(필터만 쓴 경우 0.0)
    bm25_rank: int | None   # 1부터. 없으면 None
    vector_rank: int | None
    via: str                # "bm25" | "vector" | "both" | "filter"


@dataclass(frozen=True)
class Expansion:
    chunk: dict[str, Any]
    relation: str           # "parent" | "ref" | "pair" | "section"
    from_id: str


class VectorSearchFn(Protocol):
    """주입 벡터 검색. 질의 문장을 임베딩해 `(chunk_id, 점수)`를 점수 큰 순으로 최대 `k`개 돌려준다.

    `filters`는 SQL `WHERE`로 옮길 수 있게 그대로 넘긴다(원격 pgvector는 같은 조건을 서버에서 건다).
    돌려준 ID가 사전 필터 후보 밖이면 `CorpusIndex.search`가 버린다.
    """

    def __call__(self, query: str, *, k: int, filters: ChunkFilter) -> Sequence[tuple[str, float]]: ...


def rrf_fuse(rankings: Sequence[Sequence[str]], *, k: int = RRF_K, depth: int = RRF_DEPTH) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion. 각 순위표의 앞 `depth`개만 쓴다. 점수 동률은 먼저 나온 순서를 지킨다."""
    acc: dict[str, float] = {}
    order: dict[str, int] = {}
    for ranking in rankings:
        for r, cid in enumerate(ranking[:depth], start=1):
            acc[cid] = acc.get(cid, 0.0) + 1.0 / (k + r)
            order.setdefault(cid, len(order))
    return sorted(acc.items(), key=lambda kv: (-kv[1], order[kv[0]]))


@dataclass
class CorpusIndex:
    chunks: list[dict[str, Any]]
    _by_id: dict[str, int] = field(init=False, repr=False)
    _bm25: BM25 = field(init=False, repr=False)
    _maps: dict[str, dict[str, set[int]]] = field(init=False, repr=False)
    _name_keys: dict[str, set[int]] = field(init=False, repr=False)
    _pair: dict[str, list[int]] = field(init=False, repr=False)
    _section: dict[tuple[str, str], list[int]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._by_id = {}
        self._maps = {k: defaultdict(set) for k in ("layer", "kind", "doc_type", "code", "item_seq", "notice", "base_date", "pair", "section",
                                                    "year", "issuer")}
        self._name_keys = defaultdict(set)
        self._pair = defaultdict(list)
        self._section = defaultdict(list)
        for i, c in enumerate(self.chunks):
            self._by_id.setdefault(c["chunk_id"], i)
            self._maps["layer"][c.get("layer", "")].add(i)
            self._maps["kind"][c.get("chunk_kind", "")].add(i)
            self._maps["doc_type"][c.get("doc_type", "")].add(i)
            for code in c.get("ingr_codes") or []:
                self._maps["code"][code].add(i)
            if c.get("item_seq"):
                self._maps["item_seq"][c["item_seq"]].add(i)
            if c.get("notice_no"):
                self._maps["notice"][c["notice_no"]].add(i)
            if c.get("base_date"):
                self._maps["base_date"][c["base_date"]].add(i)
            if c.get("pair_id"):
                self._maps["pair"][c["pair_id"]].add(i)
                self._pair[c["pair_id"]].append(i)
            if c.get("section"):
                self._maps["section"][c["section"]].add(i)
            if c.get("year") not in (None, ""):
                self._maps["year"][str(int(c["year"]))].add(i)  # jsonl int·원격 SMALLINT·문자열 모두 같은 키
            if c.get("issuer"):
                self._maps["issuer"][c["issuer"]].add(i)
            if c.get("item_seq") and c.get("section"):
                self._section[(c["item_seq"], _section_head(c["section"]))].append(i)
            for nm in list(c.get("ingr_names") or []) + ([c["item_name"]] if c.get("item_name") else []):
                k = name_key(str(nm))
                if k:
                    self._name_keys[k].add(i)
        self._bm25 = BM25(tokenize(c.get("text", "")) for c in self.chunks)

    @classmethod
    def from_db(cls, conn_factory: Any, *, batch: int = 5000) -> CorpusIndex:
        """원격 Supabase `corpus_chunks`(읽기 전용 SELECT)에서 서버 시작 시 1회 구성한다. 구현은 `corpus_remote`."""
        from app.agent.tools.corpus_remote import load_corpus_from_db  # noqa: PLC0415 - 순환 import 방지

        return load_corpus_from_db(conn_factory, batch=batch)

    # ------------------------------------------------------------------ 조회

    def __len__(self) -> int:
        return len(self.chunks)

    def get(self, chunk_id: str) -> dict[str, Any] | None:
        i = self._by_id.get(chunk_id)
        return None if i is None else self.chunks[i]

    def candidates(self, flt: ChunkFilter) -> set[int]:
        """사전 필터를 통과하는 청크 번호 집합(조건이 없으면 전체)."""
        sets: list[set[int]] = []

        def union(kind: str, values: Iterable[str]) -> set[int]:
            out: set[int] = set()
            for v in values:
                out |= self._maps[kind].get(v, set())
            return out

        if flt.layers is not None:
            sets.append(union("layer", flt.layers))
        if flt.chunk_kinds is not None:
            sets.append(union("kind", flt.chunk_kinds))
        if flt.doc_types is not None:
            sets.append(union("doc_type", flt.doc_types))
        if flt.ingr_codes is not None:
            sets.append(union("code", flt.ingr_codes))
        if flt.ingr_names is not None:
            keys = [k for k in (name_key(n) for n in flt.ingr_names) if k]
            hit: set[int] = set()
            for nk, ids in self._name_keys.items():
                if any(k in nk for k in keys):
                    hit |= ids
            sets.append(hit)
        if flt.item_seq is not None:
            sets.append(set(self._maps["item_seq"].get(flt.item_seq, set())))
        if flt.pair_ids is not None:
            sets.append(union("pair", flt.pair_ids))
        if flt.notice_no is not None:
            sets.append(set(self._maps["notice"].get(flt.notice_no, set())))
        if flt.base_date is not None:
            sets.append(set(self._maps["base_date"].get(flt.base_date, set())))
        if flt.years is not None:
            sets.append(union("year", (str(int(y)) for y in flt.years)))
        if flt.issuers is not None:
            sets.append(union("issuer", flt.issuers))
        if flt.sections is not None or flt.section_prefix is not None:  # 두 조건은 OR(e약은요 절 이름 또는 허가 상세 절 코드)
            sec: set[int] = union("section", flt.sections or ())
            if flt.section_prefix is not None:
                pre = flt.section_prefix
                for name, ids in self._maps["section"].items():
                    if name == pre or name.startswith(pre + " "):
                        sec |= ids
            sets.append(sec)
        if not sets:
            return set(range(len(self.chunks)))
        sets.sort(key=len)
        out = set(sets[0])
        for s in sets[1:]:
            out &= s
            if not out:
                break
        return out

    def matches(self, chunk: dict[str, Any], flt: ChunkFilter) -> bool:
        """청크가 필터를 만족하는가(시험·방어용 재검사)."""
        i = self._by_id.get(chunk["chunk_id"])
        return i is not None and i in self.candidates(flt)

    # ------------------------------------------------------------------ 검색

    def search(self, query: str, flt: ChunkFilter | None = None, *, top_k: int = 5, vector_fn: VectorSearchFn | None = None,
               depth: int = RRF_DEPTH, rrf_k: int = RRF_K) -> list[Hit]:
        """사전 필터 → BM25(+주입 벡터) → RRF. 후보 밖 ID는 어느 경로에서든 버린다.

        코드 검사(RFP-22-02 A): 어휘 점수가 0이고 식별 조건(성분코드·품목·쌍 등)도 없는 청크는 근거로 세우지 않는다(벡터가 항상 k개를 돌려주기 때문).
        질의가 비어 있고 식별 조건이 있으면 후보를 안정 순서로 돌려준다(`via="filter"`).
        """
        flt = flt or ChunkFilter()
        cand = self.candidates(flt)
        if not cand or top_k <= 0:
            return []
        if not query.strip():
            if not flt.id_scoped:
                return []
            return [Hit(self.chunks[i], 0.0, None, None, "filter") for i in sorted(cand)[:top_k]]

        scores = {i: s for i, s in self._bm25.scores(tokenize(query)).items() if i in cand}
        bm = sorted(scores, key=lambda i: (-scores[i], i))[:depth]
        bm_ids = [self.chunks[i]["chunk_id"] for i in bm]
        vec_ids: list[str] = []
        if vector_fn is not None:
            seen: set[str] = set()
            for cid, _ in vector_fn(query, k=depth, filters=flt):
                i = self._by_id.get(cid)
                if i is not None and i in cand and cid not in seen:
                    seen.add(cid)
                    vec_ids.append(cid)
        fused = rrf_fuse([bm_ids, vec_ids] if vec_ids else [bm_ids], k=rrf_k, depth=depth)
        bm_rank = {c: r for r, c in enumerate(bm_ids, start=1)}
        vec_rank = {c: r for r, c in enumerate(vec_ids, start=1)}
        hits: list[Hit] = []
        for cid, sc in fused:
            lexical = self._by_id[cid] in scores
            if not lexical and not flt.id_scoped:
                continue
            b, v = bm_rank.get(cid), vec_rank.get(cid)
            via = "both" if (b and v) else ("bm25" if b else "vector")
            hits.append(Hit(self.chunks[self._by_id[cid]], sc, b, v, via))
            if len(hits) >= top_k:
                break
        return hits

    # ------------------------------------------------------------------ 연결 청크

    def dangling_refs(self) -> list[tuple[str, str]]:
        """`(chunk_id, 끊어진 대상 id)` 목록. 시험에서 비어 있어야 한다."""
        bad: list[tuple[str, str]] = []
        for c in self.chunks:
            for t in ([c["parent_id"]] if c.get("parent_id") else []) + list(c.get("refs") or []):
                if t not in self._by_id:
                    bad.append((c["chunk_id"], t))
        return bad

    def section_siblings(self, chunk: dict[str, Any]) -> list[dict[str, Any]]:
        """같은 품목·같은 절의 청크(문단 번호 `#n` 순). 절 전체를 붙일 때 쓴다(H16)."""
        if not (chunk.get("item_seq") and chunk.get("section")):
            return []
        ids = self._section.get((chunk["item_seq"], _section_head(chunk["section"])), [])
        return sorted((self.chunks[i] for i in ids), key=_para_order)


def _section_head(section: str) -> str:
    """절 묶음 키. 허가 상세 효능(EE)·용법용량(UD)은 짧아 한 절로 묶고, 주의사항(NB)은 소제목(`NB 5. 일반적 주의`)별로 묶는다. e약은요는 절 이름 그대로."""
    s = section.strip()
    return s.split(" ", 1)[0] if s.split(" ", 1)[0] in ("EE", "UD") else s


def _para_order(c: dict[str, Any]) -> tuple[int, str]:
    m = _LOCATOR_NO_RE.search(c.get("locator", ""))
    return (int(m.group(1)) if m else 0, c["chunk_id"])


def expand_chunks(index: CorpusIndex, hits: Sequence[dict[str, Any]], *, max_parent_depth: int = 3, pair_cap: int = 4,
                  section_cap: int = 10, max_total: int = 20) -> list[Expansion]:
    """찾은 청크에 연결 청크를 코드가 붙인다: 부모 사슬 → `refs` → 같은 `pair_id` → 같은 품목·절 형제.

    이미 찾은 청크와 중복은 넣지 않는다. 총 `max_total`개까지(증거 묶음 크기 제한). 끊어진 참조는 건너뛴다(시험이 0건을 검사).
    """
    seen = {h["chunk_id"] for h in hits}
    out: list[Expansion] = []

    def add(c: dict[str, Any] | None, relation: str, src: str) -> None:
        if c is None or c["chunk_id"] in seen or len(out) >= max_total:
            return
        seen.add(c["chunk_id"])
        out.append(Expansion(c, relation, src))

    for h in hits:
        cur, depth = h, 0
        while cur.get("parent_id") and depth < max_parent_depth:
            parent = index.get(cur["parent_id"])
            add(parent, "parent", h["chunk_id"])
            if parent is None:
                break
            cur, depth = parent, depth + 1
        for r in h.get("refs") or []:
            add(index.get(r), "ref", h["chunk_id"])
        if h.get("pair_id"):
            n = 0
            for i in index._pair.get(h["pair_id"], []):  # noqa: SLF001 - 같은 모듈 내부 색인
                c = index.chunks[i]
                if c["chunk_id"] != h["chunk_id"] and c["chunk_id"] not in seen and n < pair_cap:
                    add(c, "pair", h["chunk_id"])
                    n += 1
        for c in index.section_siblings(h)[:section_cap]:
            add(c, "section", h["chunk_id"])
    return out


def load_jsonl(paths: Iterable[Path]) -> list[dict[str, Any]]:
    """jsonl 청크 파일들을 읽는다. 같은 `chunk_id`는 한 번만(앞선 것 유지)."""
    seen: set[str] = set()
    chunks: list[dict[str, Any]] = []
    for p in paths:
        with Path(p).open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                c = json.loads(line)
                if c["chunk_id"] in seen:
                    continue
                seen.add(c["chunk_id"])
                chunks.append(c)
    return chunks


def load_local_corpus(directory: Path = DEFAULT_CORPUS_DIR) -> CorpusIndex | None:
    """로컬 코퍼스 4종을 한 인덱스로 읽는다. 파일이 하나라도 없으면 None(시험은 skip)."""
    paths = [Path(directory) / n for n in CORPUS_FILES]
    if not all(p.is_file() for p in paths):
        return None
    return CorpusIndex(load_jsonl(paths))
