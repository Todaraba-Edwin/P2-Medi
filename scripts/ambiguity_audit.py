"""문서 모호도(충돌·모호함) 수치 측정. 사용: python3 scripts/ambiguity_audit.py [--json 경로]

정의(amb-v1, 2026-11-07 측정 전 고정)는 report/SCH-00-ambiguity-audit-2026-11-07.md 2장과 같다.
코드로 셀 수 있는 값만 점수에 넣는다(모델 판단 없음). 표준 라이브러리만 쓰고 문서는 읽기만 한다.
정규식 휴리스틱이라 거짓 양성·거짓 음성이 있다(보고서 8장). 결과는 결정적이다(정렬된 순회, 시각 미포함).
"""
import datetime
import json
import os
import re
import subprocess
import sys

DEF_VERSION = "amb-v1"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

AREAS = "ABCDEFGH"
AREA_NAME = {
    "A": "에이전트 그래프·도구", "B": "하네스·안전", "C": "평가", "D": "데이터·API·적재",
    "E": "로깅·운영", "F": "입력 확장", "G": "화면·브랜드", "H": "일정·프로세스",
}
WEIGHT = {"A": 0.20, "B": 0.20, "C": 0.25, "D": 0.15, "E": 0.05, "F": 0.05, "G": 0.05, "H": 0.05}
EXCLUDE_DOCS = {"P2-doc/MFDS_병용금기_지정규정_고시.md", "P2-doc/IROS_239_e약은요_서비스_v1.0.md"}

TICKET_AREA = {}
def _assign(area, ids):
    for i in ids:
        TICKET_AREA[i] = area
_assign("A", ["AG-01", "AG-02", "AG-03", "AG-05", "AG-06", "AG-07", "AG-08", "AG-09", "AG-10", "AG-15",
              "RFP-02", "RFP-03", "RFP-04", "RFP-05", "RFP-06", "RFP-07", "RFP-08", "RFP-09",
              "RFP-22", "RFP-23", "RFP-25", "RFP-27", "PRD-02"])
_assign("B", ["RFP-10", "RFP-12", "RFP-13", "RFP-19", "RFP-29", "RFP-33"])
_assign("C", ["AG-04", "AG-11", "AG-12", "AG-13", "AG-14", "AG-16", "BE-08", "PRD-03", "RFP-11", "RFP-26", "RFP-28"])
_assign("D", ["BE-01", "BE-02", "BE-03", "BE-04", "BE-05", "BE-07", "BE-09", "BE-10", "BE-12",
              "RFP-15", "RFP-17", "RFP-21", "RFP-31", "RFP-32"])
_assign("E", ["RFP-34", "BE-06", "BE-13"])
_assign("F", ["PRD-08", "FE-05", "BE-14", "AG-17"])
_assign("G", ["FE-01", "FE-02", "FE-03", "FE-04", "FE-06", "PRD-06", "PRD-07", "RFP-20", "BE-11"])
_assign("H", ["RFP-01", "RFP-14", "RFP-16", "RFP-18", "RFP-24", "RFP-30", "PRD-01", "PRD-04", "PRD-05"])
# 지시서 영역 목록에 없던 것(추가 배정): 보고서에 표시
BRIEF_LISTED = {"AG-01", "AG-02", "AG-03", "AG-05", "AG-06", "AG-07", "AG-08", "AG-09", "AG-10", "RFP-22", "RFP-23",
                "RFP-25", "RFP-29", "RFP-33", "RFP-26", "AG-04", "AG-11", "AG-12", "AG-13", "AG-14", "AG-16", "BE-08",
                "PRD-03", "BE-01", "BE-02", "BE-03", "BE-04", "BE-05", "BE-09", "BE-10", "BE-12", "RFP-17", "RFP-21",
                "RFP-32", "RFP-34", "BE-06", "BE-13", "PRD-08", "FE-05", "BE-14", "AG-17", "FE-01", "FE-02", "FE-03",
                "FE-04", "FE-06", "PRD-06", "PRD-07"}
