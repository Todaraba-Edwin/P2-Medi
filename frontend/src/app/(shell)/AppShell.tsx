"use client";

import { useEffect, useReducer, useRef, useState } from "react";
import { PhoneIcon } from "lucide-react";
import type { Candidate } from "@/lib/api";
import { BrandLogo } from "@/components/BrandLogo";
import { ChatInput, ExampleChips, HomeHero } from "@/features/chat";
import { EMERGENCY_CALL_LABEL, EMERGENCY_TEL_HREF, EmergencyBanner, FixedNoticeBox, LegalFooter } from "@/features/emergency";
import { EvidenceDetail, EvidencePanel } from "@/features/evidence";
import { DISCLAIMER } from "@/lib/fixed/phrases.generated";
import { cn } from "@/lib/utils";
import { chatStore, useChatStore } from "@/stores/chat";
import type { ChatStore } from "@/stores/chat";
import { Conversation } from "./Conversation";
import { NOT_SAVED_SHORT } from "./copy";
import { computeLayout, initialShellState, isDesktopWidth, shellReducer } from "./layout-rules";
import { MenuButton, MenuDrawer, SidebarColumn, SidebarOverlay } from "./Sidebar";
import { useViewportWidth } from "./useViewportWidth";

/**
 * 화면 조립(FE-IMPL-06): 119 배너(맨 위) → [사이드바 | 머리줄·대화·고정 영역·입력창 | 근거 상세].
 * 반응형(FE-07-09 B): 1023 이하는 사이드바 숨김·☰ 드로어·근거 상세 시트, 1024 이상은 사이드바 칸과 우측 패널.
 *
 * - 119 배너는 한 번 뜨면 내리지 않고, 사이드바 오버레이·드로어의 스크림 밖(위)에 둔다.
 * - 고정 안내·고지는 근거 상세 틀 밖의 접히지 않는 영역(입력창 위)에 응답 값 그대로 둔다.
 * - 사이드바 상태는 사용자 토글이 원천이다. 근거 상세가 새로 열리는 순간의 판정만 예외다(`layout-rules.ts`).
 */
