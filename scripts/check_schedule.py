"""schedule.md·schedule-done.md와 tickets/ 일관성, Top 5 최신 여부를 점검한다. 사용: python3 scripts/check_schedule.py
점검: 티켓 파일 <-> schedule 행(SCH·제목·체크·링크), 선행 관계(존재·순환·나중 SCH), Index·앵커, Top 5 트랙 4표(트랙당 5행 이하, 접두어·미완·SCH, 진행 병렬·부분 병렬·직렬과 선행 관계),
Recap·사용자 결정 큐 섹션, 마지막 갱신일, (RFP-35-06) SCH 우선순위 합·Recap 번호 차례·본문의 낡은 "대기 N건". 문제가 있으면 목록을 출력하고 종료 코드 1을 돌려준다. 코드는 읽기만 한다.
"""
import collections
import datetime
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
DIRS = {"AG": "agent", "BE": "backend", "FE": "frontend", "RFP": "doc", "PRD": "doc"}
ORDER = {"SCH-00": 0, "SCH-01": 1, "SCH-02": 2, "SCH-03": 3}
errors, warns = [], []


def slug(h):
    h = re.sub(r"[^\w\- ]", "", h.strip().lower())
    return h.replace(" ", "-")


tick = {}
for d in sorted(set(DIRS.values())):
    for f in sorted(os.listdir(f"tickets/{d}")):
        if not f.endswith(".md"):
            continue
        text = open(f"tickets/{d}/{f}", encoding="utf-8").read()
        fm = re.match(r"---\n(.*?)\n---", text, re.S).group(1)
        meta = dict(re.findall(r"^(\w+):\s*(.*)$", fm, re.M))
        m = re.search(r"^- 선행:\s*([^(\n]*)", text, re.M)
        meta["pre"] = re.findall(r"(?:RFP|PRD|AG|BE|FE)-\d+", m.group(1)) if m else []
        meta["text"], meta["path"] = text, f"tickets/{d}/{f}"
        tick[meta["id"]] = meta

s = open("schedule.md", encoding="utf-8").read()
if not os.path.exists("schedule-done.md"):
    errors.append("schedule-done.md 없음(완료된 티켓 행과 결정 기록은 이 파일에서 관리)")
    dn = ""
else:
    dn = open("schedule-done.md", encoding="utf-8").read()
sched, cur = {}, None
# 완료([x]) 행은 schedule-done.md에, 미완 행은 schedule.md에 둔다. 두 파일을 합쳐 티켓과 대조한다.
for src, text in (("schedule.md", s), ("schedule-done.md", dn)):
    cur = None
    for line in text.split("\n"):
        m = re.match(r"## (SCH-\d+)", line)
        if m:
            cur = m.group(1)
        elif line.startswith("## ") and not line.startswith("## SCH"):
            cur = None
        r = re.match(r"^\| `\[(.)\]` \| `([A-Z]+-\d+)` \| \[(.*?)\]\((.*?)\) \|", line)
        if r and cur:
            if src == "schedule.md" and r.group(1) == "x":
                errors.append(f"{r.group(2)}: 완료([x]) 행은 schedule-done.md로 옮겨야 함")
            if src == "schedule-done.md" and r.group(1) != "x":
                errors.append(f"{r.group(2)}: 미완 행이 schedule-done.md에 있음(schedule.md로 옮길 것)")
            sched[r.group(2)] = (cur, r.group(1), r.group(3), r.group(4))

for i in sorted(set(tick) - set(sched)):
    errors.append(f"{i}: 티켓은 있는데 schedule.md 표에 없음")
for i in sorted(set(sched) - set(tick)):
    errors.append(f"{i}: schedule.md에만 있음")
