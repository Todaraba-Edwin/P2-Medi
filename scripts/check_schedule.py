"""schedule.md·schedule-done.md와 tickets/ 일관성, Top 5 최신 여부를 점검한다. 사용: python3 scripts/check_schedule.py
점검: 티켓 파일 <-> schedule 행(SCH·제목·체크·링크), 선행 관계(존재·순환·나중 SCH), Index·앵커, Top 5(5개, 미완, 선행 충족 또는 Top 5 안),
Recap·사용자 결정 큐 섹션, 마지막 갱신일. 문제가 있으면 목록을 출력하고 종료 코드 1을 돌려준다. 코드는 읽기만 한다.
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

# Top 5
sec = s.split("## 지금 해야 할 일 (Top 5)")[1].split("\n## ")[0] if "## 지금 해야 할 일 (Top 5)" in s else ""
top = re.findall(r"^\| `\[.\]` \| (SCH-\d+) \| `([A-Z]+-\d+)` \|", sec, re.M)
if len(top) != 5:
    errors.append(f"Top 5 행 수가 {len(top)}개")
ids = [i for _, i in top]
for sc, i in top:
    m = tick.get(i)
    if not m:
        errors.append(f"Top 5: {i} 티켓 없음")
        continue
    if m["status"] in ("done", "dropped"):
        errors.append(f"Top 5: {i}는 {m['status']}라 목록에 있으면 안 됨")
    if m["sch"] != sc:
        errors.append(f"Top 5: {i} SCH 표기 불일치")
    for p in m["pre"]:
        if p in tick and tick[p]["status"] != "done" and p not in ids:
            errors.append(f"Top 5: {i}의 선행 {p}가 미완이고 Top 5에도 없음")
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
toprows = re.findall(r"^\| `\[.\]` \| SCH-\d+ \| `([A-Z]+-\d+)` \|.*\| ([^|]*) \| [^|]* \|$", sec, re.M)
for i, cell in toprows:
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

print(f"티켓 {total}개, schedule 행 {len(sched)}개, SCH별 {dict(cnt)}, Top 5 {ids}, 대기 결정 {len(pending)}건")
for w in warns:
    print("경고:", w)
for e in errors:
    print("오류:", e)
print("통과" if not errors else f"실패({len(errors)}건)")
sys.exit(1 if errors else 0)
