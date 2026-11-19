"use client";

import { useEffect, useReducer, useRef, useState } from "react";
import { UserIcon } from "lucide-react";
import type { Candidate } from "@/lib/api";
import { BrandLogo } from "@/components/BrandLogo";
import { AccountMenu, AccountModal, EntryChoice, LOGIN_ENTRY_LABEL, MANAGE_PROFILES_LABEL, TargetPicker, isAccountEntryEnabled, openAccountModal } from "@/features/account";
import { ChatInput, ExampleChips, HomeHero } from "@/features/chat";
import { EmergencyBanner, ExternalAiNotice, FixedNoticeBox, LegalFooter, StartEmergencyLink } from "@/features/emergency";
import { EvidenceDetail, EvidencePanel } from "@/features/evidence";
import { groupCandidates } from "@/features/result";
import { DISCLAIMER, START_EMERGENCY_119, START_EXTERNAL_AI_NOTICE } from "@/lib/fixed/phrases.generated";
import { AUTH_CALLBACK_ERROR_CODES, takeAuthErrorFromLocation } from "@/lib/supabase/callback";
import { cn } from "@/lib/utils";
import { accountStore, hasHealthConsent, selectTargetProfile, useAccountStore } from "@/stores/account";
import type { AccountStore } from "@/stores/account";
import { chatStore, useChatStore } from "@/stores/chat";
import type { ChatStore } from "@/stores/chat";
import { profileToContext } from "@/stores/profile-context";
import { Conversation } from "./Conversation";
import { EmergencyEntry } from "./EmergencyEntry";
import { NOT_SAVED_SHORT, resendBubbleText } from "./copy";
import { computeLayout, initialShellState, isDesktopWidth, shellReducer } from "./layout-rules";
import { IconButton, MenuButton, MenuDrawer, SidebarColumn, SidebarOverlay } from "./Sidebar";
import { useViewportWidth } from "./useViewportWidth";

/**
 * 화면 조립(FE-IMPL-06): 119 배너(맨 위) → [사이드바 | 머리줄·대화·고정 영역·입력창 | 근거 상세].
 * 반응형(FE-07-09 B): 1023 이하는 사이드바 숨김·☰ 드로어·근거 상세 시트, 1024 이상은 사이드바 칸과 우측 패널.
 *
 * - 119 배너는 한 번 뜨면 내리지 않고, 사이드바 오버레이·드로어·근거 상세 시트의 스크림 밖(위)에 둔다(층은 배너 아래 영역에만 그린다).
 * - 배너가 없을 때 119 진입점은 머리줄에 있고, 머리줄을 덮는 층(드로어·오버레이·시트) 안에도 같은 진입점을 둔다(G-3).
 * - 고정 안내·고지는 근거 상세 틀 밖의 접히지 않는 영역(입력창 위)에 응답 값 그대로 둔다.
 * - 사이드바 상태는 사용자 토글이 원천이다. 근거 상세가 새로 열리는 순간의 판정만 예외다(`layout-rules.ts`).
 * - 계정(FE-04): 시작 화면의 진입 선택(게스트로 시작 / 로그인·가입), 사이드바의 계정 자리, 계정 모달, 입력창 위의 대상 선택.
 *   게스트는 지금처럼 바로 질문한다. 계정 모달도 배너 아래 영역에만 그린다(119 배너를 덮지 않는다).
 */
