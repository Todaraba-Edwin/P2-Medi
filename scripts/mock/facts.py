"""mock 생성에 쓰는 '사실(facts)'을 data/ 파일과 API 샘플에서 코드로 가져온다(RFP-31 §4: LLM은 값을 만들지 않는다).

- 임부금기·연령금기·병용금기: data/ CSV(CP949, 병용금기는 87만 줄이라 스트리밍).
- e약은요 라벨 문장: data/api_samples/eyak__*.json에서 원문 부분 문자열을 찾아 확인(없으면 예외).
  샘플에 없는 제품(어린이타이레놀현탁액 등)은 RFP-21 §4.3~4.4의 2026-11-01 API 확인값을 '출처 표시'와 함께 쓴다.
- 결과는 mock/_facts.json에 캐시한다(로컬 전용).
"""
import csv, glob, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CACHE = ROOT / "mock" / "_facts.json"

F_PREG = DATA / "한국의약품안전관리원_임부금기약물_20260721.csv"
F_AGE = DATA / "한국의약품안전관리원_연령금기_20260721.csv"
F_COMBO = DATA / "의약품안전사용서비스(DUR)_병용금기 품목리스트 2026.6.csv"
ASOF = "2026-07-21"  # 임부금기·연령금기 자료 기준일(CLAUDE.md 4장)
MOCK_RETRIEVED_AT = "2026-11-05T09:00:00+09:00"  # API 조회 시각(mock 고정값)
SRC_ORG = "한국의약품안전관리원"


def rows(path, enc="cp949"):
    with open(path, encoding=enc, newline="") as f:
        yield from csv.DictReader(f)


def _eyak():
    out = {}
    for p in glob.glob(str(DATA / "api_samples" / "eyak__*.json")):
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        items = (d.get("body") or {}).get("items") or []
        if isinstance(items, dict):
            items = items.get("item", [])
        for x in items:
            out.setdefault(x["itemSeq"], x)
    return out


def _pick(text, needle):
    """라벨 원문에서 needle(원문 그대로의 부분 문자열)을 찾아 그대로 돌려준다. 없으면 예외."""
    if needle not in text:
        raise ValueError(f"라벨 원문에 없음: {needle}")
    return needle


def _seg(text, needle):
    """needle이 든 문장 전체(마침표 뒤 공백 2칸 이상으로 끊은 한 문장)를 원문 그대로 돌려준다. 없으면 예외."""
    for seg in re.split(r"(?<=[.])\s{2,}", text):
        if needle in seg:
            return seg.strip()
    raise ValueError(f"라벨 원문에 없음: {needle}")


