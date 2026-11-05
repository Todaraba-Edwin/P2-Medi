"""네트워크 없이 스냅샷(mock/api_snapshots)과 data/ CSV만으로 PRD 15.3 시나리오 S1~S8의 각 단계가 재현되는지 점검한다(RFP-32).

단계: 1 제품 찾기 → 2 성분 풀기 → 3 금기 확인 → 4 라벨 문장.
파일(CSV)과 API가 다르면 감추지 않고 note에 그대로 적는다(고시일자·등급 표기 등).
S7(범위 외·인젝션)은 데이터가 필요 없어 '해당 없음', S8(API 실패)은 스냅샷이 아니라 이 스크립트가 만든 오류 응답 샘플로 처리한다.
결과: mock/api_snapshots/SCENARIO_COVERAGE.md, SCENARIO_COVERAGE.json, s8_error_samples/.
사용: .venv/bin/python scripts/mock/replay_check.py
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import api_snapshot as A  # noqa: E402  (이 모듈은 import해도 네트워크를 쓰지 않는다. 여기서는 load_snapshot만 쓴다)
import facts as F  # noqa: E402

ROOT = A.ROOT
SNAP = A.SNAP
DATA = ROOT / "data"
F_DOSE = DATA / "한국의약품안전관리원_용량주의약물_20260721.csv"
TARGETS = json.loads((SNAP / "targets.json").read_text(encoding="utf-8"))["resolved"]


def seq(key: str) -> str:
    return TARGETS[key]["items"][0]["item_seq"]


def name(key: str) -> str:
    return TARGETS[key]["items"][0]["item_name"]      # 끝 공백까지 그대로(Prduct는 정확 일치, 스냅샷 해시도 원문 이름 기준)


class Ctx:
    """한 단계가 읽은 스냅샷 파일을 기록한다. 스냅샷이 없으면 missing에 쌓는다."""

    def __init__(self):
        self.files, self.missing = [], []

    def snap(self, svc, op, params, pages=1):
        out, total = [], None
        for p in range(1, pages + 1):
            prm = {**params, "pageNo": p} if p > 1 else params
            h = A.request_hash(svc, op, prm)
            path = A.snap_path(svc, op, h)
            if path is None:
                self.missing.append(f"{svc}/{op} {params}")
                return None, None
            self.files.append(str(path.relative_to(SNAP)))
            j = json.loads(path.read_text(encoding="utf-8"))
            total = (j.get("body") or {}).get("totalCount")
            out += A.extract_items(j.get("body") or {})
            if p * int(A.norm_params(params)["numOfRows"]) >= int(total or 0):
                break
        return out, total


# ---- CSV (data/) ----
_cache: dict = {}


def csv_rows(path):
    if path not in _cache:
        _cache[path] = list(F.rows(path))
    return _cache[path]


def preg_rows(prefix):
    return [r for r in csv_rows(F.F_PREG) if r["제품명"].startswith(prefix)]


def age_rows(prefix):
    return [r for r in csv_rows(F.F_AGE) if r["제품명"].startswith(prefix)]


def dose_rows(prefix):
    return [r for r in csv_rows(F_DOSE) if r["약품명"].startswith(prefix)]


_combo = None


def combo_rows():
    """병용금기 CSV(약 250MB)는 한 번만 스트리밍하며 관심 쌍만 모은다."""
    global _combo
    if _combo is None:
        _combo = {"easerect_cold": [], "acet_single": 0}
        for r in F.rows(F.F_COMBO):
            a, b = r["제품명A"], r["제품명B"]
            if a.startswith("이지렉트정1.0밀리그램") and b.startswith("타이레놀콜드-에스정"):
                _combo["easerect_cold"].append(r)
            if a.startswith("타이레놀정500") or b.startswith("타이레놀정500"):
                _combo["acet_single"] += 1
    return _combo


def grade_num(s):
    m = re.search(r"\d", s or "")
    return m.group(0) if m else None


def nb_section(detail_item, key):
    """허가 상세 XML 본문 중 ARTICLE 제목에 key가 든 절의 CDATA 문장을 모은다."""
    nb = detail_item.get("NB_DOC_DATA") or ""
    out = []
    for m in re.finditer(r'<ARTICLE title="([^"]*)">(.*?)</ARTICLE>', nb, flags=re.S):
        if key in m.group(1):
            out += re.findall(r"<!\[CDATA\[(.*?)\]\]>", m.group(2), flags=re.S)
    return out


STEPS = []   # (시나리오, 단계, 필요 데이터, 파일 목록, 결과, 비고)


def step(scn, no, title, need, fn):
    ctx = Ctx()
    try:
        ok, notes = fn(ctx)
    except Exception as e:  # noqa: BLE001
        ok, notes = False, [f"점검 중 오류: {type(e).__name__}: {e}"]
    if ctx.missing:
        ok, notes = False, notes + [f"스냅샷 없음: {', '.join(sorted(set(ctx.missing)))}"]
    state = "재현" if ok is True else ("해당 없음" if ok is None else "미재현")
    STEPS.append(dict(scenario=scn, step=no, title=title, need=need, files=ctx.files, state=state, notes=notes))


# =====================================================================================
# 공통 단계 구현
# =====================================================================================
def find_eyak(ctx, key):
    items, _ = ctx.snap("eyak", "getDrbEasyDrugList", {"itemSeq": seq(key)})
    return items[0] if items else None


def find_permit(ctx, key):
    items, _ = ctx.snap("drug-prmsn", "getDrugPrdtPrmsnDtlInq08", {"item_seq": seq(key)})
    return items[0] if items else None


def s_find(keys, rx_note=True):
    def fn(ctx):
        notes, ok = [], True
        for k in keys:
            e, p = find_eyak(ctx, k), find_permit(ctx, k)
            if p is None:
                ok = False
                notes.append(f"{name(k)}: 허가 상세 없음")
                continue
            notes.append(f"{name(k).strip()}({seq(k)}): 허가정보 {p['ETC_OTC_CODE']}" + (", e약은요 있음" if e else ", e약은요 0건(전문의약품이라 e약은요에 없음)"))
            if e is None and p["ETC_OTC_CODE"] != "전문의약품":
                ok = False
                notes.append("  일반의약품인데 e약은요 0건")
        return ok, notes
    return fn


def s_ingr(keys, expect):
    """허가 주성분 상세와 DUR 품목정보 MATERIAL_NAME으로 성분을 푼다. expect: {키: [성분명 일부]}"""
    def fn(ctx):
        notes, ok = [], True
        for k in keys:
            m, _ = ctx.snap("drug-prmsn", "getDrugPrdtMcpnDtlInq08", {"Prduct": name(k)})
            d, _ = ctx.snap("dur-item", "getDurPrdlstInfoList03", {"itemSeq": seq(k)})
            names = [x["MTRAL_NM"] for x in (m or [])]
            codes = [x["MTRAL_CODE"] for x in (m or [])]
            for must in expect.get(k, []):
                if not any(must in n for n in names):
                    ok = False
                    notes.append(f"{name(k)}: 성분 '{must}' 못 찾음 {names}")
            notes.append(f"{name(k)}: 주성분 {names} ({','.join(codes)}); DUR 품목정보 {'수록' if d else '0건(DUR 품목정보에 없음, 성분은 허가정보로 풀어야 함)'}")
        return ok, notes
    return fn


def api_pwnm(ctx, code):
    items, total = ctx.snap("dur-ingr", "getPwnmTabooInfoList02", {"ingrCode": code})
    return items, total


def s_preg(rows):
    """rows: [(제품명 접두사, 성분코드(D…), 기대: 'listed'|'absent')] — 파일 CSV와 성분정보 API, 품목정보 API를 대조."""
    def fn(ctx):
        notes, ok = [], True
        for prefix, code, expect, key in rows:
            f = preg_rows(prefix)
            a, total = api_pwnm(ctx, code)
            it, itotal = ctx.snap("dur-item", "getPwnmTabooInfoList03", {"itemSeq": seq(key)}, pages=1)
            if expect == "listed":
                if not f:
                    ok = False
                    notes.append(f"{prefix}: 파일(임부금기 CSV)에 없음")
                if not a:
                    ok = False
                    notes.append(f"{prefix}: 성분정보 API {code} 임부금기 0건")
                if f and a:
                    fg = f[0]["금기등급"]
                    ag = {grade_num(x.get("GRADE")) for x in a}
                    ad = sorted({x.get("NOTIFICATION_DATE") for x in a})
                    diff = "일치" if fg in ag else f"등급 다름(파일 {fg} / API {sorted(ag)})"
                    notes.append(f"{prefix}: 파일 {fg}등급(고시 {f[0]['고시일자']}, {f[0]['고시번호']}) / 성분 API {code} {sorted(ag)}등급(고시일자 {ad}) → {diff}; 품목 API {len(it or [])}건")
            else:
                if f:
                    ok = False
                    notes.append(f"{prefix}: 파일에 있음(기대 '목록에 없음' 위반)")
                if a:
                    ok = False
                    notes.append(f"{prefix}: 성분 API {code}가 0건이 아님({len(a)})")
                notes.append(f"{prefix}: 파일 0행 / 성분 API {code} {len(a or [])}건 / 품목 API {len(it or [])}건 → 금기 목록에 없음(안전 단정 아님)")
        return ok, notes
    return fn


def s_label(checks):
    """checks: [(키, 필드, 기대 문장)] — e약은요 필드에 문장이 그대로 들어 있는지. 전문의약품은 ('permit', 절 키, 필수 단어)."""
    def fn(ctx):
        notes, ok = [], True
        for kind, key, field, needle in checks:
            if kind == "eyak":
                e = find_eyak(ctx, key)
                if e is None:
                    ok = False
                    notes.append(f"{name(key)}: e약은요 없음")
                elif needle not in (e.get(field) or ""):
                    ok = False
                    notes.append(f"{name(key)}: e약은요 {field}에 문장 없음: {needle[:30]}…")
                else:
                    notes.append(f"{name(key)}: e약은요 {field}에 문장 있음 ✔ {needle[:26]}…")
            elif kind == "absent":                       # 라벨 어디에도 단어가 없음(S6c '통풍')
                e, p = find_eyak(ctx, key), find_permit(ctx, key)
                texts = [str(v) for v in (e or {}).values()] + [str(p.get(f, "")) for f in ("EE_DOC_DATA", "UD_DOC_DATA", "NB_DOC_DATA")] if p else [str(v) for v in (e or {}).values()]
                if any(needle in t for t in texts):
                    ok = False
                    notes.append(f"{name(key)}: 라벨에 '{needle}'이 있음(기대 없음)")
                else:
                    notes.append(f"{name(key)}: e약은요·허가 상세 본문에 '{needle}' 없음 ✔")
            else:                                        # permit 본문 절
                p = find_permit(ctx, key)
                sents = nb_section(p or {}, field)
                if not sents or (needle and not any(needle in s_ for s_ in sents)):
                    ok = False
                    notes.append(f"{name(key)}: 허가 상세 NB '{field}' 절 문장 없음({len(sents)}개)")
                else:
                    notes.append(f"{name(key)}: 허가 상세 NB '{field}' 절 문장 {len(sents)}개 ✔ \"{sents[-1][:36].strip()}…\"")
        return ok, notes
    return fn


LB = F.load()["label"]


def build_steps():
    # ---------------- S1 ----------------
    s1 = ["tylenol_500", "tylenol_cold_s"]
    step("S1", 1, "제품 찾기", "e약은요·허가정보 품목(정500, 콜드-에스)", s_find(s1))
    step("S1", 2, "성분 풀기", "허가 주성분 상세, DUR 품목정보 MATERIAL_NAME", s_ingr(s1, {"tylenol_500": ["아세트아미노펜"], "tylenol_cold_s": ["아세트아미노펜", "슈도에페드린", "덱스트로메토르판", "클로르페니라민"]}))
    step("S1", 3, "금기 확인(임부)", "임부금기 CSV, DUR 성분정보 D000448·D000147, 품목정보 임부금기",
         s_preg([("타이레놀콜드-에스정", "D000448", "listed", "tylenol_cold_s"), ("타이레놀정500", "D000147", "absent", "tylenol_500")]))
    step("S1", 4, "라벨 문장", "e약은요 주의사항(임부)", s_label([("eyak", "tylenol_cold_s", "atpnQesitm", LB["202106954"]["임부"]), ("eyak", "tylenol_500", "atpnQesitm", LB["202106092"]["임부"])]))
    # S1-v1 / v2 (M1 변형)
    step("S1-v1", 1, "제품 찾기", "허가정보 품목(심바로드정20, 정500)", s_find(["simvarod", "tylenol_500"]))
    step("S1-v1", 2, "성분 풀기", "허가 주성분 상세", s_ingr(["simvarod"], {"simvarod": ["심바스타틴"]}))
    step("S1-v1", 3, "금기 확인(임부)", "임부금기 CSV, DUR 성분정보 D000027, 품목정보 임부금기", s_preg([("심바로드정20", "D000027", "listed", "simvarod"), ("타이레놀정500", "D000147", "absent", "tylenol_500")]))
    step("S1-v1", 4, "라벨 문장", "허가 상세 NB '임부' 절(전문의약품이라 e약은요 없음)", s_label([("permit", "simvarod", "임부", "")]))
    step("S1-v2", 1, "제품 찾기", "허가정보 품목(로바스크정, 미프론정4mg)", s_find(["rovasc", "mipron"]))
    step("S1-v2", 2, "성분 풀기", "허가 주성분 상세", s_ingr(["rovasc", "mipron"], {"rovasc": ["암로디핀"], "mipron": ["메틸프레드니솔론"]}))
    step("S1-v2", 3, "금기 확인(임부)", "임부금기 CSV, DUR 성분정보 D000152·D000005", s_preg([("로바스크정", "D000152", "listed", "rovasc"), ("미프론정4mg", "D000005", "listed", "mipron")]))
    step("S1-v2", 4, "라벨 문장", "허가 상세 NB '임부' 절", s_label([("permit", "rovasc", "임부", ""), ("permit", "mipron", "임부", "")]))

    # ---------------- S2 ----------------
    def s2_combo(ctx):
        notes, ok = [], True
        c = combo_rows()
        if not c["easerect_cold"]:
            ok = False
            notes.append("병용금기 CSV에 이지렉트×콜드-에스 쌍 없음")
        else:
            r = c["easerect_cold"][0]
            notes.append(f"파일: {r['제품명A'][:18]}… × {r['제품명B']} 고시 {r['고시번호']}·{r['고시일자']}, 사유 \"{r['상세정보']}\"")
        a, _ = ctx.snap("dur-ingr", "getUsjntTabooInfoList02", {"ingrCode": "D000200"})
        pair = [x for x in (a or []) if x.get("MIXTURE_INGR_CODE") == "D000698"]
        if not pair:
            ok = False
            notes.append("성분정보 API D000200에 D000698(라사길린) 쌍 없음")
        else:
            notes.append(f"성분 API: D000200 덱스트로메토르판 × D000698 라사길린 고시일자 {pair[0]['NOTIFICATION_DATE']}, 사유 \"{pair[0]['PROHBT_CONTENT'].strip()}\"")
            if c["easerect_cold"]:
                notes.append(f"⚠ 고시일자 다름: 파일 {c['easerect_cold'][0]['고시일자']} / API {pair[0]['NOTIFICATION_DATE']} (같은 기준인지 미확인, 최신 여부 단정 안 함)")
        rev, _ = ctx.snap("dur-ingr", "getUsjntTabooInfoList02", {"ingrCode": "D000698"})
        notes.append(f"참고: 쌍은 A쪽 성분 기준으로만 조회된다 — D000698 조회는 {len(rev or [])}건이고 덱스트로메토르판은 없음(방향 있음)")
        cold, tc = ctx.snap("dur-item", "getUsjntTabooInfoList03", {"itemSeq": seq("tylenol_cold_s")})
        notes.append(f"품목 API 콜드-에스 병용금기 {tc}건(0건이면 복합제를 성분으로 풀지 않음)")
        ez, tz = ctx.snap("dur-item", "getUsjntTabooInfoList03", {"itemSeq": seq("easerect")}, pages=4)
        got = len(ez or [])
        hit = [x for x in (ez or []) if "타이레놀" in (x.get("MIXTURE_ITEM_NAME") or "")]
        notes.append(f"품목 API 이지렉트 병용금기 총 {tz}건 중 {got}건 저장, 타이레놀 쌍 {len(hit)}건")
        a1, _ = ctx.snap("dur-ingr", "getUsjntTabooInfoList02", {"ingrCode": "D000147"})
        notes.append(f"아세트아미노펜 D000147 병용금기 성분 API {len(a1 or [])}건; 파일 타이레놀정500 쌍 {c['acet_single']}행 → 단일제는 '금기 목록에 없음'")
        if (a1 or c["acet_single"]):
            ok = False
        return ok, notes
    step("S2", 1, "제품 찾기", "허가정보 품목(이지렉트정, 콜드-에스, 정500)", s_find(["easerect", "tylenol_cold_s", "tylenol_500"]))
    step("S2", 2, "성분 풀기", "허가 주성분 상세(라사길린·덱스트로메토르판)", s_ingr(["easerect", "tylenol_cold_s"], {"easerect": ["라사길린"], "tylenol_cold_s": ["덱스트로메토르판"]}))
    step("S2", 3, "금기 확인(병용)", "병용금기 CSV, 성분정보 D000200·D000698·D000147, 품목정보 병용금기", s2_combo)
    step("S2", 4, "라벨 문장", "e약은요 콜드-에스 상호작용(MAO 억제제)", s_label([("eyak", "tylenol_cold_s", "intrcQesitm", LB["202106954"]["상호작용"][:60])]))

    # ---------------- S3 ----------------
    def s3_dup(ctx):
        notes, ok = [], True
        ef, _ = ctx.snap("dur-ingr", "getEfcyDplctInfoList02", {"ingrCode": "D000147"}, pages=3)
        notes.append(f"성분 API 효능군중복 D000147: {len(ef or [])}건, 효능군 {sorted({x.get('EFFECT_CODE') for x in (ef or [])})[:3]}")
        if not ef:
            ok = False
        for k in ("tylenol_cold_s", "children_susp"):
            it, t = ctx.snap("dur-item", "getEfcyDplctInfoList03", {"itemSeq": seq(k)})
            notes.append(f"품목 API 효능군중복 {name(k)}: {t}건")
        for k in ("children_susp",):
            ag, t = ctx.snap("dur-item", "getSpcifyAgrdeTabooInfoList03", {"itemSeq": seq(k)})
            notes.append(f"품목 API 연령금기 {name(k)}: {t}건 → 제품 연령은 라벨 문장으로만 확인(데이터 공백)")
        age_api, _ = ctx.snap("dur-ingr", "getSpcifyAgrdeTabooInfoList02", {"ingrCode": "D000147"}, pages=1)
        notes.append("성분 API 연령금기 D000147: " + ", ".join(sorted({f"{x.get('AGE_BASE')}/{x.get('FORM_NAME')}" for x in (age_api or [])})[:4]))
        d = dose_rows("어린이타이레놀현탁액")
        if d:
            notes.append(f"파일(용량주의 CSV): {d[0]['약품명']} 1일 최대투여량 {d[0]['1일 최대투여량']}, 공고 {d[0]['공고일자']}")
        else:
            ok = False
            notes.append("용량주의 CSV에 어린이타이레놀현탁액 없음")
        cp, _ = ctx.snap("dur-ingr", "getCpctyAtentInfoList02", {"ingrCode": "D000147"}, pages=3)
        notes.append(f"성분 API 용량주의 D000147: {len(cp or [])}건")
        return ok, notes
    def s3_label(ctx):
        ok, notes = s_label([("eyak", "tylenol_cold_s", "useMethodQesitm", LB["202106954"]["사용법"]),
                             ("eyak", "children_susp", "intrcQesitm", "아세트아미노펜을 포함한 해열진통제와 함께 복용하지 마십시오."),
                             ("eyak", "children_susp", "useMethodQesitm", "연령대별 권장용량은 허가사항을 참고하십시오.")])(ctx)
        p = find_permit(ctx, "children_susp")
        ud = (p or {}).get("UD_DOC_DATA") or ""
        has_table = ("mL" in ud or "mℓ" in ud or "㎖" in ud) and "kg" in ud
        notes.append(f"허가 상세 UD_DOC_DATA {len(ud)}자, 체중·mL 용량 표 {'있음 ✔(근거 상세 원문 인용용)' if has_table else '못 찾음'}")
        return ok and has_table, notes
    s3 = ["children_susp", "tylenol_cold_s"]
    step("S3", 1, "제품 찾기", "e약은요·허가정보 품목(어린이현탁액, 콜드-에스)", s_find(s3))
    step("S3", 2, "성분 풀기", "허가 주성분 상세(M-코드), DUR 품목정보(어린이 2종은 0건 예상)", s_ingr(s3, {"children_susp": ["아세트아미노펜"], "tylenol_cold_s": ["아세트아미노펜"]}))
    step("S3", 3, "금기 확인(중복·연령·용량)", "성분정보 효능군중복·연령·용량주의, 품목정보, 용량주의 CSV", s3_dup)
    step("S3", 4, "라벨 문장", "e약은요 사용법·상호작용, 허가 상세 용량 표", s3_label)
    def s3v1(ctx):
        notes, ok = [], True
        f = age_rows("타이레놀8시간이알서방정")
        notes.append(f"파일(연령금기 CSV): {len(f)}행" + (f" — {f[0]['특정연령']}{f[0]['특정연령단위']} {f[0]['연령처리조건']}, 고시 {f[0]['고시일자']}" if f else ""))
        if not f:
            ok = False
        a, t = ctx.snap("dur-item", "getSpcifyAgrdeTabooInfoList03", {"itemSeq": seq("tylenol_8h")})
        notes.append(f"품목 API 연령금기 {t}건" + (f" — {a[0].get('PROHBT_CONTENT','').strip()[:40]} (고시일자 {a[0].get('NOTIFICATION_DATE')})" if a else ""))
        i, t2 = ctx.snap("dur-ingr", "getSpcifyAgrdeTabooInfoList02", {"ingrCode": "D000147"})
        notes.append("성분 API 연령금기 D000147: " + ", ".join(sorted({f"{x.get('AGE_BASE')}/{x.get('FORM_NAME')}" for x in (i or [])})[:4]))
        sp, t3 = ctx.snap("dur-item", "getSeobangjeongPartitnAtentInfoList03", {"itemSeq": seq("tylenol_8h")})
        notes.append(f"품목 API 서방정분할주의 {t3}건")
        return ok and bool(a), notes
    step("S3-v1", 1, "제품 찾기", "e약은요·허가정보 품목(8시간이알서방정)", s_find(["tylenol_8h"]))
    step("S3-v1", 2, "성분 풀기", "허가 주성분 상세", s_ingr(["tylenol_8h"], {"tylenol_8h": ["아세트아미노펜"]}))
    step("S3-v1", 3, "금기 확인(연령)", "연령금기 CSV, 품목정보·성분정보 연령금기", s3v1)
    step("S3-v1", 4, "라벨 문장", "e약은요 사용법(연령 문장)", s_label([("eyak", "tylenol_8h", "useMethodQesitm", "12세 이상의 소아와 성인은 1회 2정을 매 8시간마다 복용합니다.")]))

    # ---------------- S4 ----------------
    def s4_find(ctx):
        notes, ok = [], True
        e, te = ctx.snap("eyak", "getDrbEasyDrugList", {"itemName": "타이레놀"})
        d, td = ctx.snap("dur-item", "getDurPrdlstInfoList03", {"itemName": "타이레놀"})
        p, tp = ctx.snap("drug-prmsn", "getDrugPrdtPrmsnInq08", {"item_name": "타이레놀"})
        notes.append(f"e약은요 {te}건 / DUR 품목정보 {td}건 / 허가 목록 {tp}건")
        if te != 7 or td != 5 or tp != 7:
            ok = False
        dur_seqs = {x["ITEM_SEQ"] for x in (d or [])}
        for x in (e or []):
            first = (x.get("useMethodQesitm") or "").strip().split("  ")[0][:28]
            notes.append(f"  {x['itemSeq']} {x['itemName'][:20]} | DUR {'수록' if x['itemSeq'] in dur_seqs else '없음'} | 사용법 \"{first}…\"")
        missing = sorted({x["itemSeq"] for x in (e or [])} - dur_seqs)
        notes.append(f"DUR 품목정보에 없는 품목: {missing}")
        if missing != ["202005623", "202200525"]:
            ok = False
        return ok, notes
    step("S4", 1, "제품 찾기(후보 7개)", "e약은요·DUR 품목정보·허가 목록 '타이레놀'", s4_find)
    step("S4", 2, "성분 풀기", "후보별 성분(허가 주성분)", s_ingr([k for k in TARGETS if k.startswith(("tylenol", "womens", "children"))], {k: ["아세트아미노펜"] for k in TARGETS if k.startswith(("tylenol", "womens", "children"))}))
    step("S4", 3, "금기 확인", "되묻기 단계라 금기 판정 없음(가부 문장 없음은 코드 검사)", lambda c: (None, ["해당 없음: 되묻기 카드에는 금기 판정을 넣지 않는다"]))
    step("S4", 4, "라벨 문장", "e약은요 사용법 첫 문장(후보 표)", s_label([("eyak", k, "useMethodQesitm", "") for k in TARGETS if k.startswith(("tylenol", "womens", "children"))]))

    # ---------------- S5 ----------------
    def s5_age(ctx):
        notes, ok = [], True
        f = age_rows("에소메졸")
        notes.append(f"파일(연령금기 CSV) 에소메졸 {len(f)}행 → 목록에 없음" + ("" if not f else " ⚠ 기대와 다름"))
        if f:
            ok = False
        a, t = ctx.snap("dur-item", "getSpcifyAgrdeTabooInfoList03", {"itemSeq": seq("esomezol")})
        notes.append(f"품목 API 연령금기 {t}건")
        ia, ti = ctx.snap("dur-ingr", "getSpcifyAgrdeTabooInfoList02", {"ingrCode": "D000153"})
        notes.append(f"성분 API 연령금기 D000153(에스오메프라졸): {ti}건" + (f" — {sorted({x.get('AGE_BASE') for x in ia})}" if ia else ""))
        if t:
            ok = False
        return ok, notes
    step("S5", 1, "제품 찾기", "허가정보 품목(에소메졸캡슐40)", s_find(["esomezol"]))
    step("S5", 2, "성분 풀기", "허가 주성분 상세", s_ingr(["esomezol"], {"esomezol": ["에스오메프라졸"]}))
    step("S5", 3, "금기 확인(연령)", "연령금기 CSV, 품목정보·성분정보 연령금기", s5_age)
    step("S5", 4, "라벨 문장", "허가 상세 NB 본문(전문의약품): '과량 투여시의 처치' 절 존재 — 서비스의 응급 안내 근거로 쓸지는 RFP-19 판단(M1은 쓰지 않음)", s_label([("permit", "esomezol", "과량", "")]))   # 허가사항에 '과량 투여시의 처치' 절이 있다. 응급 지침으로 쓸지는 RFP-19 판단

    # ---------------- S6 ----------------
    step("S6a", 1, "제품 찾기(보정 후)", "허가정보 품목(미프론정4mg)", s_find(["mipron"]))
    step("S6a", 3, "금기 확인(임부)", "임부금기 CSV, 성분정보 D000005", s_preg([("미프론정4mg", "D000005", "listed", "mipron")]))

    def s6b(ctx):
        notes, ok = [], True
        for svc, op, key in [("eyak", "getDrbEasyDrugList", "itemName"), ("dur-item", "getDurPrdlstInfoList03", "itemName"), ("drug-prmsn", "getDrugPrdtPrmsnInq08", "item_name")]:
            items, t = ctx.snap(svc, op, {key: "라모시넥스"})
            notes.append(f"{svc} {op} {key}=라모시넥스 → {t}건")
            if t != 0:
                ok = False
        hit = [n for p in (F.F_PREG, F.F_AGE) for n in {r["제품명"] for r in csv_rows(p)} if "라모시넥스" in n]
        notes.append(f"임부금기·연령금기 CSV 제품명에 '라모시넥스' {len(hit)}건")
        if hit:
            ok = False
        return ok, notes
    step("S6b", 1, "제품 찾기(가상 약)", "세 서비스 0건 + CSV 부재", s6b)
    step("S6b", 3, "금기 확인", "성분을 풀지 못함 → 근거 없음(금기 없음이라 말하지 않음)", lambda c: (None, ["해당 없음: 약 미식별이라 금기 조회를 하지 않는다"]))
    step("S6c", 4, "라벨 문장(근거 없음)", "정500 라벨에 '통풍' 없음", s_label([("absent", "tylenol_500", "", "통풍")]))

    # ---------------- S7 ----------------
    step("S7", "-", "범위 외·인젝션·복용 중단 유도", "데이터 불필요(코드 규칙)", lambda c: (None, ["해당 없음: 스냅샷이 필요하지 않다(입구 분류·고정 문구는 코드)"]))

    # ---------------- S8 ----------------
    def s8(ctx):
        d = SNAP / "s8_error_samples"
        d.mkdir(parents=True, exist_ok=True)
        samples = {
            # 형식은 PJ2-API-엔티티.md 2장에서 실제로 확인한 오류 응답 모양(HTTP 400·403, cmmMsgHeader)을 따른다. 값은 이 스크립트가 만든 샘플이다.
            "http_403_service_key_not_registered.xml": ('<?xml version="1.0" encoding="UTF-8"?><OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>'
                                                        '<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg><returnReasonCode>30</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>', 403),
            "http_400_no_openapi_service.xml": ('<?xml version="1.0" encoding="UTF-8"?><OpenAPI_ServiceResponse><cmmMsgHeader><errMsg>SERVICE ERROR</errMsg>'
                                                '<returnAuthMsg>NO_OPENAPI_SERVICE_ERROR</returnAuthMsg><returnReasonCode>12</returnReasonCode></cmmMsgHeader></OpenAPI_ServiceResponse>', 400),
            "http_500_server_error.json": (json.dumps({"header": {"resultCode": "99", "resultMsg": "SYNTHETIC SERVER ERROR"}}, ensure_ascii=False), 500),
            "client_timeout.json": (json.dumps({"error": "ReadTimeout", "note": "클라이언트 시간 초과(응답 본문 없음)"}, ensure_ascii=False), None),
        }
        notes = []
        for fn_, (body, status) in samples.items():
            (d / fn_).write_text(body, encoding="utf-8")
            ctx.files.append(f"s8_error_samples/{fn_}")
            notes.append(f"{fn_}: HTTP {status}, 코드가 만든 샘플(실제 응답 아님)")
        notes.append("파일 기준 판정은 S1 3단계의 CSV 결과로 재현(API 없이)")
        ok = bool(preg_rows("타이레놀콜드-에스정")) and not preg_rows("타이레놀정500")
        return ok, notes
    step("S8", "1~3", "API 실패 → 파일 기준", "오류 응답 샘플(코드 생성) + 임부금기 CSV", s8)


def render(path_md, path_json):
    order = []
    for s in STEPS:
        if s["scenario"] not in order:
            order.append(s["scenario"])
    n_ok = sum(1 for s in STEPS if s["state"] == "재현")
    n_bad = sum(1 for s in STEPS if s["state"] == "미재현")
    n_na = sum(1 for s in STEPS if s["state"] == "해당 없음")
    lines = ["# 시나리오 × 스냅샷 재현 점검 (RFP-32)", "",
             "> `scripts/mock/replay_check.py`가 **네트워크 없이** 스냅샷(`mock/api_snapshots/`)과 `data/` CSV만으로 만든 표다. 로컬 전용이며 개발용이다(서비스 근거 데이터 아님).",
             "> 단계: 1 제품 찾기 → 2 성분 풀기 → 3 금기 확인 → 4 라벨 문장. 파일(CSV)과 API가 다르면 비고에 그대로 적었다.", "",
             f"**집계**: 단계 {len(STEPS)}개 중 재현 {n_ok}, 미재현 {n_bad}, 해당 없음 {n_na}.", "",
             "| 시나리오 | 단계 | 필요 데이터 | 스냅샷 파일(수) | 재현 |", "|---|---|---|---|---|"]
    for s in STEPS:
        files = s["files"]
        shown = ", ".join(f"`{f.split('/')[0]}/{f.split('/')[1][:14]}…/{f.split('/')[-1][:8]}`" for f in files[:2]) if files and "/" in files[0] and not files[0].startswith("s8_") else ", ".join(f"`{f}`" for f in files[:2])
        more = f" 외 {len(files) - 2}" if len(files) > 2 else ""
        lines.append(f"| {s['scenario']} | {s['step']} {s['title']} | {s['need']} | {len(files)}개: {shown}{more} | {s['state']} |")
    lines += ["", "## 단계별 비고(파일과 API 차이 포함)", ""]
    for sc in order:
        lines.append(f"### {sc}")
        for s in [x for x in STEPS if x["scenario"] == sc]:
            lines.append(f"- **{s['step']} {s['title']}** — {s['state']}")
            for n in s["notes"]:
                lines.append(f"  - {n}")
        lines.append("")
    path_md.write_text("\n".join(lines), encoding="utf-8")
    path_json.write_text(json.dumps(STEPS, ensure_ascii=False, indent=1), encoding="utf-8")
    return n_ok, n_bad, n_na


if __name__ == "__main__":
    build_steps()
    ok, bad, na = render(SNAP / "SCENARIO_COVERAGE.md", SNAP / "SCENARIO_COVERAGE.json")
    print(f"재현 {ok} / 미재현 {bad} / 해당 없음 {na}")
    for s in STEPS:
        if s["state"] == "미재현":
            print(f"미재현 {s['scenario']} {s['step']} {s['title']}: {s['notes']}")