DOC_AREA = {
    "P2-doc/PJ2-Agent-Harness.md": "B", "P2-doc/PJ2-Agent-로깅-전략.md": "E", "P2-doc/PJ2-DUR-RAG-근거설계.md": "D",
    "P2-doc/PJ2-API-엔티티.md": "D", "P2-doc/PJ2-API-응답확인.md": "D", "P2-doc/PJ2-가설검증.md": "C",
    "P2-doc/PJ2-약국-약봉투-조사.md": "F", "schedule.md": "H", "schedule-done.md": "H",
    "schedule-changelog.md": "H", "CLAUDE.md": "H",
}
RFP_CH = {1: "H", 2: "H", 3: "H", 4: "H", 5: "D", 6: "A", 7: "B", 8: "A", 9: "C", 10: "H", 11: "H", 12: "H"}
PRD_CH = {1: "H", 2: "H", 3: "H", 4: "H", 5: "H", 7: "D", 8: "A", 9: "C", 10: "H", 11: "H", 12: "H", 13: "H", 14: "H", 15: "G"}

UNRESOLVED = ["미정", "미확인", "확인 못 함", "확인하지 못", "TBD", "(가정)", "가정:"]
HONEST = ["측정 전", "잠정"]
DEFERRED = ["미답", "번호 없이", "사용자 확인 필요", "확인 필요", "(보류)", "승인 대기", "답 대기", "열린 질문"]
HISTORY = re.compile(r"→|옛|(?<!에)이전|바꿈|바꿨|갱신|대신|였|폐기|정정")
TOOLS = ["identify_drug", "check_contraindications", "get_label_section", "search_notice", "search_reason", "search_label"]
NODES = ["guardrail_in", "router", "model", "tools", "validator", "finalize"]


def git_date(path):
    try:
        st = subprocess.run(["git", "status", "--porcelain", "--", path], capture_output=True, text=True, check=True).stdout
        if st.strip():
            return datetime.date.today().isoformat()
        out = subprocess.run(["git", "log", "-1", "--format=%cs", "--", path], capture_output=True, text=True, check=True).stdout
        return out.strip() or None
    except Exception:
        return None


def load_docs():
    """(경로, 영역, 시작 줄 번호, 줄 목록) 조각 목록. RFP·PRD는 장·절 단위로 나눈다."""
    files = []
    for d in ("P2-doc",):
        files += sorted(os.path.join(d, f) for f in os.listdir(d) if f.endswith(".md"))
    for d in sorted(os.listdir("tickets")):
        files += sorted(os.path.join("tickets", d, f) for f in os.listdir(os.path.join("tickets", d)) if f.endswith(".md"))
    files += ["schedule.md", "schedule-done.md", "schedule-changelog.md", "CLAUDE.md"]
    pieces, tickets = [], {}
    for path in files:
        if path in EXCLUDE_DOCS:
            continue
        lines = open(path, encoding="utf-8").read().split("\n")
        if path.startswith("tickets/"):
            tid = os.path.basename(path)[:-3]
            text = "\n".join(lines)
            fm = re.match(r"---\n(.*?)\n---", text, re.S)
            meta = dict(re.findall(r"^(\w+):\s*(.*)$", fm.group(1), re.M)) if fm else {}
            tickets[tid] = {"path": path, "meta": meta, "lines": lines}
            pieces.append((path, TICKET_AREA.get(tid, "H"), 1, lines))
        elif path in ("P2-doc/PJ2-RFP.md", "P2-doc/PJ2-PRD.md"):
            cur, start, buf = "H", 1, []
            for n, l in enumerate(lines, 1):
                m = re.match(r"## (\d+)\. ", l)
                m3 = re.match(r"### (\d+)\.(\d+) ", l)
                new = None
                if path.endswith("RFP.md") and m:
                    new = RFP_CH.get(int(m.group(1)), "H")
                elif path.endswith("PRD.md"):
                    if m:
                        ch = int(m.group(1))
                        new = "A" if ch == 6 else PRD_CH.get(ch, "H")
                    elif m3 and m3.group(1) == "6":
                        new = "A" if m3.group(2) == "1" else "B"
                if new is not None:
                    if buf:
                        pieces.append((path, cur, start, buf))
                    cur, start, buf = new, n, []
                buf.append(l)
            if buf:
                pieces.append((path, cur, start, buf))
        else:
            pieces.append((path, DOC_AREA.get(path, "H"), 1, lines))
    return pieces, tickets