for i, m in tick.items():
    if i not in sched:
        continue
    sc, chk, title, link = sched[i]
    if m["sch"] != sc:
        errors.append(f"{i}: SCH 불일치 티켓={m['sch']} 표={sc}")
    if m["title"].strip() != title.strip():
        errors.append(f"{i}: 제목 불일치")
    if (chk == "x") != (m["status"] == "done"):
        errors.append(f"{i}: 완료 체크 불일치 status={m['status']} 표={chk}")
    if not os.path.exists(link):
        errors.append(f"{i}: 링크 없음 {link}")
    for p in m["pre"]:
        if p not in tick:
            errors.append(f"{i}: 선행 {p} 없음")
        elif ORDER[tick[p]["sch"]] > ORDER[m["sch"]]:
            errors.append(f"{i}({m['sch']}): 나중 SCH의 {p}({tick[p]['sch']})를 선행으로 둠")

g = {i: m["pre"] for i, m in tick.items()}


def cyc(n, stack):
    if n in stack:
        return stack[stack.index(n):] + [n]
    for p in g.get(n, []):
        r = cyc(p, stack + [n]) if p in g else None
        if r:
            return r
    return None


for i in g:
    r = cyc(i, [])
    if r:
        errors.append("선행 순환: " + " -> ".join(r))
        break

for i, m in tick.items():
    t = m["text"]
    if "## Index" not in t:
        errors.append(f"{i}: Index 없음")
        continue
    idx = t.split("## Index")[1].split("\n## ")[0]
    heads = [l for l in t.split("\n") if re.match(r"#{2,3} ", l) and not l.startswith("## Index")]
    miss = [l for l in heads if "(#" + slug(l.lstrip("#")) + ")" not in idx]
    if miss:
        errors.append(f"{i}: Index 누락 {miss[:2]}")
    n2 = n3 = 0
    fence = False
    for l in t.split("\n"):
        if l.startswith("```"):
            fence = not fence
        mm = None if fence else re.match(r"(#{2,3}) (.*)$", l)
        if not mm or mm.group(2) == "Index":
            continue
        if len(mm.group(1)) == 2:
            n2 += 1
            n3 = 0
            if not mm.group(2).startswith(f"{n2}. "):
                errors.append(f"{i}: '## {mm.group(2)}'는 '## {n2}. ' 번호로 시작해야 함")
        else:
            n3 += 1
            if not mm.group(2).startswith(f"{n2}.{n3} "):
                errors.append(f"{i}: '### {mm.group(2)}'는 '### {n2}.{n3} ' 번호로 시작해야 함")
    anchors = {slug(l.lstrip("#")) for l in t.split("\n") if l.startswith("#")}
    bad = [a for a in re.findall(r"\]\(#([^)]+)\)", t) if a not in anchors]
    if bad:
        errors.append(f"{i}: 깨진 앵커 {bad[:2]}")

# Top 5: 트랙 4표(RFP-30-05 A). 절 제목·앵커는 그대로 두고 그 안의 "### 트랙" 표를 읽는다.
TRACKS = {"Agent": ("AG",), "BackEnd": ("BE",), "FrontEnd": ("FE",), "Docs": ("RFP", "PRD")}
PROG = ("병렬", "부분 병렬", "직렬")
sec = s.split("## 지금 해야 할 일 (Top 5)")[1].split("\n## ")[0] if "## 지금 해야 할 일 (Top 5)" in s else ""
tsec = {}
for blk in re.split(r"^### ", sec, flags=re.M)[1:]:
    name = blk.split("\n", 1)[0].strip()
    if name in TRACKS:
        tsec[name] = blk
for name in TRACKS:
    if name not in tsec:
        errors.append(f"Top 5: '### {name}' 트랙 표 없음")
# 행: 완료 | SCH | Label | Title | 진행 | 선행 | 지금 할 수 있는 것 | ⛔ | 완료일
ROW = re.compile(r"^\| `\[.\]` \| (SCH-\d+) \| `([A-Z]+-\d+)` \|(.*)\|\s*$", re.M)
top, rows = [], []
for name, blk in tsec.items():
    rs = ROW.findall(blk)
    if len(rs) > 5:
        errors.append(f"Top 5 {name}: 행 수 {len(rs)}개(트랙당 최대 5행)")
    for sc, i, rest in rs:
        cells = [c.strip() for c in rest.split("|")]
        if len(cells) != 6:
            errors.append(f"Top 5 {name} {i}: 열 수가 맞지 않음(완료·SCH·Label·Title·진행·선행·지금 할 수 있는 것·⛔·완료일)")
            continue
        top.append((sc, i))
        rows.append((name, i, cells[1], cells[3], cells[4]))
        if not i.startswith(tuple(p + "-" for p in TRACKS[name])):
            errors.append(f"Top 5 {name}: {i}는 이 트랙의 접두어({'·'.join(TRACKS[name])})가 아님")
