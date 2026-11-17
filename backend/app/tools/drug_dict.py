"""BE-10 제품·성분 사전 조회(오프라인 1차).

사전 파일(JSON, `data/mock/dict/drug_dict.json`, 로컬 전용)은 `scripts/build_drug_dict.py`가 만든다.
이 모듈은 이름 정규화, 염 이름 줄이기(PRD-09-05), 조회(`lookup_name`), 문자 n-gram BM25만 맡는다.
네트워크·임베딩 호출은 없다. 임베딩은 `embed_fn` 주입점만 열어 두었고 이 모듈이 호출을 구현하지 않는다.

조회 계약(AG-02 `identify_drug`가 쓴다):
  - 정확 일치(원문) → 정규화 일치 → 접두 일치 → BM25 후보 순서.
  - 제품명 일치가 성분명 일치보다 우선한다(`matched_by`). 같은 이름이 여러 제품이면 임의로 고르지 않고 후보 목록을 돌려준다.
  - 사전에 없으면 `empty=True`, 후보 0개(AG-09 "약 미식별" 입력).
  - 판정은 하지 않는다. 성분코드는 KIDS 형식(`100501ATE`)과 API 형식(`D000147`)을 가능한 만큼 함께 돌려준다.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.tools import drug_form as DF

MATCHED_BY_PRODUCT = "product_name"
MATCHED_BY_INGREDIENT = "ingredient_name"
MATCHED_BY_COMPONENT = "ingredient_component"  # 제품에 든 성분 하나가 KIDS 단일 성분 코드와 맞음(제품 단위 판정 아님, BE-10-06 B)

# 후보의 코드 연결 상태(BE-10-06). `none`이면 조회 도구는 `NOT_LISTED`가 아니라 `UNIDENTIFIED`로 처리해야 한다.
# (상태 변환·화면 문구는 AG-02 몫이며 이 모듈은 상태 값만 돌려준다. 코드를 못 찾은 것은 "목록에 없음"이 아니라 "확인 못 함"이다.)
CODE_LINKED = "linked"  # 제품 단위(EDI·제품명·성분 집합 일치)로 KIDS 코드가 연결됨
CODE_COMPONENT_ONLY = "component_only"  # 집합 일치는 아니지만 성분 단위로는 KIDS 단일 성분 코드와 연결됨
CODE_NONE = "none"  # KIDS 코드 연결 없음 → UNIDENTIFIED(NOT_LISTED 금지)

MATCH_EXACT = "exact"  # 입력 원문이 사전 이름과 같음
MATCH_NORMALIZED = "normalized"  # 정규화 키가 같음
MATCH_PREFIX = "prefix"  # 정규화 키가 제품명의 앞부분과 같음(브랜드명만 입력)
MATCH_CONTAINS = "contains"  # 정규화 키가 제품명 중간에 들어 있음(3자 이상)
MATCH_COMPONENT = "component"  # 제품 성분 하나가 KIDS 단일 성분과 일치(성분 단위 보조 조회)
MATCH_BM25 = "bm25"  # 문자 n-gram BM25 후보(되묻기용, 자동 확정 금지)

DEFAULT_DICT_PATH = Path(__file__).resolve().parents[3] / "data" / "mock" / "dict" / "drug_dict.json"
SCHEMA_VERSION = 1
BM25_NGRAM_SIZES = (2,)  # 문자 2-gram 단독(BE-10-07 A, 3-gram 제거). 바꾸면 사전 버전 해시가 바뀌도록 빌더가 이 값을 쓴다
BM25_TOKENIZER = "char-ngram-" + "+".join(str(n) for n in BM25_NGRAM_SIZES)
BM25_MIN_NORM = 0.15  # 정규화 점수가 이보다 낮은 BM25 후보는 버린다(없는 이름은 빈 결과)
CONTAINS_MIN_LEN = 3

# --------------------------------------------------------------------------- 이름 정규화

_PAREN_EXPORT_RE = re.compile(r"\((?:수출명|수출용)[^)]*\)")
_EXPORT_NAME_RE = re.compile(r"수출용|수출명")  # 순위만 뒤로 보낸다(BE-10-13 A). 정규화 키는 `_PAREN_EXPORT_RE`가 따로 지운다
_KIDS_SUFFIX_RE = re.compile(r"_\([^)]*\)\s*$")  # KIDS 제품명 끝의 `_(0.25g/5mL)`
_PAREN_RE = re.compile(r"[(（\[][^)）\]]*[)）\]]")
_STRIP_RE = re.compile(r"[\s\-_·.,/:;'\"`~!@#$^&*+=|<>?{}\[\]()（）]+")
_UNIT_MAP = (("밀리그램", "mg"), ("밀리그람", "mg"), ("마이크로그램", "ug"), ("μg", "ug"), ("㎎", "mg"), ("그램", "g"), ("그람", "g"), ("밀리리터", "ml"))


def normalize_name(text: str, *, keep_paren: bool = True) -> str:
    """정규화 키: NFKC, 소문자, 수출명 괄호·KIDS 용량 꼬리 제거, 단위 통일, 공백·구두점 제거.

    `keep_paren=False`이면 남은 괄호(성분명 병기 등)도 내용째 지운다(제품명 기본형 키).
    """
    s = unicodedata.normalize("NFKC", text or "")
    s = _PAREN_EXPORT_RE.sub("", s)
    s = _KIDS_SUFFIX_RE.sub("", s)
    if not keep_paren:
        s = _PAREN_RE.sub("", s)
    s = s.lower()
    for a, b in _UNIT_MAP:
        s = s.replace(a, b)
    return _STRIP_RE.sub("", s)


# --------------------------------------------------------------------------- 염 이름 줄이기(PRD-09-05)

# 긴 것부터 먼저 비교한다. 끝에서 반복해서 떼므로 `염산염`이 `염산`·`염`보다 앞에 있어야 한다.
_KO_SALTS = (
    "브롬화수소산염일수화물", "염산염수화물", "염산염일수화물", "염산염이수화물", "염산염삼수화물", "황산염수화물", "나트륨삼수화물",
    "나트륨수화물", "나트륨일수화물", "나트륨이수화물", "칼슘수화물", "칼슘이수화물", "마그네슘이수화물", "마그네슘수화물",
    "브롬화수소산염", "염산염", "황산염", "질산염", "인산염", "초산염", "아세트산염", "말레산염", "말레인산염", "푸마르산염",
    "타르타르산염", "타르타르트산염", "구연산염", "시트르산염", "메실산염", "베실산염", "토실산염", "숙신산염", "석신산염",
    "젖산염", "락트산염", "옥살산염", "프로피온산염", "에스테르", "스트론튬사수화물", "스트론튬", "나트륨", "칼륨", "칼슘", "마그네슘",
    "수화물", "일수화물", "이수화물", "삼수화물", "사수화물", "무수물", "염산", "황산", "브롬화수소산",
)
_KO_SALTS = tuple(sorted(set(_KO_SALTS), key=len, reverse=True))
# 떼고 남은 앞부분이 이런 무기산·염기 이름뿐이면 물질 자체의 이름이라 떼지 않는다(탄산칼슘, 황산마그네슘 등).
_KO_BARE = {"탄산", "황산", "염산", "인산", "질산", "초산", "아세트산", "구연산", "젖산", "수산화", "산화", "염화", "브롬화", "요오드화", "규산", "붕산"}

_EN_SALT_WORDS = {
    "hydrochloride", "hcl", "sulfate", "sulphate", "maleate", "fumarate", "tartrate", "citrate", "mesylate", "besylate", "tosylate",
    "succinate", "phosphate", "acetate", "nitrate", "hydrobromide", "bromide", "sodium", "potassium", "calcium", "magnesium",
    "strontium", "dihydrate", "monohydrate", "trihydrate", "tetrahydrate", "hydrate", "anhydrous", "lactate", "oxalate", "dihydrochloride",
    "mesilate", "besilate",  # mesylate·besylate의 다른 철자(API는 mesilate도 쓴다)
}
_EN_BARE = {"calcium carbonate", "magnesium sulfate", "sodium sulfate", "potassium sulfate", "calcium sulfate", "calcium phosphate", "sodium phosphate",
            "potassium phosphate", "calcium acetate", "sodium acetate", "calcium citrate", "sodium citrate", "potassium citrate", "magnesium citrate"}
_AS_RE = re.compile(r"\(\s*as\s+([^)]+)\)", re.IGNORECASE)
_EN_STRENGTH_RE = re.compile(r"\s+[\d.,]+\s*(?:mg|g|ug|mcg|ml|i\.?u\.?|%|units?)(?![a-z]).*$", re.IGNORECASE)  # `ibuprofen 10g(20mg/mL)`의 함량 꼬리
_EN_PAREN_RE = re.compile(r"\s*\([^)]*\)")  # `acetaminophen(encapsulated)` 같은 가공 설명
# 원료 표기 꼬리: `X Montan Glycol Wax Mixture 40%`처럼 `Mixture nn%`와 그 앞의 담체(wax·lactose·starch 등, 수식어 2개 이내)를 뗀다.
# 담체 단어가 없으면 `Mixture nn%`만 뗀다(`Clonixin Lysinate Mixture 50%` → `Clonixin Lysinate`, 성분 이름은 건드리지 않는다).
_EN_MIXTURE_RE = re.compile(
    r"\s+(?:(?:\S+\s+){0,2}(?:wax|lactose|starch|mannitol|dextrin|cellulose)\s+)?mixture\s*[\d.,]+\s*%.*$", re.IGNORECASE)
_EN_LOCANT_RE = re.compile(r"(?<=[a-z])-\d+-(?=[a-z])", re.IGNORECASE)  # `isosorbide-5-mononitrate`의 위치 번호
_EN_EXT_RE = re.compile(r"\bext\b\.?", re.IGNORECASE)  # `ext.` → `extract`
_EN_SPECIES_RE = re.compile(r"\bbiloba\b\s*", re.IGNORECASE)  # `ginkgo biloba leaf` = `ginkgo leaf`(종소명 표기 차이)


def _en_tidy(text: str) -> str:
    """영문 원료 표기 차이를 줄인다(일반 규칙. 특정 제품명에 맞추지 않는다)."""
    t = _EN_MIXTURE_RE.sub("", text)
    t = _EN_LOCANT_RE.sub("-", t)
    t = _EN_EXT_RE.sub("extract", t)
    return " ".join(_EN_SPECIES_RE.sub("", t).split())


_API_SPLIT_RE = re.compile(r"[/;·]")  # 허가·e약은요 영문 성분 구분자(`/`·`;`·`·`)


def split_api_components(raw: str) -> list[str]:
    """허가정보 영문 성분 문자열을 성분 단위로 나눈다(`Streptokinase·Streptodornase` 포함)."""
    return [x.strip() for x in _API_SPLIT_RE.split(raw or "") if x.strip()]


def component_keys(raw: str, sep: str = "api", kids_split: Callable[[str], list[str]] | None = None) -> list[str]:
    """성분 문자열 → 정렬된 고유 성분 키 목록. `sep="kids"`면 `kids_split`(KIDS는 `+`·`,` 구분)으로 나눈다."""
    parts = (kids_split(raw) if sep == "kids" and kids_split else split_api_components(raw))
    return sorted({k for k in (ingredient_key(c) for c in parts) if k})


def normalize_rules_signature() -> str:
    """정규화 규칙(염 단어·정규식·구분자)의 해시. 규칙이 바뀌면 사전 버전이 바뀌게 빌더가 해시에 넣는다."""
    parts = [sorted(_EN_SALT_WORDS), sorted(_EN_BARE), sorted(_KO_SALTS), sorted(_KO_BARE),
             [r.pattern for r in (_EN_STRENGTH_RE, _EN_PAREN_RE, _EN_MIXTURE_RE, _EN_LOCANT_RE, _EN_EXT_RE, _EN_SPECIES_RE, _API_SPLIT_RE, _AS_RE, _STRIP_RE)]]
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def split_ko_salt(name: str) -> tuple[str, str]:
    """한글 성분명을 (줄인 이름, 뗀 염 이름)으로 나눈다. 뗄 것이 없으면 (원문, "").

    예: 슈도에페드린염산염 → (슈도에페드린, 염산염). 탄산칼슘·아세트아미노펜은 그대로 둔다.
    원문 염 이름은 호출자가 별도로 보존한다(원문 `raw`를 지우지 않는다).
    """
    base = unicodedata.normalize("NFKC", name or "").strip()
    removed = ""
    changed = True
    while changed:
        changed = False
        for salt in _KO_SALTS:
            if base.endswith(salt) and len(base) > len(salt) + 1:
                rest = base[: -len(salt)]
                if rest in _KO_BARE or rest.endswith(tuple(_KO_BARE)):
                    continue
                base, removed, changed = rest, salt + removed, True
                break
    return (base, removed) if removed else (name.strip(), "")


def split_en_salt(name: str) -> tuple[str, str]:
    """영문 성분명 줄이기. `(as xxx)`가 있으면 그 안 이름이 본체다. 끝 토큰의 염·수화물 단어를 뗀다."""
    text = _en_tidy(unicodedata.normalize("NFKC", name or "").strip())
    m = _AS_RE.search(text)
    if m:
        return m.group(1).strip().lower(), _AS_RE.sub("", text).strip().lower()
    low = _EN_STRENGTH_RE.sub("", _EN_PAREN_RE.sub("", " ".join(text.split()))).strip().lower()
    if low in _EN_BARE:
        return low, ""
    words = low.split()
    removed: list[str] = []
    while len(words) > 1 and words[-1] in _EN_SALT_WORDS and " ".join(words) not in _EN_BARE:
        removed.insert(0, words.pop())
    return " ".join(words), " ".join(removed)


def ingredient_key(name: str) -> str:
    """성분 이름의 비교 키(염 이름을 떼고 정규화). 한글·영문 모두 쓴다."""
    if re.search(r"[가-힣]", name):
        return normalize_name(split_ko_salt(name)[0])
    return normalize_name(split_en_salt(name)[0])


# --------------------------------------------------------------------------- BM25(문자 n-gram)

def char_ngrams(text: str, sizes: Sequence[int] = BM25_NGRAM_SIZES) -> list[str]:
    """정규화 키의 문자 n-gram. 길이가 n보다 짧으면 키 전체를 하나의 토큰으로 쓴다."""
    out: list[str] = []
    for n in sizes:
        if len(text) < n:
            continue
        out.extend(text[i : i + n] for i in range(len(text) - n + 1))
    if not out and text:
        out.append(text)
    return out


class BM25:
    """외부 라이브러리 없는 BM25 Okapi(문서는 토큰 리스트). 역색인으로 질의 토큰이 든 문서만 채점한다."""

    def __init__(self, docs: Iterable[Sequence[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self._postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self._len: list[int] = []
        for i, toks in enumerate(docs):
            counts: dict[str, int] = defaultdict(int)
            for t in toks:
                counts[t] += 1
            for t, c in counts.items():
                self._postings[t].append((i, c))
            self._len.append(len(toks))
        self.n = len(self._len)
        self._avg = (sum(self._len) / self.n) if self.n else 0.0
        self._idf = {t: math.log(1 + (self.n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self._postings.items()}

    def upper_bound(self, query_tokens: Sequence[str]) -> float:
        """질의 토큰이 한 문서에 전부·충분히 들어 있을 때의 상한(점수 정규화용)."""
        return sum(self._idf.get(t, 0.0) * (self.k1 + 1) for t in set(query_tokens)) or 1.0

    def scores(self, query_tokens: Sequence[str]) -> dict[int, float]:
        acc: dict[int, float] = defaultdict(float)
        for t in set(query_tokens):
            idf = self._idf.get(t)
            if idf is None:
                continue
            for i, tf in self._postings[t]:
                norm = 1 - self.b + self.b * self._len[i] / (self._avg or 1.0)
                acc[i] += idf * tf * (self.k1 + 1) / (tf + self.k1 * norm)
        return acc


# --------------------------------------------------------------------------- 반환 계약

@dataclass(frozen=True)
class IngredientRef:
    """성분 하나. `display`는 염 이름을 줄인 표시명, `raw`·`salt`는 원문 보존(PRD-09-05)."""

    name_en: str
    name_ko: str | None
    display: str
    raw: str
    salt: str


@dataclass(frozen=True)
class ComponentMatch:
    """제품에 든 성분 하나가 맞은 KIDS 단일 성분 항목. `kids_codes`는 그 성분의 모든 제형 코드(성분 단위, 제품 단위 아님)."""

    component: str  # 제품 쪽 성분 비교 키(염 이름을 뗀 정규화 키)
    ingredient_id: int
    display: str
    kids_codes: tuple[str, ...] = ()
    api_codes: tuple[str, ...] = ()
    name_en: str = ""  # 표시명이 한글명 투표 오류일 때(예: 소아용)를 대비해 영문 성분명을 함께 둔다
    # BE-10-08 A: 제품 제형과 KIDS 코드 제형(접미, 측정 추정)의 비교. `match`일 때만 판정에 쓴다(`usable_codes`).
    form_match: str = DF.FM_UNKNOWN  # match | route_only | mismatch | unknown
    product_form: str = "?"  # 제품 제형 이름(예: 경구/정제). 모르면 `?`
    code_form: str = "?"  # 가장 강하게 맞은 코드들의 제형 이름(여럿이면 `·`로 잇는다)
    usable_codes: tuple[str, ...] = ()  # 제형이 맞아(match) 판정에 쓸 수 있는 코드. match가 아니면 비어 있다

    @property
    def usable_for_judgment(self) -> bool:
        return self.form_match in DF.USABLE

    @property
    def label(self) -> str:
        return f"{self.display}({self.name_en})" if self.name_en and self.name_en != self.display else self.display


COMPONENT_NOTE = "이 제품에 든 {names} 성분이 목록에 있음. 제품 단위 판정 아님(성분 단위 연결)"


def form_note(matches: Sequence[ComponentMatch]) -> str | None:
    """제형이 맞지 않는 성분 단위 일치에 붙일 참고 문구. 전부 `match`이면 None."""
    notes = []
    for m in matches:
        if m.form_match == DF.FM_MISMATCH:
            notes.append(DF.NOTE_MISMATCH.format(forms=m.code_form))
        elif m.form_match == DF.FM_ROUTE_ONLY:
            notes.append(DF.NOTE_ROUTE_ONLY.format(forms=m.code_form))
        elif m.form_match == DF.FM_UNKNOWN:
            notes.append(DF.NOTE_UNKNOWN)
    return " / ".join(dict.fromkeys(notes)) or None


def _with_form_note(note: str, matches: Sequence[ComponentMatch]) -> str:
    extra = form_note(matches)
    return f"{note}. {extra}" if extra else note


@dataclass(frozen=True)
class Candidate:
    matched_by: str  # product_name | ingredient_name
    name: str
    score: float  # 일치 종류별 고정 점수(exact 1.0 등) 또는 BM25 정규화 점수(0~1)
    match_type: str
    item_seq: str | None = None
    entp_name: str | None = None
    prescription: str | None = None  # 전문 | 일반 | None
    ingredients: tuple[IngredientRef, ...] = ()
    kids_codes: tuple[str, ...] = ()
    api_codes: tuple[str, ...] = ()
    code_link: str = "none"  # edi_code | product_name | ingredient_name | kids_source | component_only | none
    code_scope: str | None = None  # product(그 제품의 코드) | all_forms(성분의 모든 제형 코드를 모음)
    cancelled: bool = False
    sources: tuple[str, ...] = ()
    # linked | component_only | none. none이면 조회 도구는 NOT_LISTED를 돌려주지 않고 UNIDENTIFIED로 처리한다(AG-02가 변환).
    code_status: str = CODE_NONE
    component_matches: tuple[ComponentMatch, ...] = ()  # component_only일 때 어느 성분이 어느 KIDS 코드와 맞았는지
    note: str | None = None  # 성분 단위 표시 노트(제품 단위 판정 아님)
    # BE-10-08 A·BE-10-12 A: 성분 단위(component_only)·성분 이름 연결(all_forms) 제품 후보의 제형 비교. 제품 코드 연결·성분명 입력 후보는 이 검사를 받지 않아 기본값(판정 가능)이다.
    form_match: str | None = None  # 위 후보만 match | route_only | mismatch | unknown
    usable_for_judgment: bool = True  # False면 금기 판정에 쓰지 않고 참고로만 보인다(mismatch·route_only·unknown)
    usable_kids_codes: tuple[str, ...] = ()  # 성분 단위 후보에서 제형이 맞아 판정에 쓸 코드(`kids_codes`는 모든 제형 코드, 참고용)


@dataclass(frozen=True)
class LookupResult:
    query: str
    normalized_query: str
    matched_by: str | None  # 1순위 후보의 일치 단위. 빈 결과면 None
    match_type: str | None
    resolved: bool  # True면 후보가 하나로 정해졌다. False면 되묻기(후보 목록)나 빈 결과
    needs_clarification: bool
    empty: bool
    candidates: tuple[Candidate, ...] = ()
    total_candidates: int = 0
    dict_version: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        """JSON 직렬화용 dict(튜플은 리스트로)."""
        return json.loads(json.dumps(asdict(self), ensure_ascii=False))


EmbedFn = Callable[[list[str]], list[list[float]]]


# --------------------------------------------------------------------------- 사전

class DrugDict:
    """메모리에 올린 제품·성분 사전. `from_dict`(합성 시험)나 `load`(파일)로 만든다."""

    def __init__(self, data: dict[str, Any], embed_fn: EmbedFn | None = None) -> None:
        self.meta: dict[str, Any] = data.get("meta", {})
        self.form_map: dict[str, dict[str, Any]] = self.meta.get("form_map", {})  # 코드 접미 → 제형(측정 추정, drug_form.infer_code_forms)
        self.products: list[dict[str, Any]] = data["products"]
        self.ingredients: list[dict[str, Any]] = data["ingredients"]
        self.embed_fn = embed_fn  # 주입점만. 이 모듈은 호출하지 않는다(BE-10 임베딩 시험은 별도 지시서).
        self._vectors: list[list[float]] | None = None

        self._by_raw: dict[str, list[int]] = defaultdict(list)
        self._by_key: dict[str, list[int]] = defaultdict(list)
        self._by_base: dict[str, list[int]] = defaultdict(list)
        self._base_keys: list[tuple[str, int]] = []
        for i, p in enumerate(self.products):
            self._by_raw[p["name"].strip()].append(i)
            full = normalize_name(p["name"])
            base = normalize_name(p["name"], keep_paren=False)
            self._by_key[full].append(i)
            if base:
                self._by_base[base].append(i)
                self._base_keys.append((base, i))
        self._by_seq: dict[str, int] = {p["item_seq"]: i for i, p in enumerate(self.products) if p.get("item_seq")}
        # KIDS 단일 성분 항목(성분 집합 키 = 성분 하나의 키). 성분 단위 보조 조회가 쓴다.
        self._single_by_key: dict[str, int] = {
            ing["set_key"]: j for j, ing in enumerate(self.ingredients) if len(ing.get("components", [])) == 1 and ing.get("set_key")
        }
        self._ing_by_key: dict[str, list[int]] = defaultdict(list)
        for j, ing in enumerate(self.ingredients):
            for nm in ing["names"]:
                k = normalize_name(nm)
                sk = ingredient_key(nm)
                for key in {k, sk}:
                    if key and j not in self._ing_by_key[key]:
                        self._ing_by_key[key].append(j)

        # BM25 문서: 제품 이름(기본형 키 + 전체 키) 먼저, 성분 이름 뒤. 문서 번호로 (종류, 인덱스)를 되찾는다.
        self._docs: list[tuple[str, int]] = []
        toks: list[list[str]] = []
        for i, p in enumerate(self.products):
            self._docs.append(("p", i))
            toks.append(char_ngrams(normalize_name(p["name"])))
        for j, ing in enumerate(self.ingredients):
            self._docs.append(("i", j))
            toks.append(char_ngrams(" ".join(normalize_name(n) for n in ing["names"])))
        self._bm25 = BM25(toks)

    # -- 생성·적재
    @classmethod
    def load(cls, path: str | Path = DEFAULT_DICT_PATH, embed_fn: EmbedFn | None = None) -> DrugDict:
        """파일에서 만든다(개발·평가용. 평가 러너는 이 경로를 쓴다)."""
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f), embed_fn=embed_fn)

    @classmethod
    def from_db(cls, conn_factory: Callable[[], Any], *, paramstyle: str = "format", version: str | None = None,
                embed_fn: EmbedFn | None = None) -> DrugDict:
        """DB 사전 테이블(`drug_dict_meta`·`drug_dict_entry`, BE-06-24 B)에서 만든다. 서비스 경로 기본.

        연결은 `conn_factory()`로 한 번 열고 읽은 뒤 닫는다(읽기 전용 SELECT만). `version`이 없으면 가장 늦게 적재한 판.
        판이 없거나 불완전하면 `app.db.drug_dict_store`의 예외로 올린다(빈 사전으로 대신하지 않는다). 파일은 읽지 않는다.
        """
        from app.db.drug_dict_store import read_payload  # noqa: PLC0415 - 파일 경로만 쓰는 개발·평가는 DB 모듈을 불러오지 않는다

        conn = conn_factory()
        try:
            payload = read_payload(conn, paramstyle=paramstyle, version=version)
        finally:
            conn.close()
        return cls(payload, embed_fn=embed_fn)

    @property
    def version(self) -> str:
        return str(self.meta.get("version", ""))

    # -- 후보 만들기
    def _ingredient_refs(self, ids: Iterable[int]) -> tuple[IngredientRef, ...]:
        refs = []
        for j in ids:
            c = self.ingredients[j]["components"]
            refs.extend(IngredientRef(x["en"], x.get("ko"), x["display"], x["raw"], x.get("salt", "")) for x in c)
        return tuple(refs)

    def _component_matches(self, i: int) -> tuple[ComponentMatch, ...]:
        """제품의 각 성분 키를 KIDS 단일 성분 항목과 대조한다(정확 일치만. 비슷한 이름으로 넓히지 않는다).

        각 일치에 제품 제형과 코드 제형을 비교한 `form_match`를 붙인다(BE-10-08 A).
        """
        pform = self.products[i].get("form") or {}
        out = []
        for k in self.products[i].get("ingr_keys", []):
            j = self._single_by_key.get(k)
            if j is not None:
                ing = self.ingredients[j]
                codes = tuple(ing.get("kids_codes", []))
                per = {c: DF.compare_forms(pform, DF.code_form(c, self.form_map)) for c in codes}
                best = DF.best_match(per.values())
                top = [c for c, r in per.items() if r == best]
                code_label = ", ".join(dict.fromkeys(DF.label(DF.code_form(c, self.form_map)) for c in top)) if top else "?"
                out.append(ComponentMatch(k, j, ing["display"], codes, tuple(ing.get("api_codes", [])), ing["components"][0].get("en", ""),
                                          form_match=best, product_form=DF.label(pform), code_form=code_label,
                                          usable_codes=tuple(top) if best in DF.USABLE else ()))
        return tuple(out)

    def _code_status(self, p: dict[str, Any]) -> str:
        if p.get("kids_codes"):
            return CODE_LINKED
        return CODE_COMPONENT_ONLY if p.get("code_link") == CODE_COMPONENT_ONLY else CODE_NONE

    def component_candidates(self, item_seq: str) -> tuple[Candidate, ...]:
        """성분 단위 보조 조회(BE-10-06 B). 제품에 든 성분마다 KIDS 단일 성분 코드와 맞은 후보를 돌려준다.

        제품 단위(EDI·제품명·성분 집합) 연결이 없을 때 쓴다. 후보는 `matched_by="ingredient_component"`이고
        "이 제품에 든 ○○ 성분이 목록에 있음, 제품 단위 판정 아님" 노트를 단다. 맞는 성분이 없으면 빈 튜플이다.
        빈 튜플은 "금기 없음"이 아니다(`NOT_LISTED` 금지, 조회 도구는 `UNIDENTIFIED`로 처리, 변환은 AG-02).
        """
        i = self._by_seq.get(item_seq)
        if i is None:
            return ()
        p = self.products[i]
        cands = []
        for m in self._component_matches(i):
            cands.append(Candidate(
                matched_by=MATCHED_BY_COMPONENT, name=m.display, score=0.95, match_type=MATCH_COMPONENT, item_seq=p.get("item_seq"),
                entp_name=p.get("entp"), prescription=p.get("prescription"), ingredients=self._ingredient_refs([m.ingredient_id]),
                kids_codes=m.kids_codes, api_codes=m.api_codes, code_link=CODE_COMPONENT_ONLY, code_scope="all_forms",
                cancelled=bool(p.get("cancelled", False)), sources=tuple(self.ingredients[m.ingredient_id].get("sources", [])),
                code_status=CODE_COMPONENT_ONLY, component_matches=(m,), note=_with_form_note(COMPONENT_NOTE.format(names=m.label), (m,)),
                form_match=m.form_match, usable_for_judgment=m.usable_for_judgment, usable_kids_codes=m.usable_codes))
        return tuple(cands)

    def _all_forms_form(self, p: dict[str, Any]) -> tuple[str | None, tuple[str, ...], str | None]:
        """성분 이름으로 이은(`ingredient_name`·`all_forms`) 제품의 코드에 제형 비교를 적용한다(BE-10-12 A).

        모든 제형 코드를 붙여 둔 연결이라 제품 제형과 맞는 코드(`match`)만 판정에 쓴다. 제품 코드 연결(edi_code·product_name 등)은 대상이 아니다.
        반환: (form_match 또는 None, 판정에 쓸 코드, 참고 노트).
        """
        if p.get("code_link") != "ingredient_name" or not p.get("kids_codes"):
            return None, (), None
        pform = p.get("form") or {}
        per = {c: DF.compare_forms(pform, DF.code_form(c, self.form_map)) for c in p["kids_codes"]}
        best = DF.best_match(per.values())
        usable = tuple(c for c, r in per.items() if r in DF.USABLE)
        if best in DF.USABLE:
            return best, usable, None
        top = [c for c, r in per.items() if r == best]
        labels = ", ".join(dict.fromkeys(DF.label(DF.code_form(c, self.form_map)) for c in top)) or "?"
        note = {DF.FM_MISMATCH: DF.NOTE_MISMATCH.format(forms=labels), DF.FM_ROUTE_ONLY: DF.NOTE_ROUTE_ONLY.format(forms=labels)}.get(best, DF.NOTE_UNKNOWN)
        return best, usable, note

    def _product_candidate(self, i: int, score: float, match_type: str, folded: Sequence[int] = ()) -> Candidate:
        p = self._merged_product(i, folded) if folded else self.products[i]
        status = self._code_status(p)
        cm = self._component_matches(i) if status == CODE_COMPONENT_ONLY else ()
        af_match, af_usable, af_note = self._all_forms_form(p) if status == CODE_LINKED else (None, (), None)
        return Candidate(
            matched_by=MATCHED_BY_PRODUCT,
            name=p["name"],
            score=round(score, 4),
            match_type=match_type,
            item_seq=p.get("item_seq"),
            entp_name=p.get("entp"),
            prescription=p.get("prescription"),
            ingredients=self._ingredient_refs(p.get("ingredient_ids", [])),
            kids_codes=tuple(p.get("kids_codes", [])),
            api_codes=tuple(p.get("api_codes", [])),
            code_link=p.get("code_link", "none"),
            code_scope=p.get("code_scope"),
            cancelled=bool(p.get("cancelled", False)),
            sources=tuple(p.get("sources", [])),
            code_status=status,
            component_matches=cm,
            note=_with_form_note(COMPONENT_NOTE.format(names=", ".join(m.label for m in cm)), cm) if cm else af_note,
            form_match=DF.best_match(m.form_match for m in cm) if cm else af_match,
            usable_for_judgment=any(m.usable_for_judgment for m in cm) if cm else (af_match in DF.USABLE if af_match else True),  # 성분별 판정 가능 여부는 component_matches·usable_kids_codes
            usable_kids_codes=tuple(c for m in cm for c in m.usable_codes) if cm else af_usable,
        )

    def _ingredient_candidate(self, j: int, score: float, match_type: str) -> Candidate:
        ing = self.ingredients[j]
        return Candidate(
            matched_by=MATCHED_BY_INGREDIENT,
            name=ing["display"],
            score=round(score, 4),
            match_type=match_type,
            ingredients=self._ingredient_refs([j]),
            kids_codes=tuple(ing.get("kids_codes", [])),
            api_codes=tuple(ing.get("api_codes", [])),
            code_link="ingredient_name",
            code_scope="all_forms",
            sources=tuple(ing.get("sources", [])),
            code_status=CODE_LINKED,
        )

    def _rank_products(self, ids: list[int]) -> list[int]:
        # 판매 중인 제품, (수출용·수출명 이름은 뒤로: 내수 행이 앞, BE-10-13 A), 이름이 짧은(기본형에 가까운) 제품, item_seq 순. 결정적 순서를 위해 마지막에 인덱스.
        return sorted(ids, key=lambda i: (bool(self.products[i].get("cancelled")), bool(_EXPORT_NAME_RE.search(self.products[i]["name"])),
                                          len(self.products[i]["name"]), self.products[i].get("item_seq") or "", i))

    # -- KIDS 함량 행 접기(BE-10-13 A)
    def _is_kids_strength_row(self, i: int) -> bool:
        """`이름_(함량)` 꼬리만 다른 KIDS 행인가: 허가번호가 없고 이름 끝이 `_(…)` 형식이다."""
        p = self.products[i]
        return not p.get("item_seq") and bool(_KIDS_SUFFIX_RE.search(p["name"]))

    def _permit_rep(self, i: int) -> int | None:
        """KIDS 함량 행 `i`가 접힐 허가 행의 인덱스. 같은 정규화 키의 허가번호 행이 사전 전체에서 **정확히 1개**일 때만 돌려준다.

        2개 이상(별도 허가번호 쌍둥이, `(수출용)` 포함)이면 자동 확정하지 않고 None(되묻기 유지). 이름 안의 함량은 정규화 키에 그대로
        들어 있어 함량이 다른 제품은 키가 달라 접히지 않는다. 구조(꼬리 형식·item_seq 유무·정규화 키)만 쓰고 제품명을 보지 않는다.
        """
        permits = [j for j in self._by_key.get(normalize_name(self.products[i]["name"]), ()) if self.products[j].get("item_seq")]
        return permits[0] if len(permits) == 1 else None

    def _fold_kids_rows(self, ranked: list[int]) -> list[tuple[int, list[int]]]:
        """순위가 매겨진 제품 인덱스에서 KIDS 함량 행을 대표(허가) 행으로 접는다. [(대표 인덱스, 접힌 인덱스들)]을 순서대로 돌려준다.

        대표 행이 후보 집합에 없어도(KIDS 행 이름을 그대로 입력) 같은 키의 허가 행이 하나뿐이면 그 행이 대표가 된다. 대표가 없으면 접지 않는다.
        """
        out: list[tuple[int, list[int]]] = []
        pos: dict[int, int] = {}
        for i in ranked:
            rep = self._permit_rep(i) if self._is_kids_strength_row(i) else None
            if rep is None:
                rep, merged = i, False
            else:
                merged = True
            if rep in pos:
                if merged:
                    out[pos[rep]][1].append(i)
                continue
            pos[rep] = len(out)
            out.append((rep, [i] if merged else []))
        # 같은 허가 행이 어떤 입력 경로(원문 정확·정규화·접두)로 나와도 합친 코드가 같도록, 후보 집합에 없던 같은 키의 KIDS 행도 모은다.
        for rep, folded in out:
            if self.products[rep].get("item_seq") and self._sole_permit(rep):
                folded.extend(j for j in self._by_key.get(normalize_name(self.products[rep]["name"]), ()) if self._is_kids_strength_row(j) and j not in folded)
        return out

    def _sole_permit(self, rep: int) -> bool:
        permits = [j for j in self._by_key.get(normalize_name(self.products[rep]["name"]), ()) if self.products[j].get("item_seq")]
        return permits == [rep]

    def _merged_product(self, i: int, folded: Sequence[int]) -> dict[str, Any]:
        """대표 행 `i`에 접힌 KIDS 행의 코드·성분·출처를 합집합으로 합친 사본(원본 사전은 바꾸지 않는다). 대표 행의 이름·허가번호·제형은 유지한다."""
        p = dict(self.products[i])
        rows = [self.products[j] for j in folded]
        for key in ("kids_codes", "api_codes", "kids_product_codes", "edi_codes", "ingredient_ids", "ingr_keys", "sources"):
            vals = [*(p.get(key) or []), *(v for r in rows for v in (r.get(key) or []))]
            if vals:
                p[key] = list(dict.fromkeys(vals))
        if not self.products[i].get("kids_codes"):  # 대표 행에 코드 연결이 없으면 접힌 KIDS 행의 연결을 이어받는다
            donor = next((r for r in rows if r.get("kids_codes")), None)
            if donor is not None:
                p["code_link"], p["code_scope"] = donor.get("code_link", "none"), donor.get("code_scope")
        if not p.get("form"):
            p["form"] = next((r["form"] for r in rows if r.get("form")), p.get("form"))
        return p

    # -- 조회
    def lookup_name(self, query: str, top_k: int = 5) -> LookupResult:
        q = (query or "").strip()
        nq = normalize_name(q)
        base_q = normalize_name(q, keep_paren=False)
        ver = self.version

        def done(cands: list[Candidate], mtype: str, total: int, *, resolved: bool, notes: Sequence[str] = ()) -> LookupResult:
            shown = tuple(cands[: max(top_k, 1)])
            return LookupResult(
                query=query, normalized_query=nq, matched_by=shown[0].matched_by if shown else None, match_type=mtype if shown else None,
                resolved=resolved and len(shown) == 1, needs_clarification=bool(shown) and not (resolved and total == 1),
                empty=not shown, candidates=shown, total_candidates=total, dict_version=ver, notes=tuple(notes),
            )

        if not nq:
            return done([], "", 0, resolved=False, notes=("빈 질의",))

        # 1) 제품명: 원문 정확 → 정규화 → 기본형(괄호 제거) 정확
        for stage, ids, mtype in (
            ("raw", self._by_raw.get(q, []), MATCH_EXACT),
            ("key", self._by_key.get(nq, []), MATCH_NORMALIZED),
            ("base", self._by_base.get(base_q, []) if base_q else [], MATCH_NORMALIZED),
        ):
            if ids:
                ranked = self._rank_products(list(dict.fromkeys(ids)))
                groups = self._fold_kids_rows(ranked)
                cands = [self._product_candidate(i, 1.0 if stage == "raw" else 0.98, mtype, folded) for i, folded in groups]
                notes = []
                n_folded = sum(len(f) for _, f in groups)
                if n_folded:
                    notes.append(f"KIDS 함량 행 {n_folded}개를 같은 이름의 허가 제품에 합쳤다(코드는 합집합)")
                distinct = {self.products[i].get("item_seq") or f"p{i}" for i, _ in groups}
                if len(distinct) > 1:
                    notes.append("같은 이름의 제품이 여러 개라 후보 목록을 돌려준다(임의 선택 금지)")
                # 제품 일치가 우선이나, 같은 이름이 성분 이름이기도 하면 알려 준다(성분 후보는 뒤에 붙인다).
                ing_ids = self._ing_by_key.get(nq, [])
                if ing_ids:
                    notes.append("같은 이름이 성분명이기도 하다(제품 일치 우선)")
                return done(cands, mtype, len(cands), resolved=len(distinct) == 1, notes=notes)

        # 2) 성분명(영문·한글·별칭·염 이름 줄인 이름) 정확
        ing_ids = list(dict.fromkeys(self._ing_by_key.get(nq, []) + self._ing_by_key.get(ingredient_key(q), [])))
        if ing_ids:
            ing_ids.sort(key=lambda j: (-len(self.ingredients[j].get("kids_codes", [])), j))
            cands = [self._ingredient_candidate(j, 0.97, MATCH_NORMALIZED) for j in ing_ids]
            notes = ["성분 단위 일치라 제품 정보(제품 연령 문장·허가 라벨·제형)는 없다(H17)"]
            if len(cands) > 1:
                notes.append("같은 이름이 여러 성분(염 형태 등)에 걸린다")
            return done(cands, MATCH_NORMALIZED, len(cands), resolved=len(cands) == 1, notes=notes)

        # 3) 브랜드명만 입력: 기본형 키의 접두 일치(2자 이상)
        if len(base_q) >= 2:
            ids = [i for k, i in self._base_keys if k.startswith(base_q)]
            if ids:
                ranked = self._rank_products(ids)
                cands = [self._product_candidate(i, 0.9, MATCH_PREFIX) for i in ranked]
                return done(cands, MATCH_PREFIX, len(cands), resolved=False, notes=("이름 앞부분만 일치하는 제품 후보(되묻기)",))

        # 4) 이름 중간에 든 경우(예: 콜드-에스 → 코푸콜드-에스액)
        if len(base_q) >= CONTAINS_MIN_LEN:
            ids = [i for k, i in self._base_keys if base_q in k]
            if ids:
                ranked = self._rank_products(ids)
                cands = [self._product_candidate(i, 0.8, MATCH_CONTAINS) for i in ranked]
                return done(cands, MATCH_CONTAINS, len(cands), resolved=False, notes=("이름 중간이 일치하는 제품 후보(되묻기)",))

        # 5) 문자 n-gram BM25 후보(되묻기용, 오탈자 대응)
        qt = char_ngrams(nq)
        scores = self._bm25.scores(qt)
        ub = self._bm25.upper_bound(qt)
        order = sorted(((d, s) for d, s in scores.items() if s / ub >= BM25_MIN_NORM), key=lambda kv: (-kv[1], kv[0]))
        out: list[Candidate] = []
        for d, s in order[: max(top_k, 1)]:
            kind, idx = self._docs[d]
            norm = min(s / ub, 1.0)
            out.append(self._product_candidate(idx, norm, MATCH_BM25) if kind == "p" else self._ingredient_candidate(idx, norm, MATCH_BM25))
        return done(out, MATCH_BM25, len(out), resolved=False, notes=("n-gram BM25 후보. 자동 확정하지 않고 되묻는다",))

    # -- 임베딩 주입점(호출 구현 없음)
    def attach_vectors(self, vectors: list[list[float]]) -> None:
        """`embed_fn`으로 미리 만든 문서 벡터(문서 순서 = 제품 뒤 성분)를 붙인다. 하이브리드 시험(별도 지시서)용 자리."""
        if len(vectors) != len(self._docs):
            raise ValueError("벡터 수가 문서 수와 다르다")
        self._vectors = vectors

    def doc_texts(self) -> list[str]:
        """임베딩 입력 문서 목록(제품 이름들, 성분 이름들). `embed_fn`에 넘길 값."""
        texts = [p["name"] for p in self.products]
        texts += [" / ".join(i["names"][:6]) for i in self.ingredients]
        return texts