export function AppShell({ store = chatStore, account = accountStore }: { store?: ChatStore; account?: AccountStore }) {
  const width = useViewportWidth();
  const member = useAccountStore((state) => state.status === "member", account);
  // 계정 진입점 스위치(FE-04-02 A·FE-04-05 A): 로그인할 길(목 모드이거나 Supabase 설정)이 있을 때만 켠다. 꺼져 있으면 로그인/가입·계정 자리를 그리지 않고 `/api/me`도 부르지 않는다
  const accountEnabled = isAccountEntryEnabled();
  const profiles = useAccountStore((state) => state.profiles, account);
  const targetProfileId = useAccountStore((state) => state.targetProfileId, account);
  const entryDismissed = useAccountStore((state) => state.entryDismissed, account);
  const turns = useChatStore((state) => state.turns, store);
  const emergency = useChatStore((state) => state.emergency, store);
  const [shell, dispatch] = useReducer(shellReducer, initialShellState);
  /** 되묻기에서 고른 후보(차례별 → 묶음 `input_name`별, 메모리) */
  const [picked, setPicked] = useState<Record<string, Record<string, Candidate>>>({});
  /** 사이드바 오버레이·드로어를 그릴 자리(119 배너 아래 영역) */
  const [layer, setLayer] = useState<HTMLElement | null>(null);
  const main = useRef<HTMLElement>(null);

  // 화면을 떠나면 진행 중인 요청을 끊는다
  useEffect(() => () => store.getState().abort(), [store]);

  // 로그인 세션이 있으면(소셜 로그인에서 돌아온 경우·새로고침) 로그인 상태를 읽는다. 없거나 실패하면 게스트 그대로다.
  // 로그인 콜백이 실패해 돌아왔으면(`?auth_error=`: 이메일 없는 카카오계정 등) 주소에서 표시를 지우고 로그인 화면에 안내를 보인다
  useEffect(() => {
    if (!accountEnabled) return;
    const authError = takeAuthErrorFromLocation();
    if (authError) account.getState().failLogin(AUTH_CALLBACK_ERROR_CODES[authError]);
    else void account.getState().bootstrap();
  }, [account, accountEnabled]);

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

  /** 고른 대상("누가 먹나요")의 연령대·임신 여부. 게스트이거나 고르지 않았으면 두 칸은 비어 있다(값 전달만, 대화는 저장하지 않는다) */
  const targetContext = () => {
    const state = account.getState();
    return profileToContext(selectTargetProfile(state), hasHealthConsent(state.me));
  };
  // 새 질문: 이번 질문의 되묻기 답은 없다(`confirmed_drugs=[]`, AG-21-02 A). 이전 차례의 선택(`priorDrugs`)은 그대로 실린다
  const send = (question: string) => {
    store.getState().setContext({ ...targetContext(), confirmedDrugs: [] });
    void store.getState().send(question);
  };
  const newChat = () => {
    store.getState().reset();
    setPicked({});
    dispatch({ type: "newChat" });
  };
  // 대상이 바뀌면 이전 선택 힌트를 비운다(AG-21-03 A: 다른 사람의 약을 같은 이름으로 확인하지 않게)
  const changeTarget = (profileId: string | null) => {
    if (profileId !== targetProfileId) store.getState().setContext({ priorDrugs: [] });
    account.getState().setTarget(profileId);
  };
  const resend = (turnId: string) => {
    const { setContext, turns: current } = store.getState();
    const turn = current.find((item) => item.id === turnId);
    const picks = picked[turnId] ?? {};
    const groups = groupCandidates(turn?.stream.response?.candidates ?? []);
    const chosen = groups.flatMap((group) => (picks[group.inputName] ? [picks[group.inputName]] : []));
    // 모든 묶음(되묻는 이름)을 골랐을 때만 보낸다(FE-09-01 A)
    if (!turn || groups.length === 0 || chosen.length !== groups.length) return;
    // 고른 후보 전부를 묶음에 한 번에 붙이고 같은 질문을 한 번 다시 보낸다(PRD 15.3 (4), 요청 1회).
    // 지금 고른 것만 `confirmed_drugs`로 싣고, 이전 차례의 선택은 `prior_drugs`로 따로 간다(AG-21-02 A). 답이 오면 스토어가 고른 것을 이전 선택으로 옮긴다
    const names = chosen.map((candidate) => candidate.name);
    setContext({
      ...targetContext(),
      // 어느 묶음에서 골랐는지(`input_name`)를 함께 싣는다(FE-09-05 A). 묶음이 하나여도 싣는다
      confirmedDrugs: chosen.map((candidate) => ({ name: candidate.name, itemSeq: candidate.item_seq, inputName: candidate.input_name })),
    });
    // 말풍선에는 무엇을 골랐는지 보이고(FE-09-04 A), 서버로는 원 질문을 보낸다
    void store.getState().send(turn.question, resendBubbleText(names));
  };
  const focusInput = () => main.current?.querySelector("textarea")?.focus();
  // 계정 모달을 열 때 드로어·사이드바 오버레이는 닫는다(층을 겹치지 않는다)
  const openAccount = () => {
    dispatch({ type: "closeDrawer" });
    if (layout.sidebarOverlay) dispatch({ type: "collapseSidebar" });
    openAccountModal(account);
  };
  const startGuest = () => {
    account.getState().startGuest();
    focusInput();
  };
  const accountMenu = accountEnabled ? <AccountMenu member={member} onOpen={openAccount} onLogout={() => void account.getState().logout()} /> : null;

  const first = turns[0];
  const last = turns[turns.length - 1];
  const lastFailed = last !== undefined && !last.stream.response && (last.stream.status === "error" || last.stream.status === "interrupted");
  // 아래 고정 영역이 보일 고정 안내: 가장 최근에 받은 답의 값. 마지막 차례가 응답 없는 오류면 오류 부품이 고정 안내·고지를 보인다
  const dockTurn = lastFailed ? undefined : [...turns].reverse().find((turn) => turn.stream.response);
  const dockResponse = dockTurn?.stream.response ?? null;
  const sidebar = { firstQuestion: first?.question ?? null, onNewChat: newChat, account: accountMenu };

  return (
    <div data-testid="app-shell" data-ready="true" className="flex h-dvh flex-col overflow-hidden">
      {/* 119 안내는 화면의 첫 요소다. 한 번 뜨면 내리지 않고, 사이드바 오버레이·드로어·근거 상세 시트가 열려 있어도 전화 링크를 누를 수 있다
          (층은 아래 shell-body 안에만 그리고, Radix 모달이 body에 거는 pointer-events:none을 배너 행 전체에서 되살린다: 배너가 덮이지 않은 화면 요소로 남는다) */}
      {emergency && (
        <div data-testid="emergency-row" className="pointer-events-auto flex-none px-3 pt-2">
          <EmergencyBanner emergency={emergency} />
        </div>
      )}
      <div ref={setLayer} data-testid="shell-body" className="relative flex min-h-0 flex-1">
        {layout.sidebarColumn !== "none" && (
          <div inert={layout.sidebarOverlay} className="h-full flex-none">
            <SidebarColumn
              mode={layout.sidebarColumn}
              {...sidebar}
              onToggle={() => dispatch({ type: "toggleSidebar" })}
              railAccount={
                accountEnabled && (
                  <IconButton label={member ? MANAGE_PROFILES_LABEL : LOGIN_ENTRY_LABEL} data-testid="account-entry" className="mt-auto" onClick={openAccount}>
                    <UserIcon className="size-5" aria-hidden="true" />
                  </IconButton>
                )
              }
            />
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
            {!emergency && <EmergencyEntry testId="emergency-entry" />}
          </header>
          <div className={cn("mx-auto flex min-h-0 w-full flex-1 flex-col gap-2", layout.desktop ? "max-w-[880px] px-6" : "max-w-[760px] px-3")}>
            {turns.length === 0 ? (
              <div data-testid="home" className="flex min-h-0 flex-1 flex-col justify-center gap-4 overflow-y-auto py-2">
                <HomeHero />
                {/* 진입 선택: 게스트로 시작(주) / 로그인·가입(보조). 누르지 않아도 아래 입력창으로 바로 질문할 수 있다 */}
                {accountEnabled && !member && !entryDismissed && <EntryChoice onGuest={startGuest} onLogin={openAccount} />}
                <ExampleChips onPick={(question) => send(question)} />
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
                onPick={(turnId, candidate) => setPicked((prev) => ({ ...prev, [turnId]: { ...prev[turnId], [candidate.input_name]: candidate } }))}
                onOther={focusInput}
                onResend={resend}
              />
            )}
            {/* 접히지 않는 고정 영역: 고정 안내(응답 값 그대로) → 고지 → 입력창. 근거 상세 틀 밖이다 */}
            <div data-testid="dock" className="flex flex-none flex-col gap-1.5 pb-[max(14px,env(safe-area-inset-bottom,0px))]">
              {dockResponse && <FixedNoticeBox lines={dockResponse.fixed_notice} />}
              {/* 시작 화면 안내 2종(질문을 보내기 전, 입력창 가까이): 119 안내 줄과 외부 AI 전송 고지. 백엔드 상수에서 생성한 값 그대로다(FE-01-19 A·FE-01-24 A, RFP-24-01) */}
              {turns.length === 0 && (
                <>
                  <StartEmergencyLink text={START_EMERGENCY_119} />
                  <ExternalAiNotice text={START_EXTERNAL_AI_NOTICE} />
                </>
              )}
              {/* 응답을 받기 전(시작 화면·첫 답을 기다리는 중)의 상시 고지는 백엔드 상수에서 생성한 값이다(FE-01-19 A) */}
              {!lastFailed && <LegalFooter disclaimer={dockResponse ? dockResponse.disclaimer : DISCLAIMER} />}
              {/* 대상 선택 "누가 먹나요": 로그인하고 프로필이 있을 때만(게스트는 숨김) */}
              {member && profiles.length > 0 && <TargetPicker profiles={profiles} value={targetProfileId} onChange={changeTarget} />}
              <ChatInput onSend={(question) => send(question)} />
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
          <EvidencePanel
            mode="sheet"
            open={evidenceResponse !== null}
            onOpenChange={(open) => !open && closeEvidence()}
            // 응급이면 배너 아래 영역에만 그린다(사용자 결정 2026-11-16 후보 5 B). 아니면 화면 전체(기존 동작)이고, 머리줄 119를 덮으므로 시트 안에 진입점을 둔다
            container={emergency ? layer : undefined}
            headerAction={!emergency && <EmergencyEntry testId="layer-emergency-entry" />}
          >
            {evidenceResponse && <EvidenceDetail response={evidenceResponse} />}
          </EvidencePanel>
        )}
        {accountEnabled && <AccountModal store={account} container={layer} hasEmergency={emergency !== null} emergencyEntry={!emergency && <EmergencyEntry testId="layer-emergency-entry" />} />}
        <SidebarOverlay open={layout.sidebarOverlay} onClose={() => dispatch({ type: "collapseSidebar" })} container={layer} showEmergencyEntry={!emergency} {...sidebar} />
        <MenuDrawer open={!layout.desktop && shell.drawerOpen} onClose={() => dispatch({ type: "closeDrawer" })} container={layer} showEmergencyEntry={!emergency} {...sidebar} />
      </div>
    </div>
  );
}