ids = [i for _, i in top]
for i, n in collections.Counter(ids).items():
    if n > 1:
        errors.append(f"Top 5: {i}가 트랙 표에 {n}번 있음")
for sc, i in top:
    m = tick.get(i)
    if not m:
        errors.append(f"Top 5: {i} 티켓 없음")
        continue
    if m["status"] in ("done", "dropped"):
        errors.append(f"Top 5: {i}는 {m['status']}라 목록에 있으면 안 됨")
    if m["sch"] != sc:
        errors.append(f"Top 5: {i} SCH 표기 불일치")
for name, i, prog, now, _ in rows:
    if prog not in PROG:
        errors.append(f"Top 5 {name} {i}: 진행 '{prog}'는 {'·'.join(PROG)} 중 하나여야 함")
        continue
    undone = [p for p in tick.get(i, {}).get("pre", []) if p in tick and tick[p]["status"] != "done"]
    if prog == "병렬":
        for p in undone:
            if p not in ids:
                errors.append(f"Top 5 {name} {i}: 병렬인데 선행 {p}가 미완이고 트랙 표에도 없음(부분 병렬·직렬로)")
    elif prog == "직렬":
        if not undone:
            errors.append(f"Top 5 {name} {i}: 직렬인데 선행이 모두 done(병렬로)")
        for p in undone:
            if p not in ids:
                warns.append(f"Top 5 {name} {i}: 직렬로 기다리는 선행 {p}가 트랙 표에 없음(진행하는 곳이 없음)")
    elif not now or now == "-":
        errors.append(f"Top 5 {name} {i}: 부분 병렬인데 '지금 할 수 있는 것'이 비어 있음")
# Top 5에 들어가야 할 후보 경고: 가장 앞선 SCH의 미완 티켓 중 선행이 모두 done인 필수 티켓이 Top 5 밖에 있는지
ready = [i for i, m in tick.items() if m["status"] in ("todo", "doing") and m["priority"] == "필수" and all(tick[p]["status"] == "done" for p in m["pre"] if p in tick)]
lowest = min((ORDER[tick[i]["sch"]] for i in ready), default=None)
out = [i for i in ready if ORDER[tick[i]["sch"]] == lowest and i not in ids]
if out and len(top) == 5 and not any(ORDER[sc] > lowest for sc, _ in top if False):
    warns.append("가장 앞선 SCH의 착수 가능 필수 티켓 중 Top 5 밖: " + ", ".join(sorted(out)) + " (의도한 것인지 선정 근거에 적혀 있는지 확인)")

# 결정 번호: 티켓 "결정 현황" 표(원본) <-> schedule.md "먼저 답할 결정" 표 <-> Top 5 ⛔ 칸
dec = {}
for i, m_ in tick.items():
    for row in re.findall(r"^\| ((?:RFP|PRD|AG|BE|FE)-\d+-\d{2}) \|(.*)\|\s*$", m_["text"], re.M):
        cells = [c.strip() for c in row[1].split("|")]
        status = next((c for c in cells if c in ("대기", "완료")), None)
        if not status:
            continue
        dec[row[0]] = status
        if not row[0].startswith(i + "-"):
            errors.append(f"{row[0]}: 번호의 티켓 부분이 표가 있는 티켓({i})과 다름")
