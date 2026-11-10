"""AG-02 계약 시험용 합성 재료(합성 사전 + 소규모 SQLite + 가짜 라벨 공급자). 외부 호출 없음."""

from __future__ import annotations

import sqlite3
from typing import Any

from app.agent.tools.context import ToolContext
from app.db import loaders
from app.tools.drug_dict import DrugDict

APAP, IBU, WAR, TTT, INJ = "100001ATB", "200001ATB", "300001ATB", "400001ATB", "500001BIJ"
FORM_MAP = {"ATB": {"route": "경구", "group": "정제", "confidence": "high"}, "BIJ": {"route": "주사", "group": "주사제", "confidence": "high"}}


def _ing(i: int, en: str, ko: str, kids: list[str], api: list[str]) -> dict[str, Any]:
    return {"id": i, "components": [{"en": en, "ko": ko, "display": ko, "raw": ko, "salt": ""}], "names": [en, ko], "display": ko,
            "kids_codes": kids, "api_codes": api, "sources": [], "set_key": en.lower()}


def _prod(seq: str, name: str, rx: str, *, kids: list[str] | None = None, api: list[str] | None = None, ids: list[int] | None = None,
          link: str = "none", keys: list[str] | None = None, form: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "item_seq": seq, "entp": "합성제약", "prescription": rx, "kids_product_codes": [], "edi_codes": [], "kids_codes": kids or [],
            "api_codes": api or [], "ingredient_ids": ids or [], "code_link": link, "code_scope": "product" if kids else None, "cancelled": False,
            "sources": [], "ingr_en": "", "ingr_keys": keys or [], "product_type": "", "form": form or {"route": "경구", "form": "정", "group": "정제"}}


def synth_dict() -> DrugDict:
    ings = [_ing(0, "Acetaminophen", "아세트아미노펜", [APAP], ["D000001"]), _ing(1, "Ibuprofen", "이부프로펜", [IBU], ["D000002"]),
            _ing(2, "Warfarin", "와파린", [WAR], ["D000003"]), _ing(3, "Zzzinj", "지지주사성분", [INJ], [])]
    cap = {"route": "경구", "form": "캡슐", "group": "캡슐"}
    prods = [
        _prod("100000001", "타이레놀정", "일반", kids=[APAP], api=["D000001"], ids=[0], link="edi_code"),
        _prod("100000002", "이부정", "일반", kids=[IBU], api=["D000002"], ids=[1], link="edi_code"),
        _prod("100000003", "와파린정", "전문", kids=[WAR], api=["D000003"], ids=[2], link="edi_code"),
        _prod("100000004", "에이캡슐", "일반", link="component_only", keys=["acetaminophen"], form=cap),       # route_only
        _prod("100000005", "파뚜정", "일반", link="component_only", keys=["acetaminophen"]),                   # match → 판정 가능
        _prod("100000006", "미네정", "일반", link="component_only", keys=["zzzinj"]),                          # mismatch(경구 ↔ 주사)
        _prod("100000007", "미등록정", "일반"),                                                                  # 코드 없음
        _prod("100000008", "전문정", "전문", kids=[TTT], ids=[], link="edi_code"),
        _prod("100000009", "이부프로펜", "일반", kids=[IBU], api=["D000002"], ids=[1], link="edi_code"),        # 제품·성분 동명
        _prod("100000010", "감기정", "일반", kids=[APAP], ids=[0], link="edi_code"),                           # 같은 이름 두 제품(코드 다름)
        _prod("100000011", "감기정", "일반", kids=[IBU], ids=[1], link="edi_code"),
    ] + [_prod(f"1000001{n:02d}", f"약초{n}정", "일반", kids=[APAP], ids=[0], link="edi_code") for n in range(7)]
    return DrugDict({"meta": {"version": "synth-v1", "built_at": "2026-11-10T00:00:00+00:00", "form_map": FORM_MAP}, "products": prods, "ingredients": ings})


def synth_conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    loaders.apply_schema(c)
    contra = loaders.collect([{"id": "c1", "text": "", "metadata": {
        "성분명A": "ibuprofen", "성분코드A": IBU, "성분명B": "warfarin", "성분코드B": WAR, "고시번호": "20200130", "고시적용일": "2020-12-28",
        "금기사유": "출혈 위험 증가 (합성 시험 문구)", "비고": ""}}], loaders.normalize_contra_json, "contra_pair", "x.json", loaders.AS_OF_KIDS)
    preg = loaders.collect([{"성분명": "warfarin", "성분코드": WAR, "고시일자": "2016-12-30", "고시번호": "20160155", "금기등급": "2",
                             "상세정보": "임부에 대한 안전성 미확립 (합성 시험 문구)."}], loaders.normalize_pregnancy, "pregnancy_contra", "p.csv", loaders.AS_OF_KIDS)
    age = loaders.collect([{"성분명": "acetaminophen", "성분코드": APAP, "특정연령": "12", "특정연령단위": "세 (3)", "연령처리조건": "미만 (1)",
                            "고시번호": "20070030", "고시일자": "2007-04-11", "상세정보": "12세 미만 안전성 미확립 (합성 시험 문구)"}],
                          loaders.normalize_age, "age_contra", "a.csv", loaders.AS_OF_KIDS)
    loaders.load_into(c, {"x.json": contra, "p.csv": preg, "a.csv": age})
    return c


class FakeLabels:
    """가짜 라벨 공급자. `eyak_map`·`detail_map`은 품목기준코드 → 공급 결과."""

    def __init__(self, eyak_map: dict[str, Any] | None = None, detail_map: dict[str, Any] | None = None, fail: bool = False) -> None:
        self.e, self.d, self.fail = eyak_map or {}, detail_map or {}, fail

    def eyak(self, seq: str):
        if self.fail:
            raise RuntimeError("boom secret-token")
        return self.e.get(seq)

    def prmsn_detail(self, seq: str):
        if self.fail:
            raise RuntimeError("boom")
        return self.d.get(seq)


def doc(title: str, *paras: str) -> str:
    body = "".join(f'<PARAGRAPH tagName="p"><![CDATA[{p}]]></PARAGRAPH>' for p in paras)
    return f'<DOC title="{title}"><SECTION title=""><ARTICLE title="">{body}</ARTICLE></SECTION></DOC>'


def ctx(**kw: Any) -> ToolContext:
    kw.setdefault("drug_dict", synth_dict())
    kw.setdefault("conn_factory", synth_conn)
    return ToolContext(**kw)
