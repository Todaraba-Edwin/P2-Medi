"""RFP-31 M1(data/mock/chat_responses)의 사실 값을 RFP-32 스냅샷과 대조해 data/mock/api_snapshots/M1_DIFF.md 를 만든다(RFP-32 6단계).
M1은 고치지 않는다. 차이가 있으면 제안만 적는다. 네트워크·LLM 호출 없음.

대조 대상: 인용(citations) 중 API·e약은요(L3) 층 전부, 파일(L0) 층의 등급·고시일자 중 API와 비교할 수 있는 것, 본문에 나온 성분코드.
사용: .venv/bin/python evaluation/mock_gen/m1_diff.py
"""
import glob
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import api_snapshot as A  # noqa: E402

ROOT, SNAP = A.ROOT, A.SNAP
RESP = ROOT / "data" / "mock" / "chat_responses" / "responses"
TARGETS = json.loads((SNAP / "targets.json").read_text(encoding="utf-8"))["resolved"]
SEQ2KEY = {v["items"][0]["item_seq"]: k for k, v in TARGETS.items()}
rows = []   # (구분, 응답 id, 인용 id, M1 값, 스냅샷 값, 판정, 제안)
FIELD = {"atpn": "atpnQesitm", "intrc": "intrcQesitm", "use": "useMethodQesitm", "dose": "useMethodQesitm", "name": "itemName"}


def ws(s):
    return re.sub(r"\s+", " ", s or "").strip()


def snap_items(svc, op, params, pages=1):
    out = []
    for p in range(1, pages + 1):
        j, _ = A.load_snapshot(svc, op, {**params, "pageNo": p} if p > 1 else params)
        if j is None:
            return None
        out += A.extract_items(j.get("body") or {})
    return out


def add(kind, rid, cid, m1, sn, verdict, note=""):
    rows.append((kind, rid, cid, m1, sn, verdict, note))