pending = {k for k, v in dec.items() if v == "대기"}
sec2 = s.split("### 먼저 답할 결정")[1].split("\n## ")[0] if "### 먼저 답할 결정" in s else ""
listed = set(re.findall(r"^\| ((?:RFP|PRD|AG|BE|FE)-\d+-\d{2}) \|", sec2, re.M))
# "먼저 답할 결정" 표의 읽을 곳 열: 모든 행에 링크가 있어야 한다
hdr = re.search(r"^\| 번호 \|(.*)$", sec2, re.M)
if not hdr or "읽을 곳" not in hdr.group(0):
    errors.append("'먼저 답할 결정' 표에 '읽을 곳' 열이 없음")
else:
    for row in re.findall(r"^\| ((?:RFP|PRD|AG|BE|FE)-\d+-\d{2}) \|(.*)$", sec2, re.M):
        if "](" not in row[1]:
            errors.append(f"{row[0]}: '읽을 곳'에 링크가 없음")
for k in sorted(pending - listed):
    errors.append(f"{k}: 티켓에서 대기인데 schedule.md '먼저 답할 결정' 표에 없음")
for k in sorted(listed - pending):
    errors.append(f"{k}: schedule.md '먼저 답할 결정' 표에 있는데 티켓에서 대기가 아님")
for i, m_ in tick.items():
    if m_["status"] == "done" and any(k.startswith(i + "-") for k in pending):
        errors.append(f"{i}: 대기 중인 결정이 있는데 done")
# 카드: 대기 결정이 있거나 Top 5에 오른 티켓은 제목 아래 카드가 있어야 한다(건수, 대기 번호, schedule.md로 돌아가는 링크)
for i, m_ in tick.items():
    mine = sorted(k for k in pending if k.startswith(i + "-"))
    if not mine and i not in ids:
        continue
    head = m_["text"].split("## Index")[0]
    mm = re.search(r"이 티켓에서 사용자가 답할 것 \(대기 (\d+)건\)", head)
    if not mm:
        errors.append(f"{i}: 제목 아래 '답할 것' 카드가 없음")
        continue
    if int(mm.group(1)) != len(mine):
        errors.append(f"{i}: 카드의 대기 {mm.group(1)}건 != 실제 {len(mine)}건")
    if "schedule.md#지금-해야-할-일-top-5" not in head:
        errors.append(f"{i}: 카드에 schedule.md Top 5로 돌아가는 링크가 없음")
    for k in mine:
        if k not in head:
            errors.append(f"{i}: 카드에 {k}가 없음")

def expand(cell):
    out = set()
    for pre, nums in re.findall(r"((?:RFP|PRD|AG|BE|FE)-\d+)-(\d{2}(?:·\d{2})*)", cell):
        out |= {f"{pre}-{n}" for n in nums.split("·")}
    return out
for _, i, _, _, cell in rows:
    shown = expand(cell)
    mine = {k for k in pending if k.startswith(i + "-")}
    if not mine <= shown:
        errors.append(f"Top 5 {i}: 대기 결정 {sorted(mine - shown)}이 ⛔ 칸에 없음")
    if not shown <= pending:
        errors.append(f"Top 5 {i}: ⛔ 칸의 {sorted(shown - pending)}는 대기 중인 결정이 아님")
m = re.search(r"대기 중인 결정 (\d+)건", s)
if m and int(m.group(1)) != len(pending):
    errors.append(f"'대기 중인 결정 {m.group(1)}건' != 실제 {len(pending)}건")
m = re.search(r"\*\*대기\*\*: 아래 \"먼저 답할 결정\" (\d+)건", s)
if m and int(m.group(1)) != len(pending):
    errors.append(f"Recap 대기 {m.group(1)}건 != 실제 {len(pending)}건")

# RFP 1장 "한 줄 정의"와 CLAUDE.md 1장 첫 문장이 같은지(문구가 한쪽에만 반영되는 것을 막는다)
rfp_t = open("P2-doc/PJ2-RFP.md", encoding="utf-8").read()
cl_t = open("CLAUDE.md", encoding="utf-8").read()
m_r = re.search(r"^\| 한 줄 정의 \| (.*?) \|$", rfp_t, re.M)
m_c = re.search(r"## 1\. 프로젝트 한 줄 정의\n\n(.*?다)\. ", cl_t, re.S)
if not m_r or not m_c:
    errors.append("RFP 1장 또는 CLAUDE.md 1장에서 한 줄 정의를 찾지 못함")
