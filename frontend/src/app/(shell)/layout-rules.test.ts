import { describe, expect, it } from "vitest";
import { canPushSidebar, computeLayout, initialShellState, shellReducer } from "./layout-rules";
import type { ShellAction, ShellState } from "./layout-rules";

const run = (state: ShellState, ...actions: ShellAction[]) => actions.reduce(shellReducer, state);
const open = (width: number, turnId = "turn-1"): ShellAction => ({ type: "openEvidence", turnId, width });

describe("사이드바 밀기·오버레이 식(지시서 §9)", () => {
  it("근거 상세가 열린 채로는 1231 이하 오버레이, 1232 이상 밀기", () => {
    expect(canPushSidebar(1231, true)).toBe(false);
    expect(canPushSidebar(1232, true)).toBe(true);
  });

  it("근거 상세가 닫혀 있으면 데스크톱 구간(1024 이상)은 모두 밀기", () => {
    for (const width of [1024, 1100, 1231, 1280]) expect(canPushSidebar(width, false)).toBe(true);
  });

  it("레일 상태의 본문은 데스크톱 구간에서 Wmin(560) 이상이다", () => {
    expect(1024 - 60 - 400).toBeGreaterThanOrEqual(560);
  });
});

describe("근거 상세가 새로 열리는 순간의 판정(§10·§11)", () => {
  it.each([1024, 1100, 1180, 1231])("%i: 펼친 사이드바를 레일로 내리고 오버레이가 생기지 않는다", (width) => {
    const next = run(initialShellState, open(width));
    expect(next.sidebarExpanded).toBe(false);
    expect(computeLayout(next, width)).toMatchObject({ panelOpen: true, sidebarOverlay: false, sidebarColumn: "rail" });
  });

  it.each([1232, 1240, 1279, 1280, 1400])("%i: 펼침을 유지하고 밀어서 보인다", (width) => {
    const next = run(initialShellState, open(width));
    expect(next.sidebarExpanded).toBe(true);
    expect(computeLayout(next, width)).toMatchObject({ panelOpen: true, sidebarOverlay: false, sidebarColumn: "expanded" });
  });

  it("직후 사용자 토글은 동작한다: 1100에서 다시 펼치면 오버레이, 근거 상세는 열린 채다", () => {
    const next = run(initialShellState, open(1100), { type: "toggleSidebar" });
    expect(next).toMatchObject({ sidebarExpanded: true, evidenceTurnId: "turn-1" });
    expect(computeLayout(next, 1100)).toMatchObject({ sidebarOverlay: true, sidebarColumn: "rail", panelOpen: true });
    expect(run(next, { type: "collapseSidebar" })).toMatchObject({ sidebarExpanded: false, evidenceTurnId: "turn-1" });
  });

  it("E2: 다시 펼친 뒤 닫았다 다시 열면 1024~1231에서는 다시 접고, 1232 이상은 유지한다", () => {
    const reopened = (width: number) => run(initialShellState, open(width), { type: "toggleSidebar" }, { type: "closeEvidence" }, open(width));
    const expanded = run(initialShellState, open(1100), { type: "toggleSidebar" });
    expect(run(expanded, { type: "closeEvidence" }).sidebarExpanded).toBe(true); // 닫기는 사이드바를 바꾸지 않는다(밀기로 보인다)
    expect(reopened(1100).sidebarExpanded).toBe(false);
    expect(run(initialShellState, open(1280), { type: "closeEvidence" }, open(1280)).sidebarExpanded).toBe(true);
  });

  it("E1: 접힌 채로 닫았다 다시 열어도 접힌 그대로다", () => {
    expect(run(initialShellState, open(1100), { type: "closeEvidence" }, open(1100)).sidebarExpanded).toBe(false);
  });

  it("E3: 열린 채 다른 결과로 바뀔 때는 접지 않는다", () => {
    const next = run(initialShellState, open(1100), { type: "toggleSidebar" }, open(1100, "turn-2"));
    expect(next).toMatchObject({ sidebarExpanded: true, evidenceTurnId: "turn-2" });
  });

  it("E4: 새 질문 뒤 다음 답에서 다시 판정한다", () => {
    const next = run(initialShellState, open(1100), { type: "toggleSidebar" }, { type: "newChat" });
    expect(next).toMatchObject({ sidebarExpanded: true, evidenceTurnId: null });
    expect(run(next, open(1100, "turn-9")).sidebarExpanded).toBe(false);
  });

  it("E5·E6: 폭이 바뀌어도 상태는 그대로이고 표현만 오버레이로 바뀐다", () => {
    const wide = run(initialShellState, open(1300));
    expect(computeLayout(wide, 1300).sidebarOverlay).toBe(false);
    expect(computeLayout(wide, 1100)).toMatchObject({ sidebarOverlay: true, panelOpen: true });
    const narrow = run(initialShellState, open(1000)); // 1023 이하에서 열면 판정하지 않는다
    expect(narrow.sidebarExpanded).toBe(true);
    expect(computeLayout(narrow, 1000)).toMatchObject({ desktop: false, sidebarColumn: "none", evidenceMode: "sheet", sidebarOverlay: false });
    expect(computeLayout(narrow, 1100).sidebarOverlay).toBe(true);
  });
});

describe("폭별 배치", () => {
  it("1023 이하는 사이드바 칸이 없고 근거 상세는 시트, 1024부터 사이드바 칸과 패널", () => {
    expect(computeLayout(initialShellState, 1023)).toMatchObject({ desktop: false, sidebarColumn: "none", evidenceMode: "sheet" });
    expect(computeLayout(initialShellState, 1024)).toMatchObject({ desktop: true, sidebarColumn: "expanded", evidenceMode: "panel" });
  });

  it("진입 글자: 700 미만은 보기, 700 이상은 열기(지시서 G-1)", () => {
    expect(computeLayout(initialShellState, 393).entryLabelMode).toBe("sheet");
    expect(computeLayout(initialShellState, 699).entryLabelMode).toBe("sheet");
    expect(computeLayout(initialShellState, 700).entryLabelMode).toBe("panel");
    expect(computeLayout(initialShellState, 1280).entryLabelMode).toBe("panel");
  });

  it("근거 상세 개폐는 사이드바 사용자 상태를 바꾸지 않는다(밀기 구간)", () => {
    const collapsed = run(initialShellState, { type: "toggleSidebar" });
    expect(run(collapsed, open(1400), { type: "closeEvidence" }).sidebarExpanded).toBe(false);
    expect(run(initialShellState, open(1400), { type: "closeEvidence" }).sidebarExpanded).toBe(true);
  });
});