export function AppShell({ store = chatStore }: { store?: ChatStore }) {
  const width = useViewportWidth();
  const turns = useChatStore((state) => state.turns, store);
  const emergency = useChatStore((state) => state.emergency, store);
  const [shell, dispatch] = useReducer(shellReducer, initialShellState);
  /** 되묻기에서 고른 후보(차례별, 메모리) */
  const [picked, setPicked] = useState<Record<string, Candidate>>({});
  /** 사이드바 오버레이·드로어를 그릴 자리(119 배너 아래 영역) */
  const [layer, setLayer] = useState<HTMLElement | null>(null);
  const main = useRef<HTMLElement>(null);

  // 화면을 떠나면 진행 중인 요청을 끊는다
  useEffect(() => () => store.getState().abort(), [store]);

  // 넓은 폭에서는 판정 줄이 있는 답이 도착하면 근거 상세를 연다(디자인 반영본). 여는 동작 안에서 사이드바 판정도 같이 한다
  useEffect(
    () =>
      store.subscribe((next, prev) => {
        if (next.turns === prev.turns) return;
        for (const turn of next.turns) {
          const response = turn.stream.response;
          if (!response || response.findings.length === 0) continue;
          if (prev.turns.find((before) => before.id === turn.id)?.stream.response) continue; // 이미 받은 답
          if (isDesktopWidth(window.innerWidth)) dispatch({ type: "openEvidence", turnId: turn.id, width: window.innerWidth });
        }
      }),
    [store],
  );

  const evidenceTurn = turns.find((turn) => turn.id === shell.evidenceTurnId);
  const evidenceResponse = evidenceTurn?.stream.response ?? null;
  const layout = width === null ? null : computeLayout(shell, width);

  const closeEvidence = () => {
    const turnId = shell.evidenceTurnId;
    dispatch({ type: "closeEvidence" });
    // 닫으면 들어온 결과로 돌아간다: 그 결과의 진입 버튼을 보이게 하고 초점을 준다
    if (turnId) {
      window.setTimeout(() => {
        const entry = main.current?.querySelector<HTMLElement>(`[data-turn="${turnId}"] [data-testid="evidence-entry"]`);
        entry?.scrollIntoView?.({ block: "nearest" });
        entry?.focus();
      }, 0);
    }
  };

  // 패널 배치에서 Esc로 닫는다(시트·사이드바 오버레이는 Radix가 처리한다). 한글 조합 중의 Esc는 넘긴다
  const panelEscape = layout !== null && layout.panelOpen && !layout.sidebarOverlay;
  const closeRef = useRef(closeEvidence);
  useEffect(() => {
    closeRef.current = closeEvidence;
  });
  useEffect(() => {
    if (!panelEscape) return;
    const onKey = (event: KeyboardEvent) => {
      // 사이드바 오버레이 등 다른 층이 이미 처리한 Esc(defaultPrevented)는 넘긴다: Esc 한 번에 한 층만 닫힌다
      if (event.key === "Escape" && !event.isComposing && !event.defaultPrevented) closeRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [panelEscape]);

  if (layout === null || width === null) return <div data-testid="app-shell" data-ready="false" className="h-dvh" />;

  const send = (question: string) => void store.getState().send(question);
  const newChat = () => {
    store.getState().reset();
    setPicked({});
    dispatch({ type: "newChat" });
  };
  const resend = (turnId: string) => {
    const { context, setContext, turns: current } = store.getState();
    const turn = current.find((item) => item.id === turnId);
    const pick = picked[turnId];
    if (!turn || !pick) return;
    // 고른 후보를 묶음에 붙이고 같은 질문을 다시 보낸다(PRD 15.3 (4))
    setContext({ confirmedDrugs: [...context.confirmedDrugs.filter((drug) => drug.name !== pick.name), { name: pick.name, itemSeq: pick.item_seq }] });
    send(turn.question);
  };
  const focusInput = () => main.current?.querySelector("textarea")?.focus();

  const first = turns[0];
  const last = turns[turns.length - 1];
  const lastFailed = last !== undefined && !last.stream.response && (last.stream.status === "error" || last.stream.status === "interrupted");
  // 아래 고정 영역이 보일 고정 안내: 가장 최근에 받은 답의 값. 마지막 차례가 응답 없는 오류면 오류 부품이 고정 안내·고지를 보인다
  const dockTurn = lastFailed ? undefined : [...turns].reverse().find((turn) => turn.stream.response);
  const dockResponse = dockTurn?.stream.response ?? null;
  const sidebar = { firstQuestion: first?.question ?? null, onNewChat: newChat };

  return (
    <div data-testid="app-shell" data-ready="true" className="flex h-dvh flex-col overflow-hidden">
      {/* 119 안내는 화면의 첫 요소다. 한 번 뜨면 내리지 않고, 사이드바 오버레이·드로어가 열려 있어도 전화 링크를 누를 수 있다 */}
      {emergency && (
        <div data-testid="emergency-row" className="flex-none px-3 pt-2 [&_a]:pointer-events-auto">
          <EmergencyBanner emergency={emergency} />
        </div>
      )}
      <div ref={setLayer} data-testid="shell-body" className="relative flex min-h-0 flex-1">
        {layout.sidebarColumn !== "none" && (
          <div inert={layout.sidebarOverlay} className="h-full flex-none">
            <SidebarColumn mode={layout.sidebarColumn} {...sidebar} onToggle={() => dispatch({ type: "toggleSidebar" })} />
          </div>
        )}
        <main ref={main} inert={layout.sidebarOverlay} data-testid="main" className="flex min-w-0 flex-1 flex-col bg-bg">
          <header data-testid="top-bar" className={cn("flex h-14 flex-none items-center gap-2", layout.desktop ? "px-4" : "px-2.5")}>
            {!layout.desktop && <MenuButton onClick={() => dispatch({ type: "openDrawer" })} />}
            <div className="min-w-0 flex-1 text-[15px] font-bold">
              {/* 서비스 이름은 머리줄에서 글자로 보인다(넓은 폭은 사이드바 머리에 있다) */}
              {layout.desktop ? first && <p className="m-0 max-w-[420px] truncate">{first.question}</p> : <BrandLogo size={22} />}
            </div>
            {layout.desktop && !layout.panelOpen && turns.length > 0 && <span className="flex-none text-xs text-mute">{NOT_SAVED_SHORT}</span>}
            {/* 119 접근: 배너가 떠 있지 않을 때의 진입점(배너가 뜨면 119는 배너 하나뿐이다) */}
            {!emergency && (
              <a
                href={EMERGENCY_TEL_HREF}
                data-testid="emergency-entry"
                className="flex min-h-11 flex-none items-center gap-1 rounded-full px-2 text-[13px] font-bold whitespace-nowrap text-red-ink no-underline"
              >
                <PhoneIcon className="size-4" strokeWidth={2.5} aria-hidden="true" />
                {EMERGENCY_CALL_LABEL}
              </a>
            )}
          </header>
          <div className={cn("mx-auto flex min-h-0 w-full flex-1 flex-col gap-2", layout.desktop ? "max-w-[880px] px-6" : "max-w-[760px] px-3")}>
            {turns.length === 0 ? (
              <div data-testid="home" className="flex min-h-0 flex-1 flex-col justify-center gap-4 overflow-y-auto py-2">
                <HomeHero />
                <ExampleChips onPick={send} />
              </div>
            ) : (
              <Conversation
                turns={turns}
                hasEmergency={emergency !== null}
                dockTurnId={dockTurn?.id ?? null}
                evidenceTurnId={evidenceResponse ? shell.evidenceTurnId : null}
                entryLabelMode={layout.entryLabelMode}
                picked={picked}
                onOpenEvidence={(turnId) => dispatch({ type: "openEvidence", turnId, width })}
                onRetry={(turnId) => void store.getState().retry(turnId)}
                onPick={(turnId, candidate) => setPicked((prev) => ({ ...prev, [turnId]: candidate }))}
                onOther={focusInput}
                onResend={resend}
              />
            )}
            {/* 접히지 않는 고정 영역: 고정 안내(응답 값 그대로) → 고지 → 입력창. 근거 상세 틀 밖이다 */}
            <div data-testid="dock" className="flex flex-none flex-col gap-1.5 pb-[max(14px,env(safe-area-inset-bottom,0px))]">
              {dockResponse && <FixedNoticeBox lines={dockResponse.fixed_notice} />}
              {/* 응답을 받기 전(시작 화면·첫 답을 기다리는 중)의 상시 고지는 백엔드 상수에서 생성한 값이다(FE-01-19 A) */}
              {!lastFailed && <LegalFooter disclaimer={dockResponse ? dockResponse.disclaimer : DISCLAIMER} />}
              <ChatInput onSend={send} />
            </div>
          </div>
        </main>
        {layout.panelOpen && evidenceResponse && (
          <div inert={layout.sidebarOverlay} data-testid="panel-column" className="h-full w-[400px] flex-none">
            <EvidencePanel mode="panel" open onOpenChange={(open) => !open && closeEvidence()}>
              <EvidenceDetail response={evidenceResponse} />
            </EvidencePanel>
          </div>
        )}
        {!layout.desktop && (
          <EvidencePanel mode="sheet" open={evidenceResponse !== null} onOpenChange={(open) => !open && closeEvidence()}>
            {evidenceResponse && <EvidenceDetail response={evidenceResponse} />}
          </EvidencePanel>
        )}
        <SidebarOverlay open={layout.sidebarOverlay} onClose={() => dispatch({ type: "collapseSidebar" })} container={layer} {...sidebar} />
        <MenuDrawer open={!layout.desktop && shell.drawerOpen} onClose={() => dispatch({ type: "closeDrawer" })} container={layer} {...sidebar} />
      </div>
    </div>
  );
}