elif m_r.group(1).strip() + "다" != m_c.group(1).strip():
    errors.append("RFP 1장 '한 줄 정의'와 CLAUDE.md 1장 첫 문장이 다름")

for h in ("## Recap", "### 먼저 답할 결정"):
    if h not in s:
        errors.append(f"schedule.md에 '{h}' 섹션 없음")
m = re.search(r"마지막 갱신: (\d{4}-\d{2}-\d{2})", s)
if not m:
    errors.append("마지막 갱신 날짜 없음")
elif m.group(1) != datetime.date.today().isoformat():
    warns.append(f"마지막 갱신 {m.group(1)}이 오늘({datetime.date.today()})이 아님. 오늘 바꾼 것이 없다면 무시")
if not os.path.exists("schedule-changelog.md"):
    errors.append("schedule-changelog.md 없음(변경 로그는 이 파일에서 관리)")
    logs = []
else:
    logs = re.findall(r"^- (\d{4}-\d{2}-\d{2}) ·", open("schedule-changelog.md", encoding="utf-8").read(), re.M)
if "](schedule-changelog.md)" not in s:
    errors.append("schedule.md에 schedule-changelog.md 링크 없음")
if logs and m and logs[0] != m.group(1):
    warns.append(f"변경 로그 최신({logs[0]})과 마지막 갱신({m.group(1)})이 다름")

cnt = collections.defaultdict(lambda: [0, 0])
for m_ in tick.values():
    if m_["status"] == "dropped":
        continue
    cnt[m_["sch"]][1] += 1
    cnt[m_["sch"]][0] += m_["status"] == "done"
prog = re.findall(r"^\| (SCH-\d+) \| [^|]+\| (\d+)/(\d+) \|", s, re.M)
for sc, a, b in prog:
    if [int(a), int(b)] != cnt[sc]:
        errors.append(f"진행 현황 {sc} {a}/{b} != 실제 {cnt[sc][0]}/{cnt[sc][1]}")
total = len(tick)
m = re.search(r"총 (\d+)개", s)
if m and int(m.group(1)) != total:
    errors.append(f"총 티켓 수 {m.group(1)} != 실제 {total}")

# (RFP-35-06) 세 검사: SCH 우선순위 합, Recap 번호 차례, 본문의 낡은 "대기 N건"
# ① SCH 표 "(필수 N / 권장 N / 확장 N)"과 티켓 priority. frontmatter에는 필수·권장만 있으므로 확장은 권장에 넣어 센다.
pri = collections.defaultdict(collections.Counter)
for m_ in tick.values():
    if m_["status"] != "dropped":
        pri[m_["sch"]][m_.get("priority", "").strip()] += 1
for line in s.split("\n"):
    r = re.match(r"^\| (SCH-\d+) \| [^|]+\| \d+/(\d+) \|(.*)$", line)
    mm = r and re.search(r"필수\s*(\d+)\s*/\s*권장\s*(\d+)(?:\s*/\s*확장\s*(\d+))?", r.group(3))
    if not mm:
        continue
    sc, tot = r.group(1), int(r.group(2))
    a, b, c = (int(x) if x else 0 for x in mm.groups())
    if a + b + c != tot:
        errors.append(f"진행 현황 {sc}: 우선순위 합 {a}+{b}+{c}={a + b + c} != 전체 {tot}")
    if a != pri[sc]["필수"] or b + c != pri[sc]["권장"]:
        errors.append(f"진행 현황 {sc}: 필수 {a}·권장(확장 포함) {b + c} != 티켓 priority 필수 {pri[sc]['필수']}·권장 {pri[sc]['권장']}")