def slug(h):
    h = re.sub(r"[^\w\- ]", "", h.strip().lower())
    return h.replace(" ", "-")


def anchors_of(path, cache={}):
    if path not in cache:
        seen, out, fence = {}, set(), False
        for l in open(path, encoding="utf-8").read().split("\n"):
            if l.lstrip().startswith("```"):
                fence = not fence
                continue
            if fence or not re.match(r"#{1,6} ", l):
                continue
            s = slug(l.lstrip("#"))
            k = seen.get(s, 0)
            out.add(s if k == 0 else f"{s}-{k}")
            seen[s] = k + 1
        cache[path] = out
    return cache[path]


def measurable(item):
    t = re.sub(r"(?:RFP|PRD|AG|BE|FE|SCH|NFR|FR|TC|H|U)-\d+(?:-\d+)?", "", item)
    t = re.sub(r"§\d+(?:\.\d+)*|\d+(?:\.\d+)*\s*(?:절|장)|\d{4}-\d{2}-\d{2}|\d{2}-\d{2}", "", t)
    t = re.sub(r"\b[CL]\d\+?|J\d(?:~J\d)?|P\d(?:~P\d)?", "", t)
    pats = [r"\d", r"k/n", r"%", r"pytest|ruff|pre-commit|check_schedule|make_report_pdf|\.py\b",
            r"[\w\-]+/[\w\-./]+", r"\.(?:md|py|json|jsonl|csv|toml|yaml|html|pdf)\b", r"/health|/chat|/ingest",
            r"[여한두세네다섯\d]+\s*(?:개|건|종)\s*이상"]
    hit = [p for p in pats if re.search(p, t)]
    return bool(hit), hit


