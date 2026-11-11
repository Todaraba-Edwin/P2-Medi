"""AG-01 정상 경로 회귀(RFP-33-04)용 합성 재료: RFP-21 §4.8 골든 P1~P3의 **모양**을 본뜬 소사전 + 소규모 SQLite.

- 값은 RFP-21 §4.4~§4.6 표의 공개 예시(제품명·성분·등급·사유 문구)를 본떴을 뿐, 실제 파일·API·DB를 읽지 않는다(외부 호출 0).
- 평가 세트·시험셋 문항이 아니다(RFP-26-04). 골든 문항 ID 대신 `P1`·`P2`·`P3`(페르소나 번호)로 부른다.
- DUR API 병기는 `FakeDur`(가짜 `DurClient`)로만 한다. `by_ingredient`·`usjnt_pair_by_ingredient` 호출 기록을 남긴다.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.db import loaders
from app.tools.drug_dict import DrugDict
from app.tools.dur import SOURCE_INGR, DurResult, DurRow

# KIDS 성분코드(9자리, 합성). 콜드-에스는 병용금기 JSON에서 한 덩어리 코드(254000ATB)로 묶인다(RFP-21 §4.7)
APAP, COLD, PSE, RASA = "101300ATB", "254000ATB", "448001ATB", "625201ATB"
# DUR 성분코드(API)
D_APAP, D_PSE, D_DXM, D_RASA = "D000147", "D000448", "D000200", "D000698"
SEQ_T500, SEQ_COLD, SEQ_KID, SEQ_AZI = "202106092", "202106954", "202106100", "202200001"

FORM_MAP = {"ATB": {"route": "경구", "group": "정제", "confidence": "high"}, "ASY": {"route": "경구", "group": "액제", "confidence": "high"}}


def _ing(i: int, en: str, ko: str, kids: list[str], api: list[str]) -> dict[str, Any]:
    return {"id": i, "components": [{"en": en, "ko": ko, "display": ko, "raw": ko, "salt": ""}], "names": [en, ko], "display": ko,
            "kids_codes": kids, "api_codes": api, "sources": [], "set_key": en.lower()}


def _prod(seq: str, name: str, rx: str, *, kids: list[str], api: list[str], ids: list[int], form: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "item_seq": seq, "entp": "합성제약", "prescription": rx, "kids_product_codes": [], "edi_codes": [], "kids_codes": kids,
            "api_codes": api, "ingredient_ids": ids, "code_link": "edi_code", "code_scope": "product", "cancelled": False,
            "sources": [], "ingr_en": "", "ingr_keys": [], "product_type": "", "form": form or {"route": "경구", "form": "정", "group": "정제"}}


def golden_dict() -> DrugDict:
    ings = [
        _ing(0, "Acetaminophen", "아세트아미노펜", [APAP], [D_APAP]),
        _ing(1, "Pseudoephedrine", "슈도에페드린", [PSE], [D_PSE]),
        _ing(2, "Dextromethorphan", "덱스트로메토르판", [], [D_DXM]),
        _ing(3, "Chlorpheniramine", "클로르페니라민", [], []),
        _ing(4, "Rasagiline", "라사길린", [RASA], [D_RASA]),
    ]
    syr = {"route": "경구", "form": "현탁액", "group": "액제"}
    prods = [
        _prod(SEQ_T500, "타이레놀정500밀리그람", "일반", kids=[APAP], api=[D_APAP], ids=[0]),
        _prod(SEQ_COLD, "타이레놀콜드-에스정", "일반", kids=[COLD, PSE], api=[D_APAP, D_PSE, D_DXM], ids=[0, 1, 2, 3]),
        _prod(SEQ_KID, "어린이타이레놀현탁액", "일반", kids=[APAP], api=[D_APAP], ids=[0], form=syr),
        _prod(SEQ_AZI, "이지렉트정1.0밀리그램", "전문", kids=[RASA], api=[D_RASA], ids=[4]),
    ]
    meta = {"version": "golden-synth-v1", "built_at": "2026-11-11T00:00:00+00:00", "form_map": FORM_MAP}
    return DrugDict({"meta": meta, "products": prods, "ingredients": ings})


def golden_conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    loaders.apply_schema(c)
    contra = loaders.collect([{"id": "g1", "text": "", "metadata": {
        "성분명A": "acetaminophen+pseudoephedrine+dextromethorphan+chlorpheniramine", "성분코드A": COLD, "성분명B": "rasagiline mesylate",
        "성분코드B": RASA, "고시번호": "20250046", "고시적용일": "2025-07-14", "금기사유": "경련, 반사항진, 이상고열, 혼수 등", "비고": ""}}],
        loaders.normalize_contra_json, "contra_pair", "contra.json", loaders.AS_OF_KIDS)
    preg = loaders.collect([{"성분명": "Pseudoephedrine", "성분코드": PSE, "고시일자": "2020-06-30", "고시번호": "20200061", "금기등급": "2",
                             "상세정보": "임부에 대한 안전성 미확립."}], loaders.normalize_pregnancy, "pregnancy_contra", "preg.csv", loaders.AS_OF_KIDS)
    loaders.load_into(c, {"contra.json": contra, "preg.csv": preg})
    return c


class FakeDur:
    """가짜 `DurClient`(네트워크 0). 성분정보 임부금기 `D000448` 2등급 1건, 병용 `D000200`×`D000698` 1건, 나머지 0건."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    @staticmethod
    def _res(kind: str, rows: list[DurRow], query: dict[str, str]) -> DurResult:
        return DurResult(ok=True, kind=kind, level="ingr", rows=rows, total_count=len(rows), query=query,  # type: ignore[arg-type]
                         source_name=SOURCE_INGR, queried_at_utc="2026-11-11T00:00:00Z", queried_at_display="2026-11-11 09:00",
                         source="snapshot", request_hash="fake0000", request_hashes=["fake0000"])

    def by_ingredient(self, kind: str, code: str) -> DurResult:
        self.calls.append(("by_ingredient", kind, code))
        rows = []
        if kind == "pregnancy" and code == D_PSE:
            rows = [DurRow(kind="pregnancy", level="ingr", ingr_code=D_PSE, grade="2등급", grade_norm="2", content="임부에 대한 안전성 미확립.",
                           notification_date_raw="20200630", notification_date="2020-06-30")]
        return self._res(kind, rows, {"ingrCode": code})

    def usjnt_pair_by_ingredient(self, a: str, b: str) -> DurResult:
        self.calls.append(("usjnt_pair_by_ingredient", a, b))
        rows = []
        if {a, b} == {D_DXM, D_RASA}:
            rows = [DurRow(kind="usjnt", level="ingr", ingr_code=a, pair_ingr_code=b, content="경련, 반사항진, 이상고열, 혼수 등",
                           notification_date_raw="20171106", notification_date="2017-11-06")]
        return self._res("usjnt", rows, {"ingrCode": a})


# RFP-21 §4.8 골든 P1~P3(정상) 질문. 문장은 RFP-21 §4.4~§4.6 그대로(공개 예시, 시험셋 아님)
Q_P1 = "도윤이(만 2세)가 열이 나서 어린이 타이레놀 현탁액을 먹였는데 기침도 해요. 집에 있는 타이레놀 콜드-에스를 반 알 줘도 되나요?"
Q_P2 = "임신 14주인데 열이 나요. 집에 타이레놀정500이랑 콜드-에스가 있는데 먹어도 되나요?"
Q_P3 = "엄마가 이지렉트정을 드시는데 감기라서 타이레놀 콜드-에스를 사 왔어요. 같이 먹어도 되나요?"