# ② Recap 표의 번호는 겹치지 않고 오름차순이어야 한다("Recap N번"으로 찾아가므로).
#    끝난 행을 지워 번호가 비는 것은 허용한다(남은 행 번호를 바꾸면 기존 인용이 어긋난다, 2026-11-16)
rec = s.split("## Recap")[1].split("\n## ")[0] if "## Recap" in s else ""
nums = [int(x) for x in re.findall(r"^\| (\d+) \|", rec, re.M)]
if nums != sorted(set(nums)):
    errors.append(f"Recap 표 번호가 겹치거나 오름차순이 아님: {nums}")
# ③ 본문의 "대기 중인 결정 N건"·"대기 결정 N건"·"(대기 N건)". 카드와 위의 schedule.md 두 문구는 이미 검사하므로 뺀다.
#    가리키는 대상: 같은 줄에서 앞선 마지막 티켓 번호(없으면 그 티켓 자신), schedule.md는 전체(SCH 행은 그 SCH). "N건 →"는 이력이라 뺀다.
WAIT = re.compile(r"(대기 중인 결정|대기 결정|\(대기)\s*\*{0,2}(\d+)\s*건(?!\s*→)")
TID = re.compile(r"(?:RFP|PRD|AG|BE|FE)-\d+(?![\d-]\d)")
def owed(t):
    return sum(1 for k in pending if k.startswith(t + "-"))
done_spans = set()
for p_ in (r"대기 중인 결정 (\d+)건", r"\*\*대기\*\*: 아래 \"먼저 답할 결정\" (\d+)건"):
    m_ = re.search(p_, s)
    if m_:
        done_spans.add(m_.start(1))
for src, text, own in [("schedule.md", s, None)] + [(m_["path"], m_["text"], i) for i, m_ in sorted(tick.items())]:
    fence, off = False, 0
    for n, line in enumerate(text.split("\n"), 1):
        if line.startswith("```"):
            fence = not fence
        for m_ in ([] if fence else WAIT.finditer(line)):
            if "이 티켓에서 사용자가 답할 것" in line or (own is None and off + m_.start(2) in done_spans):
                continue
            if own is None:
                r = re.match(r"^\| (SCH-\d+) \|", line)
                exp = sum(1 for k in pending if tick.get(k.rsplit("-", 1)[0], {}).get("sch") == r.group(1)) if r else len(pending)
            else:
                # 전역 ids(Top 5 목록)를 덮어쓰지 않게 이름을 따로 둔다(요약 줄 'Top 5 ['RFP-3']' 버그 원인)
                tids = TID.findall(line[:m_.start()])
                exp = owed(tids[-1] if tids else own)
            if int(m_.group(2)) != exp:
                errors.append(f"{src}:{n}: '{m_.group(0)}' != 실제 대기 {exp}건")
        off += len(line) + 1

# 리포트(P2-doc/report/): md와 pdf는 한 쌍(CLAUDE.md 6장)
import pathlib
rep = pathlib.Path("P2-doc/report")
if rep.is_dir():
    for md in sorted(rep.glob("*.md")):
        pdf = md.with_suffix(".pdf")
        if not pdf.exists() or pdf.stat().st_size < 2000:
            errors.append(f"리포트 {md.name}: 같은 이름의 PDF가 없다(python3 scripts/make_report_pdf.py {md})")
    for pdf in sorted(rep.glob("*.pdf")):
        if not pdf.with_suffix(".md").exists():
            errors.append(f"리포트 {pdf.name}: 같은 이름의 md가 없다")

tracks = {name: [f"{i}({prog})" for n, i, prog, _, _ in rows if n == name] for name in TRACKS}
print(f"티켓 {total}개, schedule 행 {len(sched)}개, SCH별 {dict(cnt)}, 대기 결정 {len(pending)}건")
print("Top 5 트랙: " + " / ".join(f"{name} {v}" for name, v in tracks.items()))
for w in warns:
    print("경고:", w)
for e in errors:
    print("오류:", e)
print("통과" if not errors else f"실패({len(errors)}건)")
sys.exit(1 if errors else 0)
