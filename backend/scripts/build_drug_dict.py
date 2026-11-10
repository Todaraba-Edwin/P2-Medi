"""BE-10 제품·성분 사전 빌더(오프라인 1차). 외부 API·임베딩 호출 없음, 로컬 파일만 읽는다.

재료(모두 `data/` 로컬):
  - KIDS 병용금기 JSON(`data/병용금기_데이터.json`, 스트리밍): 제품코드·제품명·성분코드(KIDS형식)·성분명 A/B
  - KIDS 임부·연령·수유부 CSV: 제품코드·제품명·성분코드. 용량주의 CSV는 복합제가 1성분만 표시되어 코드 신뢰가 안 돼 쓰지 않는다
  - 수집 스냅샷 `data/mock/api_snapshots/`: eyak-all(e약은요), prmsn-names(허가정보 전체 목록), prmsn-detail(상세 212개),
    dur-ingr(`D######` 성분코드·한글/영문 성분명), ingr_codes.json
  - DUR 품목리스트 CSV(심평원)는 쓰지 않는다(PRD-14-02).
연결 규칙(RFP-21-02 A, 일치율을 재며 확정): KIDS 제품코드=허가 EDI_CODE → 제품명 정규화 일치 → 영문 성분(집합) 이름 일치 → e약은요 괄호 성분명.
사전은 제품·성분명 튜닝을 하지 않는다. 평가 세트(`evaluation/eval_set`)를 읽지 않는다(RFP-26-04).

사용: `cd backend && .venv/bin/python scripts/build_drug_dict.py [--out ../data/mock/dict] [--limit-kids N]`
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.loaders import iter_csv, iter_json_array
from app.tools.drug_dict import (
    SCHEMA_VERSION,
    DrugDict,
    ingredient_key,
    normalize_name,
    split_en_salt,
    split_ko_salt,
)

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SNAP = DATA / "mock" / "api_snapshots"

SRC_KIDS_JSON = "KIDS 병용금기(한국의약품안전관리원)"
SRC_KIDS_CSV = "KIDS 금기·주의 CSV(한국의약품안전관리원)"
SRC_PRMSN = "허가정보(식약처)"
SRC_EYAK = "e약은요(식약처)"
SRC_DUR = "DUR 성분정보(식약처)"
BUILDER_REV = 3 # 빌드 규칙을 바꾸면 올린다(버전 문자열에 들어간다)

# 별칭 목록(흔한 줄임말·이명). 키는 영문 성분 키(`ingredient_key`)이고, (한글 표시명, 별칭들)을 붙인다.
# 평가 세트 문항에서 가져오지 않았다. 일반에 알려진 성분 이명만 둔다.
CURATED_ALIASES: dict[str, tuple[str | None, tuple[str, ...]]] = {
    "acetaminophen": ("아세트아미노펜", ("파라세타몰", "paracetamol", "apap")),
    "ibuprofen": ("이부프로펜", ("이브프로펜", "ibuprofen")),
    "aspirin": ("아스피린", ("아세틸살리실산", "acetylsalicylic acid", "asa")),
    "acetylsalicylic acid": ("아스피린", ("아세틸살리실산", "aspirin", "asa")),
    "naproxen": ("나프록센", ()),
    "diclofenac": ("디클로페낙", ()),
    "pseudoephedrine": ("슈도에페드린", ()),
    "chlorpheniramine": ("클로르페니라민", ("클로페니라민", "클로르페니라민말레산염")),
    "loratadine": ("로라타딘", ()),
    "cetirizine": ("세티리진", ()),
    "dextromethorphan": ("덱스트로메토르판", ("덱스트로메토르판브롬화수소산염",)),
    "guaifenesin": ("구아이페네신", ("구아이페닌",)),
    "warfarin": ("와파린", ("와르파린",)),
    "methotrexate": ("메토트렉세이트", ("메토트렉세이트", "mtx")),
    "metformin": ("메트포르민", ()),
    "simvastatin": ("심바스타틴", ()),
}

_KO_ONLY = re.compile(r"^[가-힣]{2,}$")
_FORM_SUFFIX = ("정", "캅셀", "캡슐", "주", "액", "시럽", "크림", "겔", "패취", "연고", "산", "환", "과립", "필름", "현탁액", "주사", "내복액", "점안", "스프레이")
_PAREN_NAME_RE = re.compile(r"\(([^()_]+)\)")


# --------------------------------------------------------------------------- 재료 읽기

def _split_components(raw: str) -> list[str]:
    """KIDS 영문 성분명을 성분 단위로 나눈다(`+`, 괄호 밖 `,`). `(as x)`는 한 성분에 붙은 채로 둔다."""
    parts: list[str] = []
    depth, cur = 0, []
    for ch in raw:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        if depth == 0 and ch in "+,":
            parts.append("".join(cur).strip())
            cur = []
            continue
        cur.append(ch)
    parts.append("".join(cur).strip())
    return [p for p in parts if p]


def kids_json_records(path: Path, limit: int | None = None) -> Iterator[dict[str, str]]:
    seen: set[str] = set()
    for obj in iter_json_array(path, limit=limit):
        m = obj.get("metadata", {})
        for s in "AB":
            code = (m.get(f"제품코드{s}") or "").strip()
            if not code or code in seen:
                continue
            seen.add(code)
            yield {"product_code": code, "name": m.get(f"제품명{s}", ""), "ingr_code": m.get(f"성분코드{s}", ""),
                   "ingr_name": m.get(f"성분명{s}", ""), "entp": m.get(f"업소명{s}", "")}


def kids_csv_records(data_dir: Path) -> Iterator[dict[str, str]]:
    for fn in ("한국의약품안전관리원_임부금기약물_20260721.csv", "한국의약품안전관리원_연령금기_20260721.csv", "한국의약품안전관리원_수유부주의_20251127.csv"):
        p = data_dir / fn
        if not p.exists():
            continue
        for r in iter_csv(p):
            code = (r.get("제품코드") or "").strip()
            if code:
                yield {"product_code": code, "name": r.get("제품명", ""), "ingr_code": r.get("성분코드") or r.get("주성분코드") or "",
                       "ingr_name": r.get("성분명", ""), "entp": r.get("업체명", "")}


def _read_pages(directory: Path) -> Iterator[dict[str, Any]]:
    for f in sorted(directory.glob("page-*.json"), key=lambda x: int(x.stem.split("-")[1])):
        yield from json.loads(f.read_text(encoding="utf-8")).get("items", [])


def snapshot_sets(snap: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"eyak": [], "prmsn": [], "detail": [], "dur_ingr": [], "ingr_codes": {}}
    if (snap / "eyak-all").exists():
        out["eyak"] = list(_read_pages(snap / "eyak-all"))
    if (snap / "prmsn-names").exists():
        out["prmsn"] = list(_read_pages(snap / "prmsn-names"))
    if (snap / "prmsn-detail").exists():
        for f in sorted((snap / "prmsn-detail").glob("item-*.json")):
            resp = json.loads(f.read_text(encoding="utf-8")).get("response") or []
            if resp:
                out["detail"].append(resp[0])
    for f in sorted((snap / "dur-ingr").glob("*/*.json")) if (snap / "dur-ingr").exists() else []:
        body = json.loads(f.read_text(encoding="utf-8")).get("body", {})
        for it in body.get("items", []) or []:
            item = it.get("item", it)
            if item.get("INGR_CODE"):
                out["dur_ingr"].append(item)
    if (snap / "ingr_codes.json").exists():
        out["ingr_codes"] = json.loads((snap / "ingr_codes.json").read_text(encoding="utf-8"))
    return out


def _file_hash(paths: Iterable[Path]) -> str:
    h = hashlib.sha256()
    for p in paths:
        h.update(p.name.encode())
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def material_hashes(data_dir: Path, snap: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    kj = data_dir / "병용금기_데이터.json"
    if kj.exists():
        out["kids_contra_json"] = _file_hash([kj])
    for fn in ("한국의약품안전관리원_임부금기약물_20260721.csv", "한국의약품안전관리원_연령금기_20260721.csv",
               "한국의약품안전관리원_수유부주의_20251127.csv"):
        if (data_dir / fn).exists():
            out[fn] = _file_hash([data_dir / fn])
    for d in ("eyak-all", "prmsn-names", "prmsn-detail"):
        if (snap / d).exists():
            out[f"snapshot:{d}"] = _file_hash(sorted((snap / d).glob("*.json")))
    if (snap / "dur-ingr").exists():
        out["snapshot:dur-ingr"] = _file_hash(sorted((snap / "dur-ingr").glob("*/*.json")))
    return out


# --------------------------------------------------------------------------- 사전 조립

def _ko_candidates(product_name: str) -> list[str]:
    """제품명 괄호 안의 한글 성분명 후보(용량 꼬리 `_(…)`·형태 단어 제외)."""
    base = re.sub(r"_\([^)]*\)\s*$", "", product_name)
    out = []
    for m in _PAREN_NAME_RE.finditer(base):
        t = m.group(1).strip()
        if _KO_ONLY.match(t) and not t.endswith(_FORM_SUFFIX) and not t.startswith(("수출", "주")):
            out.append(t)
    return out


def _set_key(raw_en: str, sep: str) -> str:
    comps = [ingredient_key(c) for c in (_split_components(raw_en) if sep == "kids" else [x for x in re.split(r"[/;]", raw_en) if x.strip()])]
    return "+".join(sorted({c for c in comps if c}))


def build_dictionary(
    kids: Iterable[dict[str, str]],
    kids_csv: Iterable[dict[str, str]],
    snaps: dict[str, Any],
    hashes: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """재료 → (사전 dict, 통계 dict). 입출력은 모두 메모리 구조라 합성 입력으로 시험할 수 있다."""
    # 1) 성분 레지스트리: KIDS 코드 앞 6자리 = 성분(복합제는 조합 단위). 뒤 3자리는 제형.
    kids_all = list(kids) + [dict(r, _csv=True) for r in kids_csv]
    # 성분 = 영문 성분 집합 키(염 이름 제외, 복합제는 조합 단위). 코드 앞 6자리는 함량 규격까지 갈라서 쓰지 않는다.
    reg: dict[str, dict[str, Any]] = {}
    code_key: dict[str, str] = {}
    ko_votes: dict[str, Counter[str]] = defaultdict(Counter)
    for r in kids_all:
        code = r["ingr_code"].strip()
        if len(code) != 9 or not r["ingr_name"].strip():
            continue
        key = _set_key(r["ingr_name"], "kids")
        e = reg.setdefault(key, {"key": key, "en_raw": Counter(), "codes": set(), "sources": set()})
        e["codes"].add(code)
        code_key.setdefault(code, key)
        e["en_raw"][r["ingr_name"].strip()] += 1
        e["sources"].add(SRC_KIDS_CSV if r.get("_csv") else SRC_KIDS_JSON)
        if len(_split_components(r["ingr_name"])) == 1:  # 한글 성분명 투표(단일 성분 제품의 괄호명)
            for k in _ko_candidates(r["name"]):
                ko_votes[key][k] += 1

    keys = sorted(reg)
    ing_id = {k: i for i, k in enumerate(keys)}
    ingredients: list[dict[str, Any]] = []
    for k in keys:
        e = reg[k]
        en_raw = e["en_raw"].most_common(1)[0][0]
        comps = []
        for c in _split_components(en_raw):
            body, salt = split_en_salt(c)
            comps.append({"en": body, "ko": None, "display": body, "raw": c, "salt": salt, "key": ingredient_key(c)})
        ingredients.append({"id": ing_id[k], "components": comps, "names": [], "display": "", "kids_codes": sorted(e["codes"]),
                            "api_codes": [], "sources": sorted(e["sources"]), "en_raws": sorted(e["en_raw"]), "set_key": k})

    # 한글명: 단일 성분은 투표 1위(+별칭), 사전 표시는 염 이름을 줄인다.
    ko_by_key: dict[str, str] = {}
    for ing in ingredients:
        if len(ing["components"]) == 1 and ko_votes.get(ing["set_key"]):
            top = ko_votes[ing["set_key"]].most_common(1)[0][0]
            ko_by_key.setdefault(ing["components"][0]["key"], top)
    for key, (ko, _aliases) in CURATED_ALIASES.items():
        if ko:
            ko_by_key[key] = ko  # 큐레이션이 투표보다 우선(표시명 통일)

    # API D 코드(한글·영문 성분명) → 단일 성분 키
    api_by_key: dict[str, set[str]] = defaultdict(set)
    api_ko_by_key: dict[str, str] = {}
    code_ko = snaps.get("ingr_codes", {})
    for it in snaps.get("dur_ingr", []):
        d = it["INGR_CODE"]
        if it.get("MIX_TYPE", "단일") == "복합" and it.get("MIX_INGR"):
            continue
        k_en = ingredient_key(it.get("INGR_ENG_NAME") or "")
        k_ko = it.get("INGR_NAME") or code_ko.get(d, "")
        if k_en:
            api_by_key[k_en].add(d)
            if k_ko:
                api_ko_by_key.setdefault(k_en, k_ko)
        if k_ko:
            ko_to_en = normalize_name(split_ko_salt(k_ko)[0])
            api_by_key[f"ko:{ko_to_en}"].add(d)
    for d, k_ko in code_ko.items():
        api_by_key[f"ko:{normalize_name(split_ko_salt(k_ko)[0])}"].add(d)
    for k, k_ko in api_ko_by_key.items():
        ko_by_key.setdefault(k, k_ko)

    # 성분 표시명·별칭·API 코드 확정
    ko_aliases: dict[str, set[str]] = defaultdict(set)
    for key, (_ko, aliases) in CURATED_ALIASES.items():
        ko_aliases[key].update(aliases)
    for k, votes in ko_votes.items():
        ing = ingredients[ing_id[k]]
        if len(ing["components"]) == 1:
            ko_aliases[ing["components"][0]["key"]].update(k for k, c in votes.items() if c >= 1)
    for ing in ingredients:
        for c in ing["components"]:
            ko = ko_by_key.get(c["key"])
            if ko:
                c["ko"], c["display"] = split_ko_salt(ko)[0], split_ko_salt(ko)[0]
                if c["salt"] == "":
                    c["salt"] = split_ko_salt(ko)[1]
                c["raw"] = ko if ko != c["display"] else c["raw"]
        ing["display"] = " + ".join(c["display"] for c in ing["components"])
        names = set(ing["en_raws"]) | {ing["display"]}
        if len(ing["components"]) == 1:  # 복합제는 성분 하나의 이름을 별칭으로 갖지 않는다(조합 단위 코드)
            names.add(ing["components"][0]["en"])
            k = ing["components"][0]["key"]
            for ko in ({ko_by_key[k]} if k in ko_by_key else set()) | ko_aliases.get(k, set()):
                names.add(ko)
                names.add(split_ko_salt(ko)[0])
            ing["api_codes"] = sorted(api_by_key.get(k, set()) | api_by_key.get(f"ko:{normalize_name(ing['display'])}", set()))
        ing["names"] = sorted(n for n in names if n)
    ing_by_set: dict[str, list[int]] = defaultdict(list)
    for ing in ingredients:
        ing_by_set[ing["set_key"]].append(ing["id"])
    ing_by_ko: dict[str, list[int]] = defaultdict(list)
    for ing in ingredients:
        if len(ing["components"]) == 1:
            for n in ing["names"]:
                if re.search(r"[가-힣]", n):
                    k = normalize_name(split_ko_salt(n)[0])
                    if ing["id"] not in ing_by_ko[k]:
                        ing_by_ko[k].append(ing["id"])

    # 2) 제품: item_seq 기준으로 허가정보·e약은요·상세를 합친다.
    products: dict[str, dict[str, Any]] = {}

    def prod(seq: str, name: str) -> dict[str, Any]:
        return products.setdefault(seq, {"name": name, "item_seq": seq, "entp": None, "prescription": None, "kids_product_codes": [], "edi_codes": [],
                                         "kids_codes": [], "api_codes": [], "ingredient_ids": [], "code_link": "none", "code_scope": None,
                                         "cancelled": False, "sources": [], "ingr_en": None, "ingr_ko_main": None})

    def label(v: str | None) -> str | None:
        return "전문" if v and "전문" in v else ("일반" if v and "일반" in v else None)

    for it in snaps.get("prmsn", []):
        p = prod(it["item_seq"], it["item_name"])
        p.update(entp=it.get("entp_name"), prescription=label(it.get("spclty_pblc")), ingr_en=it.get("item_ingr_name"),
                 cancelled=(it.get("cancel_name") not in (None, "", "정상")))
        p["edi_codes"] = sorted({c.strip() for c in (it.get("edi_code") or "").split(",") if c.strip()})
        p["sources"].append(SRC_PRMSN)
    for it in snaps.get("eyak", []):
        p = prod(it["item_seq"], it["item_name"])
        p["entp"] = p["entp"] or it.get("entp_name")
        if SRC_EYAK not in p["sources"]:
            p["sources"].append(SRC_EYAK)
    for d in snaps.get("detail", []):
        p = prod(d["ITEM_SEQ"], d["ITEM_NAME"])
        p["prescription"] = p["prescription"] or label(d.get("ETC_OTC_CODE"))
        p["ingr_en"] = p["ingr_en"] or d.get("MAIN_INGR_ENG")
        p["ingr_ko_main"] = re.sub(r"\[[^\]]*\]", "", d.get("MAIN_ITEM_INGR") or "") or None
        if d.get("EDI_CODE"):
            p["edi_codes"] = sorted(set(p["edi_codes"]) | {c.strip() for c in d["EDI_CODE"].split(",") if c.strip()})
        if SRC_PRMSN not in p["sources"]:
            p["sources"].append(SRC_PRMSN)

    # KIDS 제품: 제품코드로 허가 EDI와 잇고, 못 이으면 KIDS 단독 제품으로 둔다.
    edi_to_seq: dict[str, list[str]] = defaultdict(list)
    for seq, p in products.items():
        for c in p["edi_codes"]:
            edi_to_seq[c].append(seq)
    kids_by_code: dict[str, dict[str, str]] = {}
    for r in kids_all:
        kids_by_code.setdefault(r["product_code"], r)
    kids_by_base: dict[str, set[str]] = defaultdict(set)  # 제품명 정규화 → 성분코드 집합
    for r in kids_by_code.values():
        k = normalize_name(r["name"], keep_paren=False)
        if k and len(r["ingr_code"]) == 9:
            kids_by_base[k].add(r["ingr_code"])

    def add_codes(p: dict[str, Any], codes: Iterable[str], link: str, scope: str) -> None:
        p["kids_codes"] = sorted(set(p["kids_codes"]) | set(codes))
        p["ingredient_ids"] = sorted({ing_id[code_key[c]] for c in p["kids_codes"] if c in code_key})
        p["code_link"], p["code_scope"] = link, scope

    linked_kids: set[str] = set()
    for code, r in kids_by_code.items():
        seqs = edi_to_seq.get(code, [])
        for seq in seqs:
            p = products[seq]
            p["kids_product_codes"] = sorted(set(p["kids_product_codes"]) | {code})
            if len(r["ingr_code"]) == 9:
                add_codes(p, [r["ingr_code"]], "edi_code", "product")
            src = SRC_KIDS_CSV if r.get("_csv") else SRC_KIDS_JSON
            if src not in p["sources"]:
                p["sources"].append(src)
            linked_kids.add(code)
    for code, r in kids_by_code.items():
        if code in linked_kids:
            continue
        p = prod(f"kids:{code}", r["name"])
        p["item_seq"] = None
        p["entp"] = r.get("entp") or None
        p["kids_product_codes"] = [code]
        p["sources"].append(SRC_KIDS_CSV if r.get("_csv") else SRC_KIDS_JSON)
        p["ingr_en"] = r["ingr_name"]
        if len(r["ingr_code"]) == 9:
            add_codes(p, [r["ingr_code"]], "kids_source", "product")

    # 이름·성분으로 잇는 단계(아직 코드가 없는 제품만)
    for p in products.values():
        if p["kids_codes"]:
            continue
        codes = kids_by_base.get(normalize_name(p["name"], keep_paren=False))
        if codes:
            add_codes(p, codes, "product_name", "product")
            continue
        if p["ingr_en"]:
            sk = _set_key(p["ingr_en"], "api")
            ids = ing_by_set.get(sk)
            if ids:
                allc = sorted({c for i in ids for c in ingredients[i]["kids_codes"]})
                add_codes(p, allc, "ingredient_name", "all_forms")
                continue
        for ko in ([p["ingr_ko_main"]] if p["ingr_ko_main"] else []) + _ko_candidates(p["name"]):
            ids = ing_by_ko.get(normalize_name(split_ko_salt(ko)[0]))
            if ids:
                allc = sorted({c for i in ids for c in ingredients[i]["kids_codes"]})
                add_codes(p, allc, "ingredient_name", "all_forms")
                break

    out_products = []
    for p in products.values():
        p["api_codes"] = sorted({d for i in p["ingredient_ids"] for d in ingredients[i]["api_codes"]})
        out_products.append({k: v for k, v in p.items() if k not in ("ingr_ko_main",)})
    out_products.sort(key=lambda x: (x["item_seq"] or "~" + (x["kids_product_codes"][0] if x["kids_product_codes"] else ""), x["name"]))
    out_ingredients = [{k: v for k, v in i.items() if k != "en_raws"} for i in ingredients]
    for i in out_ingredients:  # 새 인덱스 기준 id 유지(리스트 위치 = id)
        i["components"] = [{k: v for k, v in c.items() if k != "key"} for c in i["components"]]

    stats = compute_stats(out_products, out_ingredients)
    blob = json.dumps({"rev": BUILDER_REV, **(hashes or {})}, sort_keys=True)
    version = f"be10-dict-s{SCHEMA_VERSION}-{hashlib.sha256(blob.encode()).hexdigest()[:12]}"
    data = {"meta": {"schema": SCHEMA_VERSION, "version": version, "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
                     "material_sha256": hashes or {}, "counts": stats["counts"],
                     "materials": {SRC_KIDS_JSON: "한국의약품안전관리원", SRC_KIDS_CSV: "한국의약품안전관리원", SRC_PRMSN: "식약처", SRC_EYAK: "식약처",
                                   SRC_DUR: "식약처", "DUR 품목리스트 CSV(심평원)": "쓰지 않음(PRD-14-02)"}},
            "products": out_products, "ingredients": out_ingredients}
    return data, stats


def compute_stats(products: list[dict[str, Any]], ingredients: list[dict[str, Any]]) -> dict[str, Any]:
    names_raw = {p["name"] for p in products}
    names_base = {normalize_name(p["name"], keep_paren=False) for p in products}
    kids_codes = {c for i in ingredients for c in i["kids_codes"]}
    by_src: dict[str, dict[str, int]] = defaultdict(lambda: {"n": 0, "with_code": 0, "exact_code": 0, "has_ingredient_info": 0})
    link = Counter()
    for p in products:
        link[p["code_link"]] += 1
        for s in p["sources"]:
            b = by_src[s]
            b["n"] += 1
            b["with_code"] += bool(p["kids_codes"])
            b["exact_code"] += p["code_scope"] == "product"
            b["has_ingredient_info"] += bool(p.get("ingr_en") or p["kids_codes"])
    return {
        "counts": {"products": len(products), "unique_product_names_raw": len(names_raw), "unique_product_names_normalized": len(names_base),
                   "ingredients": len(ingredients), "kids_ingredient_codes_9": len(kids_codes), 
                   "api_codes_D": len({d for i in ingredients for d in i["api_codes"]}),
                   "ingredients_with_ko_name": sum(1 for i in ingredients if all(c["ko"] for c in i["components"]))},
        "link_by_method": dict(link),
        "link_by_source": {s: {**v, "rate_with_code": round(v["with_code"] / v["n"], 4) if v["n"] else 0.0,
                                  "rate_among_has_ingredient_info": round(v["with_code"] / v["has_ingredient_info"], 4) if v["has_ingredient_info"] else 0.0} for s, v in by_src.items()},
    }


# --------------------------------------------------------------------------- 점검(보고용)

SAMPLE_OTC = ["타이레놀", "어린이타이레놀", "타이레놀정500밀리그람", "콜드-에스", "이지렉트", "판콜에이", "게보린", "부루펜", "어린이부루펜시럽",
              "판피린", "베아제", "훼스탈", "신신파스", "지르텍", "아스피린", "이부프로펜", "아세트아미노펜"]


def sample_check(dd: DrugDict, names: Iterable[str] = SAMPLE_OTC) -> list[dict[str, Any]]:
    rows = []
    for n in names:
        r = dd.lookup_name(n, top_k=3)
        top = r.candidates[0] if r.candidates else None
        rows.append({"query": n, "empty": r.empty, "match_type": r.match_type, "matched_by": r.matched_by, "resolved": r.resolved,
                     "total": r.total_candidates, "top": top.name if top else None,
                     "kids_source": bool(top and any("KIDS" in s for s in top.sources)), "has_kids_code": bool(top and top.kids_codes),
                     "code_link": top.code_link if top else None})
    return rows


def classify_unmatched(dd: DrugDict, names: Iterable[str]) -> dict[str, Any]:
    """미매칭 이름을 사전 조회 결과로 분류한다(조회만 한다. 사전은 이 결과에 맞춰 고치지 않는다).

    분류 기준은 보기 전에 고정했다: 정확·정규화 제품 일치 = "사전에 있음", 성분 일치 = "성분명", 접두 일치 = "브랜드명(접두)",
    BM25 1순위와 문자열 유사도(difflib) 0.75 이상 = "오탈자 후보", 그 밖의 BM25 후보 있음 = "기타(유사 후보 약함)", 후보 없음 = "사전에 없음(가상 약 후보)".
    """
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for n in names:
        r = dd.lookup_name(n, top_k=3)
        top = r.candidates[0] if r.candidates else None
        if r.empty:
            cat = "사전에 없음(가상 약 후보)"
        elif r.match_type in ("exact", "normalized") and r.matched_by == "product_name":
            cat = "사전에 있음(제품명 일치)"
        elif r.matched_by == "ingredient_name" and r.match_type in ("exact", "normalized"):
            cat = "성분명"
        elif r.match_type == "prefix":
            cat = "브랜드명(접두 후보)"
        else:
            sim = SequenceMatcher(None, normalize_name(n, keep_paren=False), normalize_name(top.name, keep_paren=False)).ratio() if top else 0.0
            cat = "오탈자 후보" if sim >= 0.75 else "기타(유사 후보 약함)"
        buckets[cat].append({"query": n, "top": top.name if top else None, "match_type": r.match_type, "score": top.score if top else None,
                             "total": r.total_candidates})
    return {"counts": {k: len(v) for k, v in buckets.items()}, "rows": buckets}


# --------------------------------------------------------------------------- 실행

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="BE-10 제품·성분 사전 빌더(오프라인)")
    ap.add_argument("--out", default=str(DATA / "mock" / "dict"))
    ap.add_argument("--limit-kids", type=int, default=None, help="병용금기 JSON 앞부분만 읽기(시험용)")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    snaps = snapshot_sets(SNAP)
    hashes = material_hashes(DATA, SNAP)
    kids = list(kids_json_records(DATA / "병용금기_데이터.json", args.limit_kids))
    data, stats = build_dictionary(kids, list(kids_csv_records(DATA)), snaps, hashes)
    (out / "drug_dict.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    dd = DrugDict(data)
    manifest = json.loads((SNAP / "prmsn-detail" / "manifest.json").read_text(encoding="utf-8")) if (SNAP / "prmsn-detail" / "manifest.json").exists() else {}
    report = {"version": data["meta"]["version"], "stats": stats, "sample_otc": sample_check(dd), "unmatched": classify_unmatched(dd, manifest.get("unmatched", []))}
    (out / "build_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"version": report["version"], **stats}, ensure_ascii=False, indent=1))
    print("unmatched:", json.dumps(report["unmatched"]["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
