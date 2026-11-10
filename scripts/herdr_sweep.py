"""herdr 작업 pane 정리 도구(2026-11-10). 사용: python3 scripts/herdr_sweep.py [--close] [--wait]

작업이 끝난 pane이 쌓이는 문제를 막는다. 메인(P2-Medi-Main)을 뺀 모든 pane을 보고 상태를 분류한다.
  working     작업 중(건드리지 않는다)
  blocked     승인 창 대기(사용자 처리 필요, pane ID와 상태만 알림)
  draft       idle인데 입력창에 사용자가 쓴 글이 있다(메인 요청으로 읽어야 하고, 닫지 않는다)
  no-report   idle인데 보고 파일 data/mock/briefs/reports/<pane 이름>.md 가 없다(메인이 파일로 저장하라고 시킨다)
  done        idle, 입력창 비어 있음, 보고 파일 있음 -> 닫을 수 있다(--close를 주면 닫는다)
--wait: working이 아닌 pane이 하나라도 생길 때까지 기다린 뒤 분류를 출력한다(백그라운드 알림용).
읽기 전용 명령과 `herdr pane close`만 쓴다. 비밀 파일은 열지 않는다.
"""
import json
import pathlib
import subprocess
import sys
import time

MAIN = "P2-Medi-Main"
REPORTS = pathlib.Path("data/mock/briefs/reports")


def run(*args):
    return subprocess.run(["herdr", *args], capture_output=True, text=True).stdout


def panes():
    data = json.loads(run("pane", "list"))
    return [p for p in data["result"]["panes"] if p.get("label") != MAIN]


def last_input_line(label):
    out = run("agent", "read", label, "--source", "recent-unwrapped", "--lines", "12")
    lines = [ln for ln in out.splitlines() if ln.strip().startswith("❯")]
    return lines[-1].strip()[1:].strip() if lines else ""


def classify(p):
    st = p.get("agent_status")
    label = p.get("label") or ""
    if st == "working":
        return "working", ""
    if st == "blocked":
        return "blocked", ""
    draft = last_input_line(label)
    if draft:
        return "draft", draft
    if not any(REPORTS.glob(f"{label}*.md")):
        return "no-report", ""
    return "done", ""


def main():
    close = "--close" in sys.argv
    if "--wait" in sys.argv:
        while True:
            ps = panes()
            if not ps or any(p.get("agent_status") != "working" for p in ps):
                break
            time.sleep(20)
    rows = []
    for p in panes():
        kind, note = classify(p)
        rows.append((kind, p["pane_id"], p.get("label"), note))
    for kind, pid, label, note in rows:
        print(f"{kind:10} {pid:8} {label}" + (f"  입력창: {note}" if note else ""))
        if close and kind == "done":
            run("pane", "close", pid)
            print(f"  -> 닫음 {pid}")
    if not rows:
        print("열린 작업 pane 없음")


if __name__ == "__main__":
    main()
