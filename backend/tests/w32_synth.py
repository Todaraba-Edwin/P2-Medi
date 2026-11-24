"""W3-2 서버 개선 후보(AG-13-41·42·44·45·46) 시험·보조 문항 공용 합성 재료(외부 호출 0). 평가 세트·시험셋 문항이 아니다.

`e2e/golden_synth.py`의 소사전(타이레놀정500·타이레놀콜드-에스정·어린이타이레놀·이지렉트정)에 FE-17 U-26 사례(ISSUE-033)의 모양을 더한다:
- `코푸콜드-에스액`(B, 판정 코드 없음 = 선택해도 "확인하지 못함"이 정답인 약), `제감콜드에스캡슐`(D, 이름이 비슷한 비선택 후보),
- 시간 낱말이 든 이름 보호 시험용: `8시간이알서방정`(실제 사전에 같은 부류 26건), `열두시간서방정`(접두 일치)·`네시간뒤`(정확 일치)(합성: 정규식에 걸리는 토큰이 사전 이름과 맞는 경우).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "e2e"))

from golden_synth import (  # noqa: E402
    APAP,
    D_APAP,
    FORM_MAP,
    SEQ_COLD,
    SEQ_T500,
    FakeDur,
    _prod,
    golden_conn,
    golden_dict,
)

from app.tools.drug_dict import DrugDict  # noqa: E402

SEQ_A = SEQ_T500            # 타이레놀정500밀리그람(선택 약 A)
SEQ_B = "201900975"         # 코푸콜드-에스액(선택 약 B, 판정 코드 없음)
SEQ_C = SEQ_COLD            # 타이레놀콜드-에스정(비선택 후보, 판정 가능)
SEQ_D = "202400548"         # 제감콜드에스캡슐(비선택 후보)
SEQ_E = "202300111"         # 8시간이알서방정(시간 낱말이 든 실제 형태의 제품명)
SEQ_F = "202300222"         # 열두시간서방정(합성: 정규식에 걸리는 토큰 "열두시간"이 사전 이름과 접두로 맞는 경우)
SEQ_H = "202300444"         # 브이12주(숫자·"12"가 든 실제 제품 이름의 모양: 시각 조각이 BM25 유사 일치로 오탈자 의심·되묻기가 되는 원인, rca H2)
SEQ_G = "202300333"         # 네시간뒤(합성: 정규식에 걸리는 토큰과 사전 이름이 정확히 같은 경우)

# FE-17 U-26(ISSUE-033) 질문과 같은 모양(제품 이름은 사전에 있는 합성 이름)
Q_U26 = "임신 중인데 열이 나요. 집에 타이레놀정500이랑 콜드-에스가 있는데 먹어도 되나요?"
Q_REDOSE = "나 이미 오전 9시에 타이레놀정500밀리그람 2알을 먹었는데 {when}먹어도 되니?"
CONFIRMED_AB = [{"item_seq": SEQ_A, "input_name": "타이레놀정500"}, {"item_seq": SEQ_B, "input_name": "콜드-에스"}]


def w32_dict(*, protect_names: bool = True) -> DrugDict:
    """`protect_names=False`면 정규식에 걸리는 이름의 합성 제품(`열두시간서방정`·`네시간뒤`)을 뺀다(개발 보조 문항 시험은 그 보호가 필요 없다)."""
    base = golden_dict()
    liquid = {"route": "경구", "form": "액", "group": "액", "src": "ambiguous_liquid"}
    products = [
        *base.products,
        {**_prod(SEQ_B, "코푸콜드-에스액", "일반", kids=[], api=[], ids=[], form=liquid), "code_link": "component_only", "code_scope": "component"},
        _prod(SEQ_D, "제감콜드에스캡슐", "일반", kids=[APAP], api=[D_APAP], ids=[0], form={"route": "경구", "form": "캡슐", "group": "캡슐"}),
        _prod(SEQ_E, "8시간이알서방정", "일반", kids=[APAP], api=[D_APAP], ids=[0]),
        *([_prod(SEQ_F, "열두시간서방정", "일반", kids=[APAP], api=[D_APAP], ids=[0]),
           _prod(SEQ_G, "네시간뒤", "일반", kids=[APAP], api=[D_APAP], ids=[0])] if protect_names else []),
        _prod(SEQ_H, "브이12주", "전문", kids=[APAP], api=[D_APAP], ids=[0]),
    ]
    meta = {"version": "w32-synth-v1", "built_at": "2026-11-24T00:00:00+00:00", "form_map": FORM_MAP}
    return DrugDict({"meta": meta, "products": products, "ingredients": base.ingredients})


__all__ = ["FakeDur", "golden_conn", "w32_dict", "SEQ_A", "SEQ_B", "SEQ_C", "SEQ_D", "SEQ_E", "SEQ_F", "SEQ_G", "SEQ_H", "Q_U26", "Q_REDOSE", "CONFIRMED_AB"]