def main():
    resp = {}
    for f in sorted(glob.glob(str(RESP / "*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        if d.get("response"):
            resp[d["id"]] = d
    seen = set()
    all_text = {}
    for rid, d in resp.items():
        r = d["response"]
        all_text[rid] = (r.get("answer") or "") + json.dumps(r.get("detail") or [], ensure_ascii=False) + json.dumps(r.get("summary_points") or [], ensure_ascii=False)
        for c in r.get("citations") or []:
            cid = c["id"]
            if (rid, cid) in seen:
                continue
            seen.add((rid, cid))
            origin = "RFP-21 확인값 옮김" if (c.get("origin") or "rfp21" in (c.get("key") or {})) else "샘플 파일 원문"
            q = c.get("quote") or ""
            if c["layer"] == "L3":
                seq = c["key"].get("eyak") or c["key"].get("rfp21")
                items = snap_items("eyak", "getDrbEasyDrugList", {"itemSeq": seq})
                kind_ = cid.rsplit(":", 1)[-1]
                if not items:
                    add("L3 라벨", rid, cid, q[:60], "스냅샷 없음", "대조 불가"); continue
                text = items[0].get(FIELD.get(kind_, "")) or ""
                if ws(q) == ws(items[0].get("itemName")) or ws(q) in ws(text):
                    add("L3 라벨", rid, cid, f"[{origin}] {q[:50]}…", "e약은요 스냅샷 필드에 그대로 포함", "일치")
                else:
                    add("L3 라벨", rid, cid, f"[{origin}] {q[:50]}…", f"{FIELD.get(kind_)} 안에 없음", "차이", "M1 인용문을 스냅샷 원문으로 교체")
            elif cid.startswith("API:ingr-preg:"):
                code = cid.split(":")[-1]
                it = snap_items("dur-ingr", "getPwnmTabooInfoList02", {"ingrCode": code}) or []
                ok = [x for x in it if ws(q) in ws(x.get("PROHBT_CONTENT"))]
                grades = sorted({x.get("GRADE") for x in it})
                add("API 성분 임부", rid, cid, f"[{origin}] \"{q}\" (등급 2)", f"{len(it)}건, GRADE {grades}, 문구 일치 {len(ok)}건, 고시일자 {sorted({x.get('NOTIFICATION_DATE') for x in it})}",
                    "일치" if ok and "2등급" in grades else "차이")
            elif cid.startswith("API:ingr-combo:"):
                it = snap_items("dur-ingr", "getUsjntTabooInfoList02", {"ingrCode": "D000200"}) or []
                pair = [x for x in it if x.get("MIXTURE_INGR_CODE") == "D000698"]
                if pair:
                    p = pair[0]
                    nd = f"{p['NOTIFICATION_DATE'][:4]}-{p['NOTIFICATION_DATE'][4:6]}-{p['NOTIFICATION_DATE'][6:]}"
                    same = ws(q) == ws(p["PROHBT_CONTENT"]) and c.get("notice_date") == nd
                    add("API 성분 병용", rid, cid, f"[{origin}] 고시일자 {c.get('notice_date')}, \"{q}\"", f"D000200×D000698 고시일자 {nd}, \"{ws(p['PROHBT_CONTENT'])}\", DEL_YN {p.get('DEL_YN')}", "일치" if same else "차이")
                else:
                    add("API 성분 병용", rid, cid, q, "쌍 없음", "차이")
            elif cid.startswith("API:item-combo:none:"):
                seq = cid.split(":")[-1]
                it = snap_items("dur-item", "getUsjntTabooInfoList03", {"itemSeq": seq})
                j, _ = A.load_snapshot("dur-item", "getUsjntTabooInfoList03", {"itemSeq": seq})
                t = (j or {}).get("body", {}).get("totalCount")
                add("API 품목 병용", rid, cid, f"[{origin}] 0건", f"totalCount {t}", "일치" if t == 0 else "차이")
            elif cid.startswith("API:item-ingr:"):
                seq = cid.split(":")[-1]
                it = snap_items("dur-item", "getDurPrdlstInfoList03", {"itemSeq": seq}) or []
                mat = it[0]["MATERIAL_NAME"] if it else ""
                names = [n.strip() for n in q.split(",")]
                miss = [n for n in names if n not in mat]
                add("API 품목 성분", rid, cid, f"[{origin}] {q}", f"MATERIAL_NAME에 성분 {len(names) - len(miss)}/{len(names)}개 포함", "일치" if not miss else "차이", "" if not miss else f"없는 성분 {miss}")
            elif c["layer"] == "L0" and c.get("key", {}).get("csv") == "preg" and c.get("grade"):
                code_map = {"227801ATB": ("D000027", "simvarod"), "107601ATB": ("D000152", "rovasc"), "193302ATB": ("D000005", "mipron"), "254000ATB": ("D000448", "tylenol_cold_s")}
                dc = code_map.get(cid.split(":")[-1])
                if dc:
                    it = snap_items("dur-ingr", "getPwnmTabooInfoList02", {"ingrCode": dc[0]}) or []
                    ag = sorted({re.sub(r"\D", "", x.get("GRADE") or "") for x in it})
                    ad = sorted({x.get("NOTIFICATION_DATE") for x in it})
                    nd = c.get("notice_date", "").replace("-", "")
                    add("파일↔API 임부", rid, cid, f"파일 등급 {c['grade']}, 고시 {c.get('notice_date')}", f"성분 API {dc[0]} 등급 {ag}, 고시일자 {ad}",
                        "등급 일치·고시일자 다름" if c["grade"] in ag and nd not in ad else ("일치" if c["grade"] in ag else "등급 차이"),
                        "M1이 이미 파일 값을 쓰고 있어 수정 불필요. 파일과 API의 고시일자가 다른 것은 병기 대상(단정 금지)" if c["grade"] in ag and nd not in ad else "")
            elif c["layer"] == "L0" and c.get("key", {}).get("csv") == "age" and c.get("age_rule"):
                seq = TARGETS["tylenol_8h"]["items"][0]["item_seq"]
                it = snap_items("dur-item", "getSpcifyAgrdeTabooInfoList03", {"itemSeq": seq}) or []
                add("파일↔API 연령", rid, cid, f"파일 {c['age_rule']}, 고시 {c.get('notice_date')}", f"품목 API {len(it)}건" + (f", 고시일자 {it[0].get('NOTIFICATION_DATE')}, 내용 \"{ws(it[0].get('PROHBT_CONTENT'))[:40]}\"" if it else ""),
                    "참고(내용이 다른 표기)" if it else "차이", "")
            elif c["layer"] == "L0" and c.get("key", {}).get("absent") == "에소메졸":
                it = snap_items("dur-item", "getSpcifyAgrdeTabooInfoList03", {"itemSeq": SEQ2KEY and TARGETS["esomezol"]["items"][0]["item_seq"]}) or []
                ia = snap_items("dur-ingr", "getSpcifyAgrdeTabooInfoList02", {"ingrCode": "D000153"}) or []
                add("파일↔API 연령", rid, cid, "파일 에소메졸 행 없음(목록에 없음)", f"품목 API {len(it)}건, 성분 API D000153 {len(ia)}건", "일치" if not it and not ia else "차이",
                    "" if not it and not ia else "API에는 연령금기가 있음 — M1의 '목록에 없음'은 파일 기준임을 명시해야 함")
            elif c["layer"] == "L0" and c.get("key", {}).get("csv") == "combo" and not c["key"].get("absent"):
                add("파일↔API 병용", rid, cid, f"파일 고시일자 {c.get('notice_date')}, 고시 {c.get('notice_no')}", "성분 API 쌍 고시일자 2017-11-06 (위 행과 같은 쌍)", "고시일자 다름(병기 대상)", "M1이 이미 두 값을 병기함")
    # 본문에 나온 D-코드가 스냅샷 성분 응답에 있는지
    codes = {}
    for rid, t in all_text.items():
        for cd in set(re.findall(r"D\d{6}", t)):
            codes.setdefault(cd, []).append(rid)
    for cd, rids in sorted(codes.items()):
        found = None
        for p in (SNAP / "dur-ingr").rglob("*.json"):
            if cd in p.read_text(encoding="utf-8"):
                found = p.name
                break
        add("성분코드", ",".join(rids[:3]), cd, f"본문에 {cd}", f"성분 스냅샷에 {'있음' if found else '없음'}", "일치" if found else "차이")

    n = {k: sum(1 for r in rows if r[5] == k) for k in sorted({r[5] for r in rows})}
    out = ["# M1 값 ↔ 스냅샷 대조 (RFP-32 6단계)", "",
           "> `evaluation/mock_gen/m1_diff.py`가 `data/mock/chat_responses/responses/*.json`의 사실 값을 `data/mock/api_snapshots/`와 대조한 결과다. **M1은 고치지 않았다**(제안만). 로컬 전용.",
           f"> 응답 {len(resp)}개(서버 오류 응답 제외), 대조 행 {len(rows)}개. 판정별: " + ", ".join(f"{k} {v}" for k, v in n.items()), "",
           "| 구분 | 응답 | 인용 id | M1 값 | 스냅샷 값 | 판정 | 제안/비고 |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        out.append("| " + " | ".join(str(x).replace("|", "\\|").replace("\n", " ") for x in r) + " |")
    (SNAP / "M1_DIFF.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("행", len(rows), n)
    for r in rows:
        if r[5] in ("차이", "등급 차이") :
            print("차이:", r[:6])


if __name__ == "__main__":
    main()