def main():
    pieces, tickets = load_docs()
    today = datetime.date.today().isoformat()
    res = {a: {"chars": 0, "unres": 0, "honest": 0, "deferred": 0, "pending": 0, "dod_total": 0, "dod_meas": 0,
               "conflicts": 0, "broken": 0, "files": set()} for a in AREAS}
    unres_hits, deferred_hits = [], []
    for path, area, start, lines in pieces:
        r = res[area]
        r["files"].add(path)
        for n, l in enumerate(lines, start):
            r["chars"] += len(l)
            for k in UNRESOLVED:
                c = l.count(k)
                if c:
                    r["unres"] += c
                    unres_hits.append((area, path, n, k))
            for k in HONEST:
                r["honest"] += l.count(k)
            for k in DEFERRED:
                c = l.count(k)
                if c:
                    r["deferred"] += c
                    deferred_hits.append((area, path, n, k))

    # M2 결정 현황
    pending, dec_rows = {}, 0
    for tid, t in sorted(tickets.items()):
        for n, l in enumerate(t["lines"], 1):
            m = re.match(r"^\| ((?:RFP|PRD|AG|BE|FE)-\d+-\d{2}) \|(.*)\|\s*$", l)
            if not m:
                continue
            cells = [c.strip() for c in m.group(2).split("|")]
            st = next((c for c in cells if c in ("대기", "완료")), None)
            if st:
                dec_rows += 1
            if st == "대기":
                pending[m.group(1)] = f"{t['path']}:{n}"
    sched = open("schedule.md", encoding="utf-8").read()
    sec2 = sched.split("### 먼저 답할 결정")[1].split("\n## ")[0] if "### 먼저 답할 결정" in sched else ""
    listed = set(re.findall(r"^\| ((?:RFP|PRD|AG|BE|FE)-\d+-\d{2}) \|", sec2, re.M))
    mismatch = sorted(set(pending) ^ listed)
    for k in pending:
        res[TICKET_AREA.get(k.rsplit("-", 1)[0], "H")]["pending"] += 1
    res["H"]["pending"] += len(mismatch)

    # M3 완료 조건
    unmeasurable = []
    for tid, t in sorted(tickets.items()):
        if t["meta"].get("status") == "dropped":
            continue
        area = TICKET_AREA.get(tid, "H")
        inside = False
        for n, l in enumerate(t["lines"], 1):
            if l.startswith("## "):
                inside = l.startswith("## 2. 완료 조건")
                continue
            if inside and re.match(r"\s*- \[[ x]\] ", l):
                ok, _ = measurable(l)
                res[area]["dod_total"] += 1
                res[area]["dod_meas"] += ok
                if not ok:
                    unmeasurable.append({"ticket": tid, "loc": f"{t['path']}:{n}", "text": l.strip()[:90]})

    # M4 불변식
    conflicts, history, found = [], [], {}
    def note(inv, path, n, line, val, ok, area):
        rec = {"inv": inv, "loc": f"{path}:{n}", "value": val, "area": area, "text": line.strip()[:110]}
        found.setdefault(inv, []).append(rec)
        if ok:
            return
        if HISTORY.search(line):
            history.append(rec)
        else:
            conflicts.append(rec)
    judge_vals, agent_vals = [], []
    for path, area, start, lines in pieces:
        if path == "schedule-changelog.md":
            continue
        fence = False
        for n, l in enumerate(lines, start):
            for m in re.finditer(r"(?:호출\s*(?:횟수\s*)?상한|호출당\s*최대|모델\s*호출[^\n]{0,6}최대)\D{0,10}?(\d+)\s*회", l):
                note("I1 호출 상한 8", path, n, l, m.group(1), m.group(1) == "8", area)
            for m in re.finditer(r"되돌림[^\n]{0,12}?(?:최대\s*)?(\d+)\s*회", l):
                note("I2 되돌림 2", path, n, l, m.group(1), m.group(1) == "2", area)
            for m in re.finditer(r"도구\s*(\d+)\s*개", l):
                v = m.group(1)
                ok = v == "6" or (v == "3" and re.search(r"검색|AG-02|AG-03|identify_drug|조회", l))
                note("I3 도구 6개", path, n, l, v, bool(ok), area)
            for m in re.finditer(r"`((?:identify|check|get|search|lookup|find|retrieve|fetch|query)_[a-z_]+)`", l):
                v = m.group(1)
                note("I3b 도구 이름", path, n, l, v, v in TOOLS, area)
            for m in re.finditer(r"(?<![\d.\-§])(\d+)\s*노드|노드\s*(?:는|가|를|구성은?)?\s*(\d+)\s*개", l):
                v = m.group(1) or m.group(2)
                note("I4 노드 6개", path, n, l, v, v == "6", area)
            if "노드" in l:
                for m in re.finditer(r"`([a-z_]+)`", l):
                    v = m.group(1)
                    if v in TOOLS or v in NODES:
                        continue
                    if re.search(rf"`{v}`\s*(?:노드|node)", l):
                        note("I4b 노드 이름", path, n, l, v, False, area)
            for m in re.finditer(r"(?:총\s*)?약\s*(\d{2,4})\s*문항", l):
                v = m.group(1)
                if "개발셋" in l and v != "150":
                    continue
                note("I5 문항 약 150", path, n, l, v, v == "150" or int(v) < 100, area)
            for m in re.finditer(r"안전\s*핵심\s*(?:문항\s*)?(\d+)", l):
                note("I5b 안전 핵심 40", path, n, l, m.group(1), m.group(1) == "40", area)
            for m in re.finditer(r"(\d+)\s*회\s*반복|반복\s*(\d+)\s*회|×\s*(\d+)\s*회", l):
                v = m.group(1) or m.group(2) or m.group(3)
                if "안전" in l or "pass" in l or "신뢰성" in l:
                    note("I5c 반복 3회", path, n, l, v, v == "3", area)
            for m in re.finditer(r"\bC(\d)(\+?)", l):
                v = f"C{m.group(1)}{m.group(2)}"
                if re.search(r"[A-Za-z]C\d|C\d{2}", l[max(0, m.start() - 1):m.end() + 1]):
                    continue
                note("I6 조건 이름", path, n, l, v, v in ("C0", "C1", "C1+", "C2", "C3", "C4"), area)
            for m in re.finditer(r"(?<![\d.\-§])(\d)\s*조건|조건\s*(\d)\s*개", l):
                v = m.group(1) or m.group(2)
                note("I6b 조건 4개", path, n, l, v, v == "4", area)
            for m in re.finditer(r"claude-sonnet-[\w.\-]+|Sonnet\s*(\d(?:\.\d)?)", l):
                v = m.group(0)
                ok = v.startswith("claude-sonnet-5-5") or m.group(1) in ("5.5",) or (m.group(1) is None and "5-5" in v)
                if m.group(1) == "5" or v.strip() == "Sonnet":
                    ok = True
                note("I7 judge 모델", path, n, l, v, ok, area)
            for m in re.finditer(r"\bgpt-[\w.\-]+", l):
                v = m.group(0).rstrip(".-")
                note("I8 에이전트 모델", path, n, l, v, v == "gpt-6-luna", area)
            for m in re.finditer(r"\$\s?(\d+(?:\.\d+)?)(?:\s*~\s*\$?(\d+(?:\.\d+)?))?", l):
                ctx = l[max(0, m.start() - 40):m.end() + 20]
                v = m.group(0).replace(" ", "")
                if re.search(r"judge|Sonnet|채점", ctx) and re.search(r"어림|추정|예상", l) and not re.search(r"보유|크레딧|입력|출력|만료|잔액|단가|/\s*100만", ctx):
                    judge_vals.append((v, path, n, l, area))
                if re.search(r"에이전트|본 측정", ctx) and re.search(r"어림|추정|예상|약\s*\$", l) and not re.search(r"보유|크레딧\s*\$|입력|출력|단가|judge|/\s*100만", ctx):
                    agent_vals.append((v, path, n, l, area))
            for m in re.finditer(r"\bFR-(\d+)", l):
                note("I11 FR 번호", path, n, l, m.group(1), 1 <= int(m.group(1)) <= 11, area)
            for m in re.finditer(r"(?:FR|기능 요구사항)\s*(\d+)\s*개", l):
                note("I11 FR 개수", path, n, l, m.group(1), m.group(1) == "11", area)
            for m in re.finditer(r"\bNFR-(\d+)", l):
                note("I12 NFR 번호", path, n, l, m.group(1), 1 <= int(m.group(1)) <= 10, area)
            for m in re.finditer(r"(?:NFR|비기능 요구사항)\s*(\d+)\s*개", l):
                note("I12 NFR 개수", path, n, l, m.group(1), m.group(1) == "10", area)
            for m in re.finditer(r"Biyak|Ppiyak|ppiyak|PPIYAK|Ppi-yak", l):
                note("I14 표시 이름", path, n, l, m.group(0), False, area)
            for m in re.finditer(r"(?:평가\s*)?지표\s*(\d+)\s*개|(?<![\d.\-§])(\d)\s*지표", l):
                v = m.group(1) or m.group(2)
                ok = v == "5" or (v == "3" and re.search(r"Ragas|나머지|세 지표", l))
                note("I16 지표 5개", path, n, l, v, bool(ok), area)
    # I9·I10: 값 종류가 둘 이상이면 소수 값 줄이 충돌
    for inv, vals in (("I9 judge 비용 어림", judge_vals), ("I10 에이전트 본 측정 비용 $4.5", agent_vals)):
        counts = {}
        for v, *_ in vals:
            counts[v] = counts.get(v, 0) + 1
        canon = "$4.5" if inv.startswith("I10") else (max(sorted(counts), key=lambda k: counts[k]) if counts else None)
        for v, path, n, l, area in vals:
            note(inv, path, n, l, v, v == canon, area)
        found.setdefault(inv + " 값 분포", []).append(counts)
    # I13 티켓 수
    live = {k: v for k, v in tickets.items() if v["meta"].get("status") != "dropped"}
    by_sch = {}
    for t in live.values():
        s = t["meta"].get("sch")
        a = by_sch.setdefault(s, {"done": 0, "total": 0, "필수": 0, "권장": 0, "확장": 0, "기타": 0})
        a["total"] += 1
        a["done"] += t["meta"].get("status") == "done"
        pr = t["meta"].get("priority", "")
        key = "확장" if "확장" in pr else ("권장" if "권장" in pr else ("필수" if "필수" in pr else "기타"))
        a[key] += 1
    slines = sched.split("\n")
    for n, l in enumerate(slines, 1):
        m = re.match(r"^\| (SCH-\d+) \| [^|]+\| (\d+)/(\d+) \|(.*)$", l)
        if m:
            a = by_sch.get(m.group(1), {})
            note("I13 SCH 완료/전체", "schedule.md", n, l, f"{m.group(2)}/{m.group(3)}",
                 [int(m.group(2)), int(m.group(3))] == [a.get("done"), a.get("total")], "H")
            mm = re.search(r"필수\s*(\d+)\s*/\s*권장\s*(\d+)(?:\s*/\s*확장\s*(\d+))?", m.group(4))
            if mm:
                s_ = sum(int(x) for x in mm.groups() if x)
                note("I13 SCH 우선순위 합", "schedule.md", n, l, f"합 {s_}/전체 {m.group(3)}", s_ == int(m.group(3)), "H")
                exp = [a.get("필수"), a.get("권장"), a.get("확장")]
                got = [int(x) if x else 0 for x in mm.groups()]
                note("I13 SCH 우선순위(티켓 priority)", "schedule.md", n, l, f"문서 {got} 티켓 {exp}", got == exp, "H")
        m = re.search(r"총\s*(\d+)개\s*\(RFP\s*(\d+)\s*/\s*PRD\s*(\d+)\s*/\s*AG\s*(\d+)\s*/\s*BE\s*(\d+)\s*/\s*FE\s*(\d+)\)", l)
        if m:
            real = [len(tickets)] + [sum(1 for k in tickets if k.startswith(p + "-")) for p in ("RFP", "PRD", "AG", "BE", "FE")]
            got = [int(x) for x in m.groups()]
            note("I13 티켓 총수 79", "schedule.md", n, l, f"문서 {got} 실제 {real}", got == real, "H")
    # I15 Recap
    rec = sched.split("## Recap")[1].split("\n## ")[0] if "## Recap" in sched else ""
    rows = {}
    order = []
    for l in rec.split("\n"):
        m = re.match(r"^\| (\d+) \| (.*)$", l)
        if m:
            rows[int(m.group(1))] = m.group(2)
            order.append(int(m.group(1)))
    seq_ok = order == list(range(1, len(order) + 1))
    found["I15 Recap 표 번호 순서"] = [{"order": order, "sequential": seq_ok}]
    if not seq_ok:
        rn = next(n for n, l in enumerate(slines, 1) if l.startswith("## Recap"))
        conflicts.append({"inv": "I15 Recap 번호 순서", "loc": f"schedule.md:{rn}", "value": str(order), "area": "H",
                          "text": "Recap 표 번호가 1부터 차례가 아님"})
    undecidable = []
    for path, area, start, lines in pieces:
        if path == "schedule-changelog.md":
            continue
        for n, l in enumerate(lines, start):
            for m in re.finditer(r"Recap\s*(\d+)\s*번", l):
                k = int(m.group(1))
                ids = set(re.findall(r"(?:RFP|PRD|AG|BE|FE)-\d+", l))
                if k not in rows:
                    note("I15 Recap N번 참조", path, n, l, f"{k}번(행 없음)", False, area)
                elif not ids:
                    undecidable.append(f"{path}:{n}")
                else:
                    ok = any(i in rows[k] for i in ids)
                    note("I15 Recap N번 참조", path, n, l, f"{k}번", ok, area)
    # I17 대기 N건 문구
    npend = len(pending)
    for path, area, start, lines in pieces:
        if path == "schedule-changelog.md":
            continue
        for n, l in enumerate(lines, start):
            for m in re.finditer(r"대기(?:\s*중인)?\s*(?:결정\s*)?(?:은\s*)?\*{0,2}(\d+)\s*건", l):
                v = int(m.group(1))
                if path.startswith("tickets/") and "이 티켓에서 사용자가 답할 것" in l:
                    tid = os.path.basename(path)[:-3]
                    exp = sum(1 for k in pending if k.startswith(tid + "-"))
                elif path.startswith("tickets/"):
                    exp = sum(1 for k in pending if k.startswith(os.path.basename(path)[:-3] + "-"))
                    if "Top 5" in l or "schedule" in l:
                        exp = npend
                else:
                    exp = npend
                note("I17 대기 N건 문구", path, n, l, f"{v}건(실제 {exp})", v == exp, area)
    # I18 날짜 문구
    for path, area, start, lines in pieces:
        if path == "schedule-changelog.md":
            continue
        for n, l in enumerate(lines, start):
            m = re.search(r"(?:마지막 갱신|작성 상태|^\*\*기준일\*\*|^- 기준일|^> 기준일|기준일:)[^\n]{0,40}?(\d{4}-\d{2}-\d{2})", l)
            if m and n < start + 40:
                last = git_date(path)
                if last:
                    note("I18 날짜 문구", path, n, l, f"{m.group(1)}(최근 변경 {last})", m.group(1) >= last, area)

    # M5 참조 무결성
    broken = []
    for path, area, start, lines in pieces:
        fence = False
        base = os.path.dirname(path)
        for n, l in enumerate(lines, start):
            if l.lstrip().startswith("```"):
                fence = not fence
                continue
            if fence:
                continue
            for m in re.finditer(r"\]\((<[^>]+>|[^)\s]+)\)", re.sub(r"`[^`]*`", "", l)):
                tgt = m.group(1).strip("<>")
                if re.match(r"https?:|mailto:", tgt):
                    continue
                p, _, a = tgt.partition("#")
                full = os.path.normpath(os.path.join(base, p)) if p else path
                if p and not os.path.exists(full):
                    broken.append({"loc": f"{path}:{n}", "target": tgt, "why": "경로 없음", "area": area})
                    continue
                if a and full.endswith(".md"):
                    from urllib.parse import unquote
                    if unquote(a) not in anchors_of(full):
                        broken.append({"loc": f"{path}:{n}", "target": tgt, "why": "앵커 없음", "area": area})
    for c in conflicts:
        res[c["area"]]["conflicts"] += 1
    for b in broken:
        res[b["area"]]["broken"] += 1
    cs = subprocess.run([sys.executable, "scripts/check_schedule.py"], capture_output=True, text=True)
    cs_out = cs.stdout.strip().split("\n")
    cs_warn = sum(1 for l in cs_out if l.startswith("경고:"))

    # 점수
    raw = {}
    for a in AREAS:
        r = res[a]
        ch = max(r["chars"], 1)
        raw[a] = {
            "m1": r["unres"] / ch * 1000,
            "m2": (r["pending"] + r["deferred"]) / ch * 10000,
            "m3": (r["dod_meas"] / r["dod_total"]) if r["dod_total"] else None,
            "m4": (r["conflicts"] + r["broken"]) / ch * 10000,
        }
    mx = {k: max(raw[a][k] for a in AREAS) for k in ("m1", "m2", "m4")}
    norm = lambda k, a: min(raw[a][k] / mx[k], 1.0) if mx[k] > 0 else 0.0
    score = {}
    for a in AREAS:
        m3 = raw[a]["m3"] if raw[a]["m3"] is not None else 1.0
        score[a] = 0.30 * norm("m1", a) + 0.25 * norm("m2", a) + 0.25 * (1 - m3) + 0.20 * norm("m4", a)
    total = sum(score[a] * WEIGHT[a] for a in AREAS)
    r05 = lambda x: round(round(x / 0.05) * 0.05, 2)

    out = {
        "def_version": DEF_VERSION,
        "areas": {a: {"name": AREA_NAME[a], "weight": WEIGHT[a], "files": len(res[a]["files"]), "chars": res[a]["chars"],
                      "unresolved": res[a]["unres"], "honest_marks": res[a]["honest"],
                      "m1_per_1k": round(raw[a]["m1"], 3), "pending_numbered": res[a]["pending"],
                      "deferred_marks": res[a]["deferred"], "m2_per_10k": round(raw[a]["m2"], 3),
                      "dod_total": res[a]["dod_total"], "dod_measurable": res[a]["dod_meas"],
                      "m3_ratio": None if raw[a]["m3"] is None else round(raw[a]["m3"], 3),
                      "conflicts": res[a]["conflicts"], "broken_refs": res[a]["broken"],
                      "m4_per_10k": round(raw[a]["m4"], 3),
                      "norm": {k: round(norm(k, a), 3) for k in ("m1", "m2", "m4")},
                      "score_raw": round(score[a], 4), "score": r05(score[a]),
                      "weighted": round(score[a] * WEIGHT[a], 4)} for a in AREAS},
        "total_raw": round(total, 4), "total": r05(total), "threshold_ref": 0.2,
        "over_threshold": [a for a in AREAS if r05(score[a]) > 0.2],
        "decisions": {"rows": dec_rows, "pending": pending, "schedule_listed": sorted(listed), "mismatch": mismatch},
        "conflicts": conflicts, "history_context": history, "broken_refs": broken,
        "recap_undecidable": undecidable, "unmeasurable_dod": unmeasurable,
        "value_distribution": {k: v for k, v in found.items() if "분포" in k or "순서" in k},
        "invariant_hits": {k: len(v) for k, v in sorted(found.items()) if "분포" not in k and "순서" not in k},
        "check_schedule": {"exit": cs.returncode, "warnings": cs_warn, "last": cs_out[-1] if cs_out else ""},
        "extra_assignment": sorted(k for k in tickets if k not in BRIEF_LISTED),
        "unresolved_hits_by_marker": {k: sum(1 for h in unres_hits if h[3] == k) for k in UNRESOLVED},
        "deferred_hits_by_marker": {k: sum(1 for h in deferred_hits if h[3] == k) for k in DEFERRED},
    }
    jpath = sys.argv[sys.argv.index("--json") + 1] if "--json" in sys.argv else f"mock/ambiguity/audit-{today}.json"
    os.makedirs(os.path.dirname(jpath), exist_ok=True)
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)

    print(f"모호도 측정 {DEF_VERSION} (결과 {jpath})")
    print("| 영역 | 가중 | 문서 | 글자 | M1/1k | 대기+보류/10k | 완료조건 측정가능 | 충돌+깨짐/10k | 점수 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for a in AREAS:
        o = out["areas"][a]
        m3 = "-" if o["m3_ratio"] is None else f"{o['dod_measurable']}/{o['dod_total']}"
        print(f"| {a} {AREA_NAME[a]} | {WEIGHT[a]:.2f} | {o['files']} | {o['chars']} | {o['m1_per_1k']:.2f} ({o['unresolved']}) | "
              f"{o['m2_per_10k']:.2f} ({o['pending_numbered']}+{o['deferred_marks']}) | {m3} | "
              f"{o['m4_per_10k']:.2f} ({o['conflicts']}+{o['broken_refs']}) | {o['score']:.2f} |")
    print(f"전체(가중) {out['total']:.2f} (원값 {out['total_raw']}), 참조선 0.2 초과: {out['over_threshold']}")
    print(f"수치 충돌 {len(conflicts)}건, 이력 문맥 제외 {len(history)}건, 깨진 참조 {len(broken)}건, "
          f"대기 결정 {len(pending)}건(불일치 {len(mismatch)}), check_schedule 종료 {cs.returncode}·경고 {cs_warn}")
    by = {}
    for c in conflicts:
        by[c["inv"]] = by.get(c["inv"], 0) + 1
    for k in sorted(by):
        print(f"  {k}: {by[k]}")


if __name__ == "__main__":
    main()
