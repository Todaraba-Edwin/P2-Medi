"""AG-03 검색 도구 3개의 공통부: 인자 조각, 청크 → 도구 출력 계약 항목, 검색 실행.

검색은 판정하지 않는다. 항목 상태는 `FOUND`(근거 청크 있음)·`NO_EVIDENCE`(없음)뿐이고, `verdict_allowed=False`로 표시한다.
같은 사실이 API와 RAG 양쪽에서 오면 API 값이 우선이고 RAG는 보조다(PRD-11-05). 청크 본문은 고치지 않고 그대로 싣는다(M 등급 원문 포함).
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Annotated, Any

from pydantic import StringConstraints

from app.agent.tools.context import ToolContext
from app.agent.tools.contract import known_ids
from app.agent.tools.corpus import ChunkFilter, CorpusIndex, Hit, expand_chunks
from app.tools.provenance import SK_CORPUS_QUOTE

MAX_QUERY_LEN = 200
MAX_TOP_K = 10
DEFAULT_TOP_K = 5
MAX_ITEMS = 20  # 도구 한 번 호출이 돌려주는 항목 상한(찾은 청크 + 연결 청크)

Query = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUERY_LEN)]

LABEL_SOURCE_PRMSN = "허가정보 상세"
LABEL_SOURCE_EYAK = "e약은요"

# 청크 종류 → AG-02 표시 계약의 자료 키(없으면 None: 고시 조문·별표는 아직 자료 키가 없다)
DATASET_KEY_BY_KIND = {"l2_combo": "contra_pair", "l2_preg": "pregnancy", "l2_age": "age", "l3_eyak_section": "eyak",
                       "l3_prmsn_para": "prmsn", "l3_prmsn_table": "prmsn"}


def no_control(v: str) -> str:
    if any(unicodedata.category(c).startswith("C") for c in v):
        raise ValueError("제어 문자가 있다")
    return v


def _digest(tool: str, parts: dict[str, Any]) -> str:
    raw = json.dumps({"t": tool, **parts}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]  # noqa: S324 - 식별용 해시


def miss_item(tool: str, key: dict[str, Any], *, reason: str = "SEARCH_MISS", flags: list[str] | None = None) -> dict[str, Any]:
    """근거 없음 항목. 안전하다는 뜻이 아니다. 근거 ID는 질의·필터에서 결정적으로 만든다."""
    return {
        "kind": "search_miss", "status": "NO_EVIDENCE", "subject": [tool], "evidence_id": f"search:{tool}:{_digest(tool, key)}",
        "source": None, "as_of": None, "queried_at_utc": None, "flags": list(flags or []), "matches": [], "dataset_key": None,
        "source_kind": None, "text": None, "missing_reason": reason, "verdict_allowed": False,
    }


def chunk_item(chunk: dict[str, Any], *, relation: str, from_id: str | None, hit: Hit | None, label: bool = False,
               flags: list[str] | None = None) -> dict[str, Any]:
    """청크 1개 → 도구 출력 계약 항목(`source_kind=CORPUS_QUOTE`, 청크 ID, 출처·기준일, 위치)."""
    kind = chunk.get("chunk_kind", "")
    it: dict[str, Any] = {
        "kind": "chunk", "status": "FOUND", "subject": [chunk.get("item_seq") or ",".join(chunk.get("ingr_codes") or []) or chunk.get("locator", "")],
        "evidence_id": chunk["chunk_id"], "source": f"{chunk.get('issuer', '')} {chunk.get('source_ref', '').split('|')[0]}".strip(),
        "as_of": chunk.get("base_date"), "queried_at_utc": None, "flags": list(flags or []), "matches": [],
        "dataset_key": DATASET_KEY_BY_KIND.get(kind), "source_kind": SK_CORPUS_QUOTE, "text": chunk.get("text", ""), "missing_reason": None,
        "verdict_allowed": False,  # 검색 결과만으로 금기 여부를 말하지 않는다(판정은 check_contraindications)
        "layer": chunk.get("layer"), "chunk_kind": kind, "locator": chunk.get("locator"), "notice_no": chunk.get("notice_no") or None,
        "pair_id": chunk.get("pair_id"), "ingr_codes": list(chunk.get("ingr_codes") or []), "parent_id": chunk.get("parent_id"),
        "relation": relation, "from_id": from_id,
        "score": None if hit is None else round(hit.score, 6), "via": None if hit is None else hit.via,
    }
    if chunk.get("item_seq"):
        it["item_seq"], it["section"], it["item_name"] = chunk["item_seq"], chunk.get("section"), chunk.get("item_name")
    if label:
        eyak = chunk.get("doc_type") == "e약은요"
        it["is_label"] = True
        it["label_source"] = LABEL_SOURCE_EYAK if eyak else LABEL_SOURCE_PRMSN
        it["easy_text"] = chunk.get("text") if eyak else None
    return it


def run_search(tool: str, ctx: ToolContext, *, query: str, flt: ChunkFilter, top_k: int, miss_key: dict[str, Any], expand: bool = True,
               label: bool = False, label_flags_for: Any = None) -> dict[str, Any]:
    """공통 검색: 사전 필터 → (BM25 + 주입 벡터) RRF → 연결 청크 → 항목. 결과가 없으면 `NO_EVIDENCE` 1건."""
    index: CorpusIndex | None = ctx.corpus
    if index is None:
        items = [miss_item(tool, miss_key, reason="OUT_OF_SCOPE")]
        return {"items": items, "known_ids": sorted(known_ids(items))}
    hits = index.search(query, flt, top_k=top_k, vector_fn=ctx.vector_search_fn)
    items = items_from_hits(tool, index, hits, miss_key=miss_key, expand=expand, label=label, label_flags_for=label_flags_for)
    return {"items": items, "known_ids": sorted(known_ids(items))}


def items_from_hits(tool: str, index: CorpusIndex, hits: list[Hit], *, miss_key: dict[str, Any], expand: bool = True, label: bool = False,
                    label_flags_for: Any = None) -> list[dict[str, Any]]:
    if not hits:
        return [miss_item(tool, miss_key)]
    items: list[dict[str, Any]] = []

    def flags(c: dict[str, Any]) -> list[str]:
        return list(label_flags_for(c)) if label_flags_for else []

    for h in hits:
        items.append(chunk_item(h.chunk, relation="hit", from_id=None, hit=h, label=label, flags=flags(h.chunk)))
    if expand:
        for ex in expand_chunks(index, [h.chunk for h in hits], max_total=max(0, MAX_ITEMS - len(items))):
            items.append(chunk_item(ex.chunk, relation=ex.relation, from_id=ex.from_id, hit=None, label=label and ex.chunk.get("layer") == "L3",
                                    flags=flags(ex.chunk)))
    return items[:MAX_ITEMS]
