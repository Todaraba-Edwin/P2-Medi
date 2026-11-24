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

describe("창 크기 기준선 가로지르기(FE-17 U-18)", () => {
  // 기대값 갱신(2026-11-24, FE-17 U-18 추가 지시): 좁아질 때 근거 상세도 닫힌다(이전 기대 "근거 상세는 그대로"를 새 동작으로 바꿈)
  it("좁아지면(desktop false) 사이드바·드로어·근거 상세를 닫고, 넓어지면(desktop true) 사이드바를 펼친다", () => {
    const opened = run(initialShellState, { type: "openDrawer" }, open(1280));
    expect(run(opened, { type: "viewportCrossed", desktop: false })).toMatchObject({ sidebarExpanded: false, drawerOpen: false, evidenceTurnId: null });
    const collapsed = run(initialShellState, { type: "toggleSidebar" }, { type: "openDrawer" });
    expect(run(collapsed, { type: "viewportCrossed", desktop: true })).toMatchObject({ sidebarExpanded: true, drawerOpen: false });
  });

  it("근거 상세(U-18 추가): 넓은→좁은 가로지름에서만 닫고, 다시 넓어져도 열지 않으며, 좁은 폭에서 직접 연 것은 넓어져도 유지한다", () => {
    // 넓은 폭에서 열림 → 좁아짐: 닫힘 → 다시 넓어짐: 닫힌 채
    const narrowed = run(initialShellState, open(1280), { type: "viewportCrossed", desktop: false });
    expect(narrowed.evidenceTurnId).toBeNull();
    expect(run(narrowed, { type: "viewportCrossed", desktop: true }).evidenceTurnId).toBeNull();
    // 좁은 폭에서 사용자가 직접 연다(시트) → 넓어짐: 열린 채(패널로 바뀜)
    const manual = run(narrowed, open(900));
    expect(manual.evidenceTurnId).toBe("turn-1");
    const widened = run(manual, { type: "viewportCrossed", desktop: true });
    expect(widened.evidenceTurnId).toBe("turn-1");
    expect(computeLayout(widened, 1280).panelOpen).toBe(true);
    // 같은 구간 안의 폭 변화는 액션이 없으므로 상태 그대로(배치만 바뀜)
    expect(computeLayout(manual, 700).evidenceMode).toBe("sheet");
    expect(manual.evidenceTurnId).toBe("turn-1");
    // 닫기는 사용자가 언제든 할 수 있다
    expect(run(manual, { type: "closeEvidence" }).evidenceTurnId).toBeNull();
  });

  it("같은 구간 안의 사용자 토글은 가로지르기가 없으면 그대로다(폭만 바뀌면 배치 표현만 바뀐다)", () => {
    const collapsed = run(initialShellState, { type: "toggleSidebar" });
    for (const width of [1024, 1100, 1280, 1600]) expect(computeLayout(collapsed, width).sidebarColumn).toBe("rail");
  });
});

describe("근거 상세가 열린 채 창이 줄 때 사이드바 자동 접힘(FE-17 U-18 추가 지시 2)", () => {
  const resized = (from: number, to: number): ShellAction => ({ type: "viewportResized", from, to });
  /** 1280에서 근거 상세를 열면 밀어서 펼친 상태다(사이드바 펼침 + 패널) */
  const wideOpen = () => run(initialShellState, open(1280));

  it("경계: 1232(밀기) → 1231(오버레이)로 줄면 레일로 접혀 dim(오버레이)이 생기지 않는다. 1232까지는 접지 않는다", () => {
    expect(run(wideOpen(), resized(1280, 1232)).sidebarExpanded).toBe(true);
    const next = run(wideOpen(), resized(1232, 1231));
    expect(next).toMatchObject({ sidebarExpanded: false, evidenceTurnId: "turn-1" });
    expect(computeLayout(next, 1231)).toMatchObject({ sidebarOverlay: false, sidebarColumn: "rail", panelOpen: true });
    // 한 번에 크게 줄어도(1280 → 1100) 같다
    expect(run(wideOpen(), resized(1280, 1100)).sidebarExpanded).toBe(false);
  });

  it("다시 넓어져도(1231 → 1280) 자동으로 펼치지 않는다(접힌 채, 단방향이라 경계를 오가도 깜박이지 않는다)", () => {
    const folded = run(wideOpen(), resized(1280, 1231));
    const widened = run(folded, resized(1231, 1280), resized(1280, 1231), resized(1231, 1232));
    expect(widened.sidebarExpanded).toBe(false);
    expect(computeLayout(widened, 1280)).toMatchObject({ sidebarColumn: "rail", sidebarOverlay: false });
  });

  it("사용자가 밀 수 없는 폭에서 직접 펼친 오버레이(+dim)는 그대로 둔다: 폭이 더 바뀌어도 접지 않는다", () => {
    const manual = run(initialShellState, open(1100), { type: "toggleSidebar" });
    expect(computeLayout(manual, 1100).sidebarOverlay).toBe(true);
    expect(run(manual, resized(1100, 1050)).sidebarExpanded).toBe(true);
    expect(run(manual, resized(1100, 1200)).sidebarExpanded).toBe(true);
  });

  it("근거 상세가 닫혀 있거나 사이드바가 이미 접혀 있거나 좁은 폭이 끼면 아무것도 바꾸지 않는다(같은 상태 객체)", () => {
    const closed = run(initialShellState, open(1280), { type: "closeEvidence" });
    expect(run(closed, resized(1280, 1100))).toBe(closed);
    const rail = run(initialShellState, { type: "toggleSidebar" }, open(1280));
    expect(run(rail, resized(1280, 1100))).toBe(rail);
    const open1280 = wideOpen();
    expect(run(open1280, resized(1280, 900))).toBe(open1280); // 기준선 아래로는 viewportCrossed가 맡는다
    expect(run(open1280, resized(1280, 1300))).toBe(open1280);
  });

  it("넓어지며 기준선을 넘는 순간(좁은 폭에서 직접 연 시트 → 패널)은 이 규칙이 아니라 U-18 그대로 사이드바를 펼친다(§11 E6, 범위 밖·보고)", () => {
    const manual = run(initialShellState, { type: "viewportCrossed", desktop: false }, open(900));
    expect(run(manual, { type: "viewportCrossed", desktop: true }).sidebarExpanded).toBe(true);
    expect(run(manual, resized(900, 1100))).toBe(manual); // 기준선을 넘는 폭 변화는 viewportResized가 판정하지 않는다(같은 상태)
  });
});