def build():
    eyak = _eyak()
    # ---- 임부금기 ----
    preg = {}
    for r in rows(F_PREG):
        n = r["제품명"]
        for key in ("타이레놀콜드-에스정", "이지렉트정1.0밀리그램", "에소메졸캡슐40밀리그램", "로바스크정", "심바로드정20", "타리에스비정10", "미프론정4mg"):
            if n.startswith(key):
                preg.setdefault(key, dict(제품코드=r["제품코드"], 제품명=n, 성분명=r["성분명"], 성분코드=r["성분코드"], 업체명=r["업체명"],
                                          고시일자=r["고시일자"], 고시번호=r["고시번호"], 금기등급=r["금기등급"], 상세정보=r["상세정보"]))
    # ---- 연령금기 ----
    age = {}
    for r in rows(F_AGE):
        n = r["제품명"]
        for key in ("타이레놀8시간이알서방정", "타이레놀산500밀리그램"):
            if n.startswith(key):
                age.setdefault(key, dict(제품코드=r["제품코드"], 제품명=n, 성분코드=r["성분코드"], 특정연령=r["특정연령"], 단위=r["특정연령단위"],
                                         조건=r["연령처리조건"], 고시번호=r["고시번호"], 고시일자=r["고시일자"], 상세정보=r["상세정보"]))
    has_age = {"에소메졸": False}
    for r in rows(F_AGE):
        if "에소메졸" in r["제품명"]:
            has_age["에소메졸"] = True
    # ---- 병용금기(스트리밍): 콜드-에스 × 이지렉트정1.0 ----
    combo = None
    cold_vs_acetaminophen_single = 0
    for r in rows(F_COMBO):
        a, b = r["제품명A"], r["제품명B"]
        if a.startswith("이지렉트정1.0밀리그램") and b.startswith("타이레놀콜드-에스정"):
            combo = dict(제품명A=a, 성분코드A=r["성분코드A"], 제품코드A=r["제품코드A"], 제품명B=b, 성분코드B=r["성분코드B"], 제품코드B=r["제품코드B"],
                         고시번호=r["고시번호"], 고시일자=r["고시일자"], 사유=r["상세정보"])
        if a.startswith("타이레놀정500") or b.startswith("타이레놀정500"):
            cold_vs_acetaminophen_single += 1
    # ---- 라벨(L3) ----
    t = {k: eyak[k] for k in ("202106092", "202106954", "202005623")}
    label = {
        "202106954": dict(제품명="타이레놀콜드-에스정",
                          사용법=_pick(t["202106954"]["useMethodQesitm"], "만 15세 이상은 1회 1정씩, 1일 3회 식후 30분에 복용합니다."),
                          임부=_seg(t["202106954"]["atpnQesitm"], "임부 또는 임신하고 있을 가능성이 있는 여성, 수유부"),
                          상호작용=_seg(t["202106954"]["intrcQesitm"], "MAO 억제제(항우울제, 항정신병제, 감정조절제, 항파킨슨제 등)"),
                          상호작용2=_pick(t["202106954"]["intrcQesitm"], "아세트아미노펜을 포함하는 다른 제품"),
                          출처="e약은요 API 샘플(data/api_samples)"),
        "202106092": dict(제품명="타이레놀정500밀리그람(아세트아미노펜)",
                          사용법=_pick(t["202106092"]["useMethodQesitm"], "만 12세 이상 소아 및 성인은 1회 1~2정씩, 1일 3~4회(4~6시간 마다) 필요시 복용합니다."),
                          임부=_seg(t["202106092"]["atpnQesitm"], "임부 또는 수유부, 글루타치온 보유량이 낮은 상태의 환자는 의사 또는 약사와 상의하십시오."),
                          상호작용=_seg(t["202106092"]["intrcQesitm"], "와파린, 플루클록사실린을 복용하는 환자는 의사 또는 약사와 상의하십시오."),
                          출처="e약은요 API 샘플(data/api_samples)"),
        "202005623": dict(제품명="어린이타이레놀산160밀리그램(아세트아미노펜)",
                          사용법=_pick(t["202005623"]["useMethodQesitm"], "만 7~12세 소아는 1회 권장용량을 4~6시간마다 필요시 물 없이 혀에 직접 복용합니다."),
                          용량안내=_pick(t["202005623"]["useMethodQesitm"], "연령대별 용량은 허가사항을 참고하십시오."),
                          출처="e약은요 API 샘플(data/api_samples)"),
        # 아래는 샘플 파일에 없어 RFP-21 §4.4의 2026-11-01 API 확인값을 그대로 옮긴 것(출처 표시)
        "202200525": dict(제품명="어린이타이레놀현탁액(아세트아미노펜)",
                          사용법="만 12세 이하의 소아는 1회 권장용량을 4-6시간마다 필요 시 복용합니다.",
                          용량안내="연령대별 권장용량은 허가사항을 참고하십시오.",
                          상호작용="아세트아미노펜을 포함한 해열진통제와 함께 복용하지 마십시오.",
                          출처="RFP-21 §4.4 (2026-11-01 e약은요 API 확인값)"),
    }
    cand7 = [  # RFP-21 §4.3 후보 7개(품목기준코드, 제품명, 사용법 앞부분, DUR 품목정보 수록)
        ("202106092", "타이레놀정500밀리그람(아세트아미노펜)", "만 12세 이상 소아 및 성인은 1회 1~2정씩, 1일 3~4회(4~6시간 마다) 필요", True),
        ("202200407", "타이레놀8시간이알서방정(아세트아미노펜)", "12세 이상의 소아와 성인은 1회 2정을 매 8시간마다 복용합니다. 24시간 동안 6정", True),
        ("202201300", "타이레놀산500밀리그램(아세트아미노펜)", "만 12세 이상 소아 및 성인은 1회 1~2포씩 1일 3~4회(4-6시간 마다) 필요", True),
        ("202106954", "타이레놀콜드-에스정", "만 15세 이상은 1회 1정씩, 1일 3회 식후 30분에 복용합니다.", True),
        ("202200658", "우먼스타이레놀정", "성인 및 12세 이상의 소아는 1회 1~2정을 필요 시 6시간 간격으로 복용합니다.", True),
        ("202005623", "어린이타이레놀산160밀리그램(아세트아미노펜)", "만 7~12세 소아는 1회 권장용량을 4~6시간마다 필요시 물 없이 혀에 직접 복용합니다.", False),
        ("202200525", "어린이타이레놀현탁액(아세트아미노펜)", "만 12세 이하의 소아는 1회 권장용량을 4-6시간마다 필요 시 복용합니다.", False),
    ]
    facts = dict(
        asof=ASOF, preg=preg, age=age, has_age=has_age, combo=combo, acetaminophen_single_combo_rows=cold_vs_acetaminophen_single,
        label=label, cand7=cand7,
        # RFP-21 §4.6의 성분정보 API 확인값(2026-11-01). 파일과 고시일자가 다르다.
        api_ingr_combo=dict(성분A="D000200 덱스트로메토르판", 성분B="D000698 라사길린", 고시일자="2017-11-06", 사유="경련, 반사항진, 이상고열, 혼수 등",
                            출처="DUR 성분정보 API getUsjntTabooInfoList02 (RFP-21 §4.6, 2026-11-01 확인값)"),
        api_ingr_preg=dict(성분="D000448 슈도에페드린", 등급="2", 문구="임부에 대한 안전성 미확립.", 출처="DUR 성분정보 API 임부금기 (RFP-21 §4.5)"),
        grade_def={"2": "고시 「의약품 병용금기 성분 등의 지정에 관한 규정」 제3조 제3호 나목 등급(2등급)"},  # 정의 문구는 모델이 새로 쓰지 않는다
    )
    return facts


def load(refresh=False):
    if CACHE.exists() and not refresh:
        return json.loads(CACHE.read_text())
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    f = build()
    CACHE.write_text(json.dumps(f, ensure_ascii=False, indent=1))
    return f


def all_names():
    """가상 약 이름이 실제 파일에 없는지 확인할 때 쓰는 제품명 집합(전 CSV)."""
    names = set()
    for p in glob.glob(str(DATA / "*.csv")):
        for enc in ("cp949", "utf-8-sig"):
            try:
                names.update(r.get("제품명", "") for r in rows(p, enc))
                break
            except UnicodeDecodeError:
                continue
    return names


if __name__ == "__main__":
    f = load(refresh=True)
    print(json.dumps({k: (v if k not in ("label", "cand7") else "...") for k, v in f.items()}, ensure_ascii=False, indent=1)[:3500])
