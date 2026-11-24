// 반응형 셸의 폭 규칙과 상태(순수 함수). 값은 새로 정하지 않고 디자인 반영본(2026-11-12 after5 프로토타입 번들)과
// 지시서 FE-IMPL-06 §8~§11의 값을 그대로 쓴다.

/** 펼친 사이드바 폭(프로토타입 `.side{width:272px}`) */
export const SIDEBAR_WIDTH = 272;
/** 접힌 레일 폭(프로토타입 `.rail{width:60px}`) */
export const RAIL_WIDTH = 60;
/** 근거 상세 패널 폭(프로토타입 `.panel{width:400px}`) */
export const PANEL_WIDTH = 400;
/** 본문 최소 폭 Wmin(프로토타입 `Nu=560`, 지시서 §9) */
export const MAIN_MIN_WIDTH = 560;
/** 이 폭부터 사이드바 칸과 우측 근거 패널을 쓴다. 그 아래는 ☰ 드로어와 시트다(지시서 §8 "폭 1023 이하") */
export const DESKTOP_MIN_WIDTH = 1024;
/** 이 폭부터 진입 글자가 "근거 상세 열기"다(지시서 G-1 "700 이상"). 그 아래는 "근거 상세 보기" */
export const ENTRY_OPEN_LABEL_MIN_WIDTH = 700;

export interface ShellState {
  /** 사이드바 펼침 여부. 사용자 토글이 원천이다(첫 화면은 펼침). 근거 상세가 새로 열리는 순간의 판정 한 곳만 예외로 접는다 */
  sidebarExpanded: boolean;
  /** 좁은 폭의 ☰ 드로어 */
  drawerOpen: boolean;
  /** 근거 상세가 열려 있는 결과(대화 차례 id). 닫혀 있으면 null. 들어온 결과에 고정한다 */
  evidenceTurnId: string | null;
}

export const initialShellState: ShellState = { sidebarExpanded: true, drawerOpen: false, evidenceTurnId: null };

export type ShellAction =
  | { type: "toggleSidebar" }
  | { type: "collapseSidebar" } // 오버레이의 스크림 클릭·Esc
  | { type: "openDrawer" }
  | { type: "closeDrawer" }
  /** 근거 상세 열기. `width`는 여는 순간의 화면 폭이다 */
  | { type: "openEvidence"; turnId: string; width: number }
  | { type: "closeEvidence" }
  | { type: "newChat" }
  /**
   * 창 크기가 사이드바 기준선(`DESKTOP_MIN_WIDTH`)을 가로질렀다(FE-17 U-18). 좁아지면(`desktop: false`) 사이드바·드로어를 닫고,
   * 넓어지면(`desktop: true`) 사이드바를 펼치고 드로어 상태를 지운다. 같은 구간 안의 크기 변화에는 보내지 않는다(사용자 토글을 덮지 않는다).
   * 근거 상세(FE-17 U-18 추가 지시, 2026-11-24): 좁아질 때만 닫는다(우측 패널이 본문을 덮는 시트로 바뀌지 않게). 넓어질 때는 다시 열지 않고
   * 지금 상태를 그대로 둔다(자동으로 닫힌 것은 닫힌 채, 좁은 폭에서 사용자가 직접 연 것은 열린 채)
   */
  | { type: "viewportCrossed"; desktop: boolean };

export const isDesktopWidth = (width: number) => width >= DESKTOP_MIN_WIDTH;

/** 사이드바를 **밀어서** 펼칠 수 있는가: `뷰포트 − 272 − (패널 열림 ? 400 : 0) ≥ Wmin`(지시서 §9) */
export function canPushSidebar(width: number, panelOpen: boolean): boolean {
  return width - SIDEBAR_WIDTH - (panelOpen ? PANEL_WIDTH : 0) >= MAIN_MIN_WIDTH;
}

export function shellReducer(state: ShellState, action: ShellAction): ShellState {
  switch (action.type) {
    case "toggleSidebar":
      return { ...state, sidebarExpanded: !state.sidebarExpanded };
    case "collapseSidebar":
      return { ...state, sidebarExpanded: false };
    case "openDrawer":
      return { ...state, drawerOpen: true };
    case "closeDrawer":
      return { ...state, drawerOpen: false };
    case "openEvidence": {
      // 새로 열리는 순간에만(닫힘 → 열림) 판정한다. 이미 열린 채 다른 결과로 바뀔 때·폭이 바뀔 때·사용자 토글에는 적용하지 않는다(§10·§11)
      const newlyOpened = state.evidenceTurnId === null;
      const wouldOverlay = isDesktopWidth(action.width) && state.sidebarExpanded && !canPushSidebar(action.width, true);
      return {
        ...state,
        evidenceTurnId: action.turnId,
        // 같은 갱신 안에서 함께 접는다: 스크림이 한 번도 그려지지 않는다(§11 ⑦)
        sidebarExpanded: newlyOpened && wouldOverlay ? false : state.sidebarExpanded,
      };
    }
    case "closeEvidence":
      return { ...state, evidenceTurnId: null }; // 사이드바 상태는 건드리지 않는다
    case "newChat":
      return { ...state, drawerOpen: false, evidenceTurnId: null };
    case "viewportCrossed":
      return { ...state, sidebarExpanded: action.desktop, drawerOpen: false, evidenceTurnId: action.desktop ? state.evidenceTurnId : null };
  }
}

export interface ShellLayout {
  desktop: boolean;
  /** 우측 패널로 열려 있는가(넓은 폭 + 근거 상세 열림) */
  panelOpen: boolean;
  /** 사이드바가 본문 위 오버레이로 펼쳐져 있는가(전체 스크림, 뒤는 조작 불가) */
  sidebarOverlay: boolean;
  /** 배치 칸의 사이드바 모양 */
  sidebarColumn: "none" | "rail" | "expanded";
  /** 근거 상세 배치 */
  evidenceMode: "sheet" | "panel";
  /** 진입 버튼 글자 종류(`EvidenceEntryButton`의 `mode`로 넘긴다) */
  entryLabelMode: "sheet" | "panel";
}

/** 상태와 지금 폭에서 배치를 계산한다. 폭이 바뀌어도 상태(사용자 선택)는 그대로이고 표현만 바뀐다 */
export function computeLayout(state: ShellState, width: number): ShellLayout {
  const desktop = isDesktopWidth(width);
  const panelOpen = desktop && state.evidenceTurnId !== null;
  const sidebarOverlay = desktop && state.sidebarExpanded && !canPushSidebar(width, panelOpen);
  return {
    desktop,
    panelOpen,
    sidebarOverlay,
    sidebarColumn: !desktop ? "none" : state.sidebarExpanded && !sidebarOverlay ? "expanded" : "rail",
    evidenceMode: desktop ? "panel" : "sheet",
    entryLabelMode: width >= ENTRY_OPEN_LABEL_MIN_WIDTH ? "panel" : "sheet",
  };
}
