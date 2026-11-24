"use client";

import { useEffect, useLayoutEffect, useReducer, useRef, useState } from "react";
import type { Candidate } from "@/lib/api";
import { BrandLogo } from "@/components/BrandLogo";
import { NoMascotZone } from "@/components/NoMascotZone";
import { AccountMenu, AccountModal, EntryChoice, LegalDialog, StartTargetNotice, TargetChip, isAccountEntryEnabled, mayHaveSessionNow, openAccountModal } from "@/features/account";
import { failureMessage } from "@/features/account/parts";
import { ChatInput, ExampleChips, HomeHero, PREGNANCY_SAVE_CONSENT_HINT } from "@/features/chat";
import { EmergencyBanner } from "@/features/emergency";
import { EvidenceDetail, EvidencePanel } from "@/features/evidence";
import { PhotoModal } from "@/features/photo";
import type { ChatInputFromPhoto } from "@/features/photo";
import { groupCandidates } from "@/features/result";
import { AUTH_CALLBACK_ERROR_CODES, takeAuthErrorFromLocation, takeAuthResumeFromLocation } from "@/lib/supabase/callback";
import { isApiMockingEnabled } from "@/mocks";
import { cn } from "@/lib/utils";
import { accountStore, hasHealthConsent, hidesPregnancyToggle, selectTargetProfile, useAccountStore } from "@/stores/account";
import type { AccountFailure, AccountStore } from "@/stores/account";
import { chatStore, useChatStore } from "@/stores/chat";
import type { ChatStore } from "@/stores/chat";
import { profileToContext } from "@/stores/profile-context";
import { Conversation } from "./Conversation";
import { EmergencyEntry } from "./EmergencyEntry";
import { NOT_SAVED_SHORT, SYNTHETIC_DEMO_NOTICE, resendBubbleText } from "./copy";
import { computeLayout, initialShellState, isDesktopWidth, shellReducer } from "./layout-rules";
import { MenuButton, MenuDrawer, SidebarColumn, SidebarOverlay } from "./Sidebar";
import { useViewportWidth } from "./useViewportWidth";

/**
 * 화면 조립(FE-IMPL-06): 119 배너(맨 위) → [사이드바 | 머리줄·대화·고정 영역·입력창 | 근거 상세].
 * 반응형(FE-07-09 B): 1023 이하는 사이드바 숨김·☰ 드로어·근거 상세 시트, 1024 이상은 사이드바 칸과 우측 패널.
 *
 * - 119 배너는 한 번 뜨면 내리지 않고, 사이드바 오버레이·드로어·근거 상세 시트의 스크림 밖(위)에 둔다(층은 배너 아래 영역에만 그린다).
 * - 배너가 없을 때 119 진입점은 머리줄 하나다(FE-17 U-04: 층 안에는 두지 않는다. 옛 G-3 "층 안 진입점"을 대체).
 * - 고정 안내는 근거 상세 틀 밖, 각 답 아래의 접히지 않는 자리에 응답 값 그대로 둔다(FE-17 U-26-1, 2026-11-24: 입력창 위 고정 영역에서 옮김.
 *   같은 줄은 대화에서 가장 최근 답 한 곳에만 보인다, `Conversation`).
 * - 사이드바 상태는 사용자 토글이 원천이다. 근거 상세가 새로 열리는 순간의 판정만 예외다(`layout-rules.ts`).
 * - 계정(FE-04): 시작 화면의 진입 선택(게스트로 시작 / 로그인·가입), 사이드바의 계정 자리, 계정 모달.
 *   대상 프로필("누가 먹나요", 2026-11-23): 본문 선택 줄은 없다. 입력창 안 프로필 칩(`TargetChip`)과 계정 버튼 메뉴의 `프로필 관리` 아래 목록,
 *   시작 화면 기본 대상 안내(`StartTargetNotice`, FE-17 U-08)에서 고르고, 값은 계정 스토어의 `targetProfileId` 하나(메모리)라 모든 자리와
 *   계정 버튼 표시(병아리 + 이름)가 같이 바뀐다. 고른 값은 서버 기본 대상으로 저장돼 새 세션의 기본값이 된다(브라우저 저장소에는 두지 않는다). 요청에 싣는 값은 예전과 같다.
 *   게스트는 지금처럼 바로 질문한다. 계정 모달도 배너 아래 영역에만 그린다(119 배너를 덮지 않는다).
 * - 입력창 아래 통합 고지(FE-17 U-02): 법적 고지와 입력창 고지의 의미를 한 단락 상수로 합쳐 둔다(`ChatInput`, 사용자 승인 완료 문구).
 * - 119(FE-17 U-04): 평상시는 머리줄 `emergency-entry`, 응급 키워드가 오면 맨 위 배너 하나. 시작 화면 줄·층(드로어·시트·모달) 안 진입점은 없다.
 * - 임신 여부(FE-11 §7.1, 2026-11-20): 입력창 안 왼쪽 토글 "일반인 | 임산부"가 `context.pregnant`의 원천이다(일반인 false·임산부 true, FE-11-12 A).
 *   시작값은 고른 대상 프로필의 임신 여부(건강 정보 동의가 있을 때, 임신 중이면 임산부)이고 대상을 바꾸면 그 값으로 바뀐다. 게스트는 일반인.
 *   토글을 바꾸면 로그인 + 건강 정보 동의 + 대상 프로필이 있을 때만 그 프로필의 `pregnancy_status`를 PATCH한다(FE-11-13, 양방향);
 *   동의 없음·게스트는 저장하지 않고 이 대화에만 적용하며 안내 한 줄을 둔다(FE-11-14 A). 저장 실패는 대화 값을 유지하고 짧게 알린다
 * - 성별 숨김(FE-11-09 C, GROUP-03 3단계): 대상 프로필의 성별이 **남성일 때만** 토글을 그리지 않고 `context.pregnant`는 false로 고정한다(FE-11-12 A).
 *   여성·성별 미입력·게스트(대상 없음)는 그대로 보인다. 가족 프로필을 고르면 그 프로필의 성별을 따른다. 토글이 빠져도 입력창 높이는 같다(textarea `min-h-11`이 44px를 유지)
 */
export function AppShell({ store = chatStore, account = accountStore }: { store?: ChatStore; account?: AccountStore }) {
  const width = useViewportWidth();
  const member = useAccountStore((state) => state.status === "member", account);
  // 계정 진입점 스위치(FE-04-02 A·FE-04-05 A): 로그인할 길(목 모드이거나 Supabase 설정)이 있을 때만 켠다. 꺼져 있으면 로그인/가입·계정 자리를 그리지 않고 `/api/me`도 부르지 않는다
  const accountEnabled = isAccountEntryEnabled();
  const profiles = useAccountStore((state) => state.profiles, account);
  const targetProfileId = useAccountStore((state) => state.targetProfileId, account);
  const entryDismissed = useAccountStore((state) => state.entryDismissed, account);
  /**
   * 로그인 확정 전(FE-17 U-22 추가, 2026-11-24): 스토어의 `guest`는 첫 `bootstrap()`이 끝나기 전 초기값일 뿐이다. 로그인돼 있을 수 있으면(목 모드·Supabase 세션 쿠키 있음)
   * 확정될 때까지 시작 화면의 대상·계정 자리(`StartTargetNotice`·`EntryChoice`)를 같은 높이의 빈 자리로만 두고, 확정 뒤 한 번에 그린다.
   * 세션 쿠키가 없는 비로그인은 false라 지금처럼 곧바로 게스트 화면이다
   */
  const sessionChecked = useAccountStore((state) => state.sessionChecked, account);
  const authPending = accountEnabled && !member && !sessionChecked && mayHaveSessionNow();
  /** 대상 프로필이 남성이면 토글을 숨긴다(FE-11-09 C). 게스트·선택 안 함·여성·미입력은 false */
  const pregnancyHidden = useAccountStore((state) => hidesPregnancyToggle(selectTargetProfile(state)), account);
  /**
   * 고른 대상 프로필의 임신 여부(건강 정보 동의가 있을 때만 읽는다). 토글의 시작값이고 대상·프로필이 바뀌면 토글이 이 값으로 돌아간다.
   * 토글을 숨기는 대상(남성)은 저장된 값과 상관없이 false다(FE-11-12 A)
   */
  const profilePregnant = useAccountStore((state) => !hidesPregnancyToggle(selectTargetProfile(state)) && profileToContext(selectTargetProfile(state), hasHealthConsent(state.me)).pregnant === true, account);
  /** 임신 여부 토글 값(대화 묶음 `context.pregnant`, 메모리). null(아직 정하지 않음)은 일반인으로 본다 */
  const pregnant = useChatStore((state) => state.context.pregnant === true, store);
  /**
   * 토글 근처 안내: 동의 없음·게스트가 토글을 바꿨다(이 대화에만 적용, FE-11-14 A) / 프로필 저장 실패. 대상(또는 그 프로필의 임신 여부)이 바뀌면
   * 안내는 그 대상에만 붙어 있던 것이라 보이지 않는다(`key`가 지금 대상과 다르면 숨김. 효과 안에서 상태를 지우지 않는다)
   */
  const pregnancyNoteKey = `${targetProfileId ?? ""}|${profilePregnant}`;
  const [pregnancyNote, setPregnancyNote] = useState<{ key: string; hint: boolean; error: AccountFailure | null }>({ key: "", hint: false, error: null });
  const pregnancyHint = pregnancyNote.key === pregnancyNoteKey && pregnancyNote.hint;
  const pregnancyError = pregnancyNote.key === pregnancyNoteKey ? pregnancyNote.error : null;
  const pregnancySaveSeq = useRef(0);
  const turns = useChatStore((state) => state.turns, store);
  const emergency = useChatStore((state) => state.emergency, store);
  /** 이번 탭의 대화들(FE-17 U-29, 메모리). 사이드바 `지금 대화` 목록이 된다 */
  const conversations = useChatStore((state) => state.conversations, store);
  const currentChatId = useChatStore((state) => state.currentId, store);
  /** 대화를 옮기며 대상을 되살렸을 때, 대상 변경 효과가 되살린 대화의 토글 값을 프로필 값으로 덮지 않게 한 번 건너뛴다 */
  const skipPregnantSync = useRef(false);
  const [shell, dispatch] = useReducer(shellReducer, initialShellState);
  /** 약관·정책 열람 화면 열림 여부(계정 메뉴의 `약관·정책` 항목, 2026-11-23). 계정과 상관없이 게스트도 연다. 화면 모드는 메뉴 안에서 바로 고른다(FE-12-03 B) */
  const [legalOpen, setLegalOpen] = useState(false);
  /** 되묻기에서 고른 후보(차례별 → 묶음 `input_name`별, 메모리) */
  const [picked, setPicked] = useState<Record<string, Record<string, Candidate>>>({});
  /** 사이드바 오버레이·드로어를 그릴 자리(119 배너 아래 영역) */
  const [layer, setLayer] = useState<HTMLElement | null>(null);
  const main = useRef<HTMLElement>(null);
  /**
   * 입력 영역(`dock`)의 높이와 대화 스크롤 컨테이너의 스크롤바 폭(FE-17 U-27 추가 지시 2). 대화 중에는 입력 영역이 스크롤 영역 하단에 겹쳐 고정되므로
   * 대화 영역은 아래쪽에 입력 영역 높이만큼 여백을 두고(입력창이 여러 줄로 커지면 따라간다), 입력 영역은 스크롤바 자리를 덮지 않게 그만큼 오른쪽을 비운다
   */
  // 입력 영역은 앱이 준비된 뒤에 그려질 수 있어(첫 렌더에 없을 수 있다) 요소를 상태로 받아 붙을 때 관찰을 시작한다
  const [dockEl, setDockEl] = useState<HTMLDivElement | null>(null);
  const [dockHeight, setDockHeight] = useState(0);
  const [threadScrollbar, setThreadScrollbar] = useState(0);
  useEffect(() => {
    const el = dockEl;
    if (!el) return;
    const update = () => setDockHeight(Math.ceil(el.getBoundingClientRect().height));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [dockEl]);
  /** 사진 입력 모달(FE-05 사진 부분). 사진·읽은 목록은 모달 안 메모리에만 있다 */
  const [photoOpen, setPhotoOpen] = useState(false);
  /** 사진 모달이 닫힌 뒤 초점을 둘 곳: 기본은 사진 버튼, `글자로 입력`이면 입력창 */
  const photoCloseFocus = useRef<"entry" | "input">("entry");

  // 화면을 떠나면 진행 중인 요청을 끊는다
  useEffect(() => () => store.getState().abort(), [store]);

  // 로그인 세션이 있으면(소셜 로그인에서 돌아온 경우·새로고침) 로그인 상태를 읽는다. 없거나 실패하면 게스트 그대로다.
  // 로그인 콜백이 실패해 돌아왔으면(`?auth_error=`: 이메일 없는 카카오계정 등) 주소에서 표시를 지우고 로그인 화면에 안내를 보인다.
  // 콜백이 성공해 돌아왔으면(`?auth_resume=1`, 2026-11-22 사용자 보고: 소셜 로그인은 페이지 이동이라 모달이 닫힌 채 돌아온다) 표시를 한 번 읽어
  // 지우고, 서버 상태를 읽은 뒤 온보딩(동의 → 프로필)이 남았을 때만 계정 모달을 그 단계로 다시 연다. 이미 마친 사용자는 바로 채팅이다.
  // 사용자가 그 모달을 닫으면 다시 열지 않는다(표시는 이미 지워졌다): 사이드바 `프로필 관리`에서 같은 단계로 이어 간다
  useEffect(() => {
    if (!accountEnabled) return;
    const authError = takeAuthErrorFromLocation();
    const resume = takeAuthResumeFromLocation();
    if (authError) account.getState().failLogin(AUTH_CALLBACK_ERROR_CODES[authError]);
    else {
      void account.getState().bootstrap().then(() => {
        if (resume) account.getState().resumeOnboarding();
      });
    }
  }, [account, accountEnabled]);

  // 넓은 폭에서는 판정 줄이 있는 답이 도착하면 근거 상세를 연다(디자인 반영본). 여는 동작 안에서 사이드바 판정도 같이 한다.
  // 다른 대화의 답이 뒤에서 도착하면(FE-17 U-29, 백그라운드 스트림) 지금 화면은 그대로 두고, 그 대화로 돌아갈 때 열리도록 적어 둔다.
  // 대화를 옮긴 갱신(`currentId`가 바뀜)은 새 답이 아니므로 건너뛴다(근거 상세는 옮기는 쪽이 되살린다)
  useEffect(
    () =>
      store.subscribe((next, prev) => {
        if (next.conversations === prev.conversations || next.currentId !== prev.currentId) return;
        for (const conversation of next.conversations) {
          const before = prev.conversations.find((item) => item.id === conversation.id);
          if (before?.turns === conversation.turns) continue;
          for (const turn of conversation.turns) {
            const response = turn.stream.response;
            if (!response || response.findings.length === 0) continue;
            if (before?.turns.find((item) => item.id === turn.id)?.stream.response) continue; // 이미 받은 답
            if (!isDesktopWidth(window.innerWidth)) continue;
            if (conversation.id === next.currentId) dispatch({ type: "openEvidence", turnId: turn.id, width: window.innerWidth });
            else store.getState().setScreen(conversation.id, { evidenceTurnId: turn.id });
          }
        }
      }),
    [store],
  );

  // 로그아웃·탈퇴·계정 전환(FE-17 U-29): 이번 탭에 남겨 둔 다른 대화들을 지운다(다른 계정의 프로필 문맥과 섞이지 않게).
  // 보고 있던 대화는 예전처럼 그대로 둔다(기존 동작 "로그아웃·탈퇴 뒤에도 대화는 그대로다", 화면·드로어도 그대로). 게스트가 로그인하는 것은 비우지 않는다
  useEffect(
    () =>
      account.subscribe((next, prev) => {
        const loggedOut = prev.status === "member" && next.status === "guest";
        const switched = prev.me !== null && next.me !== null && prev.me.user_id !== next.me.user_id;
        if (loggedOut || switched) store.getState().keepOnlyCurrent();
      }),
    [account, store],
  );

  // 대상(또는 그 프로필의 임신 여부)이 바뀌면 토글(대화 묶음)은 그 프로필 값으로 시작한다(§7.1 규칙 ①·②).
  // 저장에 실패해 프로필이 그대로면 이 값이 바뀌지 않으므로 대화 값(토글)은 유지된다(FE-11-13 "실패 시 대화 값 유지").
  // 이번 탭의 다른 대화로 옮기며 그 대화의 대상을 되살린 경우(FE-17 U-29)는 그 대화의 토글 값을 그대로 둔다
  useEffect(() => {
    if (skipPregnantSync.current) {
      skipPregnantSync.current = false;
      return;
    }
    store.getState().setContext({ pregnant: profilePregnant });
  }, [store, targetProfileId, profilePregnant]);

  const evidenceTurn = turns.find((turn) => turn.id === shell.evidenceTurnId);
  const evidenceResponse = evidenceTurn?.stream.response ?? null;
  const layout = width === null ? null : computeLayout(shell, width);
  const desktop = width === null ? null : isDesktopWidth(width);

  // 창 크기 자동 열고 닫기(FE-17 U-18): 폭이 사이드바 기준선(1024px)을 **가로지를 때만** 좁아지면 닫고 넓어지면 펼친다.
  // 값이 바뀔 때만 도는 효과라 리사이즈 중 매 픽셀 반응하지 않고, 같은 구간 안에서 사용자가 접거나 편 상태는 그대로 둔다. 첫 그리기(폭을 처음 알 때)는 건너뛴다.
  // 상태만 바꾸므로 대화·입력 중 글자는 그대로다(다시 마운트하지 않는다). 닫히는 층의 초점은 각 층이 토글 버튼으로 돌려준다(`Sidebar` `returnFocus`)
  // 근거 상세(U-18 추가 지시, 2026-11-24): 좁아지는 순간에만 함께 닫고(reducer), 넓어져도 다시 열지 않는다. 패널 안에 초점이 있었으면 그 결과의 진입 버튼으로 돌려준다
  const lastDesktop = useRef<boolean | null>(null);
  const evidenceOpenRef = useRef<string | null>(null);
  const panelFocused = useRef(false);
  useEffect(() => {
    evidenceOpenRef.current = shell.evidenceTurnId;
    if (shell.evidenceTurnId === null) panelFocused.current = false;
  });
  // 폭 변화 효과(아래)와 같은 커밋에서 그리기 전에 돈다(layout effect)
  useLayoutEffect(() => {
    if (desktop === null) return;
    const previous = lastDesktop.current;
    lastDesktop.current = desktop;
    if (previous === null || previous === desktop) return;
    const turnId = evidenceOpenRef.current;
    // 패널은 이 효과 전에 이미 그리지 않으므로(같은 커밋) 초점 위치는 `panelFocused`(패널의 focus/blur)와 지금 초점이 body로 떨어졌는지로 판단한다
    const active = document.activeElement;
    const focusInPanel = !desktop && turnId !== null && panelFocused.current && (active === null || active === document.body);
    dispatch({ type: "viewportCrossed", desktop });
    if (focusInPanel) {
      window.setTimeout(() => main.current?.querySelector<HTMLElement>(`[data-turn="${turnId}"] [data-testid="evidence-entry"]`)?.focus(), 0);
    }
  }, [desktop]);

  // 데스크톱 구간 안의 폭 변화(FE-17 U-18 추가 지시 2): 근거 상세 + 펼친 사이드바가 밀 수 있던 폭에서 밀 수 없는 폭(1232 → 1231 이하)으로 줄면
  // 사이드바를 레일로 접어 dim(스크림)이 나오지 않게 한다. 판정은 reducer가 하고, 해당하지 않으면 같은 상태라 다시 그리지 않는다.
  // 넓어져도 다시 펼치지 않고(단방향이라 경계에서 깜박이지 않는다), 사용자가 밀 수 없는 폭에서 직접 펼친 오버레이는 그대로 둔다.
  // 그리기 전에(layout effect) 접어 오버레이·dim이 한 프레임도 칠해지지 않게 한다
  const lastWidth = useRef<number | null>(null);
  useLayoutEffect(() => {
    if (width === null) return;
    const from = lastWidth.current;
    lastWidth.current = width;
    if (from !== null && from !== width) dispatch({ type: "viewportResized", from, to: width });
  }, [width]);

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

  /**
   * 요청 `context`의 나이·임신 칸: 나이는 고른 대상("누가 먹나요")의 연령대(게스트·미선택은 비움), 임신 여부는 토글 값이다
   * (일반인 false·임산부 true, FE-11-12 A: null을 보내지 않는다). 토글을 숨긴 대상(남성, FE-11-09 C)은 늘 false다. 값 전달만 하고 대화는 저장하지 않는다
   */
  const targetContext = () => {
    const state = account.getState();
    const target = selectTargetProfile(state);
    return { age: profileToContext(target, hasHealthConsent(state.me)).age, pregnant: !hidesPregnancyToggle(target) && store.getState().context.pregnant === true };
  };
  /** 지금 대화로 보내는 순간의 대상을 적어 둔다(FE-17 U-29: 이 대화로 돌아올 때 대상을 되살린다) */
  const noteTarget = () => {
    const { currentId, setScreen } = store.getState();
    setScreen(currentId, { targetProfileId: account.getState().targetProfileId });
  };
  // 새 질문: 이번 질문의 되묻기 답은 없다(`confirmed_drugs=[]`, AG-21-02 A). 이전 차례의 선택(`priorDrugs`)은 그대로 실린다
  const send = (question: string) => {
    store.getState().setContext({ ...targetContext(), confirmedDrugs: [] });
    noteTarget();
    void store.getState().send(question);
  };
  /**
   * 새 대화(사이드바 `새 질문`, FE-17 U-21 추가의 대상 변경). FE-17 U-29(2026-11-24): 지금 대화는 지우지 않고 이번 탭의 목록에 남긴다.
   * 진행 중인 응답은 끊지 않고 그 대화에 계속 쌓인다(스토어의 대화별 요청). 떠나는 대화의 근거 상세 열림 상태는 돌아올 때를 위해 적어 둔다.
   * 새 대화의 토글은 대상 프로필 값으로(게스트는 일반인). 대상을 막 바꾼 경우에는 렌더 시점 값(`profilePregnant`)이 이전 대상의 것이므로
   * 지금 스토어 상태로 다시 계산한다(`pregnantOf`)
   */
  const pregnantOf = (state: ReturnType<AccountStore["getState"]>) => {
    const target = selectTargetProfile(state);
    return !hidesPregnancyToggle(target) && profileToContext(target, hasHealthConsent(state.me)).pregnant === true;
  };
  const leaveChat = () => {
    const { currentId, setScreen } = store.getState();
    setScreen(currentId, { evidenceTurnId: shell.evidenceTurnId });
  };
  const newChat = () => {
    leaveChat();
    store.getState().startNew();
    store.getState().setContext({ pregnant: pregnantOf(account.getState()) });
    setPregnancyNote({ key: "", hint: false, error: null });
    dispatch({ type: "newChat" });
  };
  /**
   * 이번 탭의 다른 대화로 옮긴다(사이드바 `지금 대화` 항목, FE-17 U-29). 질문·답·고른 후보(차례 id별)·묶음은 스토어·화면 상태에 그대로 있어 다시 보이고,
   * 떠날 때 열려 있던 근거 상세는 넓은 폭에서 다시 연다. 그 대화에서 질문할 때의 대상이 지금 대상과 다르면 그 대상으로 되돌린다
   * (프로필이 그사이 지워졌으면 지금 대상을 그대로 둔다). 진행 중이던 응답은 끊지 않는다
   */
  const selectChat = (id: string) => {
    const state = store.getState();
    if (id === state.currentId) {
      dispatch({ type: "closeDrawer" });
      return;
    }
    const screen = state.conversations.find((conversation) => conversation.id === id)?.screen;
    if (!screen) return;
    leaveChat();
    state.switchTo(id);
    const target = screen.targetProfileId;
    const accountState = account.getState();
    const restorable = target === null || (target !== undefined && accountState.profiles.some((profile) => profile.profile_id === target));
    if (accountState.status === "member" && restorable && target !== accountState.targetProfileId) {
      skipPregnantSync.current = true;
      accountState.setTarget(target ?? null);
    }
    setPregnancyNote({ key: "", hint: false, error: null });
    dispatch({ type: "restoreChat", evidenceTurnId: screen.evidenceTurnId, width });
  };
  /**
   * 임신 여부 토글 변경(FE-11-13·14 A): 대화 값은 바로 바꾼다. 로그인 + 건강 정보 동의 + 대상 프로필이 있으면 그 프로필의 `pregnancy_status`를
   * PATCH(임산부 → pregnant, 일반인 → not_pregnant). 동의 없음·게스트는 저장하지 않고 안내 한 줄. 서버가 422 `HEALTH_CONSENT_REQUIRED`를 주면 같은 동작.
   * 그 밖의 실패는 대화 값을 유지하고 짧게 알린다. 대상이 없는 로그인 사용자는 저장할 프로필이 없어 이 대화에만 적용한다(안내 없음)
   */
  const changePregnant = (next: boolean) => {
    store.getState().setContext({ pregnant: next });
    const state = account.getState();
    const consented = state.status === "member" && hasHealthConsent(state.me);
    const target = selectTargetProfile(state);
    const key = pregnancyNoteKey;
    setPregnancyNote({ key, hint: !consented, error: null });
    if (!consented || target === null) return;
    const seq = (pregnancySaveSeq.current += 1);
    void state.savePregnancy(target.profile_id, next ? "pregnant" : "not_pregnant").then((failure) => {
      if (!failure || seq !== pregnancySaveSeq.current) return; // 더 나중 변경이 있으면 지난 결과는 무시한다
      setPregnancyNote(failure.code === "HEALTH_CONSENT_REQUIRED" ? { key, hint: true, error: null } : { key, hint: false, error: failure });
    });
  };
  /**
   * 대상 변경(칩·시작 안내·계정 메뉴가 모두 이 함수를 쓴다). 대상이 바뀌면 이전 선택 힌트를 비운다(AG-21-03 A: 다른 사람의 약을 같은 이름으로 확인하지 않게).
   * FE-17 U-21 추가(2026-11-24): 질문이 한 번이라도 오간 대화에서 **다른** 대상으로 바꾸면 그 대화를 잇지 않고 새 대화를 연다(`새 대화` 버튼과 같은 정리,
   * 스트리밍 중이면 진행 응답을 끊는다). 같은 대상을 다시 고르거나 시작 화면(대화 없음)이면 대상만 바꾼다
   */
  const changeTarget = (profileId: string | null) => {
    const current = account.getState().targetProfileId;
    const changed = profileId !== current;
    const inConversation = store.getState().turns.length > 0;
    // 대화 중이면 새 대화가 빈 묶음으로 시작한다: 떠나는 대화의 이전 선택은 그 대화에 남긴다(FE-17 U-29, 돌아가면 그 대상으로 이어 묻는다)
    if (changed && !inConversation) store.getState().setContext({ priorDrugs: [] });
    account.getState().setTarget(profileId);
    if (changed && inConversation) newChat();
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
    noteTarget();
    void store.getState().send(turn.question, resendBubbleText(names));
  };
  const focusInput = () => main.current?.querySelector("textarea")?.focus();
  /**
   * 사진 확인 카드 승인(FE-05, 〔D7〕A): 승인 전에는 `/chat`을 부르지 않고, 승인하면 `buildChatInput` 결과로 기존 전송을 한 번 부른다.
   * 후보를 고른 약만 이번 질문의 `confirmedDrugs`로 싣고(FE-09-05 A 모양), 고르지 않은 약은 질문 글자로만 들어가 기존 식별·되묻기 경로를 탄다
   */
  const sendFromPhoto = (input: ChatInputFromPhoto) => {
    store.getState().setContext({ ...targetContext(), confirmedDrugs: input.confirmedDrugs });
    noteTarget();
    void store.getState().send(input.question);
  };
  const openPhoto = () => {
    photoCloseFocus.current = "entry";
    setPhotoOpen(true);
  };
  const photoTypeInstead = () => {
    photoCloseFocus.current = "input";
    setPhotoOpen(false);
  };
  const photoClosed = () => {
    if (photoCloseFocus.current === "input") focusInput();
    else main.current?.querySelector<HTMLElement>('[data-testid="photo-entry"]')?.focus();
  };
  // 계정 모달을 열 때 드로어·사이드바 오버레이는 닫는다(층을 겹치지 않는다)
  const openAccount = () => {
    dispatch({ type: "closeDrawer" });
    if (layout.sidebarOverlay) dispatch({ type: "collapseSidebar" });
    openAccountModal(account);
  };
  // 약관·정책 열람 화면을 열 때도 드로어·사이드바 오버레이는 닫는다(층을 겹치지 않는다)
  const openLegal = () => {
    dispatch({ type: "closeDrawer" });
    if (layout.sidebarOverlay) dispatch({ type: "collapseSidebar" });
    setLegalOpen(true);
  };
  // 열람 화면이 닫히면 초점은 연 계정 메뉴 버튼으로. 그 버튼이 사라졌으면(드로어·오버레이 안 버튼) ☰·사이드바 버튼으로
  const legalClosed = (event: Event) => {
    event.preventDefault();
    // 셀렉터를 하나씩 찾는다(한 셀렉터로 묶으면 문서 순서상 앞에 있는 사이드바 버튼이 먼저 잡힌다)
    for (const testId of ["account-menu-button", "menu-button", "sidebar-toggle"]) {
      const target = layer?.querySelector<HTMLElement>(`[data-testid="${testId}"]`);
      if (target) {
        target.focus();
        return;
      }
    }
  };
  const startGuest = () => {
    account.getState().startGuest();
    focusInput();
  };
  // 계정 자리는 항상 그린다: 게스트도 메뉴에서 화면 모드·약관·정책을 연다(계정 기능이 꺼져 있으면 "로그인/가입" 항목만 빠진다)
  // 대상 프로필 고르기: 회원 + 프로필이 있을 때만(게스트·프로필 없음은 칩·시작 화면 안내 없이 같은 입력창 배치). 계정 버튼 메뉴·입력창 칩·시작 화면 안내가 같은 값을 쓴다
  const targetChoice = member && profiles.length > 0 ? { profiles, value: targetProfileId, onChange: changeTarget } : undefined;
  const menuProps = { member, accountEnabled, container: layer, onOpen: openAccount, onLogout: () => void account.getState().logout(), onLegal: openLegal, target: targetChoice };
  const accountMenu = <AccountMenu {...menuProps} />;

  const first = turns[0];
  // 사이드바 `지금 대화` 목록(FE-17 U-29): 질문이 있는 대화만, 최근에 만든 대화가 위. 제목은 첫 질문(지금 규칙 그대로), 지금 대화는 강조
  const chats = conversations
    .filter((conversation) => conversation.turns.length > 0)
    .map((conversation) => ({ id: conversation.id, title: conversation.turns[0].question, current: conversation.id === currentChatId }))
    .reverse();
  const sidebar = { chats, onNewChat: newChat, onSelectChat: selectChat, account: accountMenu };
  /** 내용 폭 열(FE-17 U-27): 스크롤 영역 안쪽 래퍼와 입력 영역이 같은 폭·좌우 여백을 쓴다. 스크롤 컨테이너 자체는 본문 전체 폭이다 */
  const column = cn("mx-auto w-full", layout.desktop ? "max-w-[880px] px-6" : "max-w-[760px] px-3");

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
                <div className="mt-auto flex flex-col items-center gap-1.5">
                  <AccountMenu {...menuProps} variant="icon" />
                </div>
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
          {/* 합성 데이터 데모 표시(BE-13-07 A): 목(MSW) 빌드에서만 머리줄 아래 한 줄. 실서버 모드에서는 DOM에 없다. 마스코트 금지 영역, 색은 토큰만 */}
          {isApiMockingEnabled() && (
            <NoMascotZone>
              <div className="flex-none px-3 pb-1">
                <p role="note" data-testid="demo-notice" className="m-0 rounded-xl bg-fixed px-3 py-1.5 text-center text-xs leading-[17px] text-ink-2 [word-break:keep-all]">
                  {SYNTHETIC_DEMO_NOTICE}
                </p>
              </div>
            </NoMascotZone>
          )}
          {/* 스크롤 영역과 내용 폭 분리(FE-17 U-27): 스크롤 컨테이너(`home`·`chat-thread`)는 본문(main) 전체 폭을 차지해 스크롤바가 본문 오른쪽 가장자리
              (근거 상세가 열리면 패널 왼쪽)에 붙고, 휠·터치 스크롤도 본문 어디서나 된다. 내용 폭 제한(넓은 폭 880px·좁은 폭 760px, 좌우 여백 포함)은
              그 안쪽 래퍼(`column`)와 입력 영역(`dock`)이 같은 값으로 나눠 갖는다.
              대화 중(U-27 추가 지시 2)에는 `chat-thread`가 이 영역의 전체 높이를 차지하고(스크롤바가 위~아래 끝까지), 입력 영역은 같은 영역 하단에 겹쳐 고정된다
              (`relative` 기준). 시작 화면(`home`)은 입력창 위치가 지금 그대로다(입력 영역이 흐름 안에 있다) */}
          <div data-testid="main-body" className="relative flex min-h-0 w-full flex-1 flex-col gap-2">
            {turns.length === 0 ? (
              // 내용이 화면보다 길면(좁은 폭 + 기본 대상 안내, FE-17 U-08) 가운데 정렬이 위쪽을 스크롤 밖으로 잘라내지 않게 `safe` 가운데 정렬이다.
              // 바깥(`home`)이 본문 전체 폭 스크롤이고, 안쪽 래퍼가 남은 높이를 채운 채 가운데 정렬한다(내용이 더 길면 내용 높이만큼 늘어 바깥이 스크롤한다)
              <div data-testid="home" className="flex min-h-0 flex-1 flex-col overflow-y-auto">
                <div data-testid="home-column" className={cn(column, "flex shrink-0 grow flex-col justify-center-safe gap-4 py-2")}>
                  <HomeHero />
                  {/* 기본 대상 안내(FE-17 U-08): 로그인 + 프로필이 있을 때만, 병아리 이미지 아래에 지금 대상과 `게스트로 이용`(프로필 상태, U-23)·`변경`(게스트 상태, U-22: 칩과 같은 목록)을 둔다.
                      고르면 대상이 바뀌고(서버 기본 대상도 저장) 초점은 질문 칸으로 간다. 대화가 시작되면 이 영역째 사라진다 */}
                  {targetChoice && (
                    <StartTargetNotice
                      profiles={targetChoice.profiles}
                      value={targetChoice.value}
                      onChange={changeTarget}
                      onSettled={focusInput}
                      container={layer}
                    />
                  )}
                  {/* 진입 선택: 게스트로 시작(주) / 로그인·가입(보조). 누르지 않아도 아래 입력창으로 바로 질문할 수 있다.
                      로그인 확정 전에는 같은 높이(44px 버튼 줄)의 빈 자리만 둔다(U-22 추가: 로그인 사용자에게 게스트용 버튼이 한 순간도 보이지 않게, 글자 없음) */}
                  {authPending ? (
                    <div aria-hidden="true" data-testid="start-account-pending" className="mx-auto h-11 w-full max-w-[360px] flex-none" />
                  ) : (
                    accountEnabled && !member && !entryDismissed && <EntryChoice onGuest={startGuest} onLogin={openAccount} />
                  )}
                  <ExampleChips onPick={(question) => send(question)} />
                </div>
              </div>
            ) : (
              <Conversation
                turns={turns}
                hasEmergency={emergency !== null}
                evidenceTurnId={evidenceResponse ? shell.evidenceTurnId : null}
                entryLabelMode={layout.entryLabelMode}
                picked={picked}
                onOpenEvidence={(turnId) => dispatch({ type: "openEvidence", turnId, width })}
                onRetry={(turnId) => void store.getState().retry(turnId)}
                onPick={(turnId, candidate) => setPicked((prev) => ({ ...prev, [turnId]: { ...prev[turnId], [candidate.input_name]: candidate } }))}
                onOther={focusInput}
                onResend={resend}
                columnClassName={column}
                bottomInset={dockHeight}
                onScrollbarWidth={setThreadScrollbar}
              />
            )}
            {/* 접히지 않는 고정 영역: 입력창 → 통합 고지(FE-17 U-02). 고정 안내는 U-26-1로 각 답 아래로 옮겼다.
                대화 중(FE-17 U-27 추가 지시 2): 대화 스크롤 영역 하단에 겹쳐 고정(`absolute bottom-0`)되고 대화가 그 뒤로 스크롤한다. 단색 배경 + 위쪽 짧은 페이드로
                입력창 뒤로 지나가는 글자가 어색하게 잘려 보이지 않게 한다. 오른쪽은 스크롤바 폭만큼 비워(스크롤바를 덮지 않음) 내용 열과 같은 가운데에 놓인다.
                같은 요소를 시작 화면·대화에서 그대로 쓴다(입력창이 다시 만들어지지 않아 입력·초점이 이어진다) */}
            <div
              ref={setDockEl}
              data-testid="dock"
              data-overlay={turns.length > 0 ? "" : undefined}
              style={turns.length > 0 ? { right: threadScrollbar } : undefined}
              className={cn(
                column,
                "flex flex-none flex-col gap-1.5 bg-bg pb-[max(14px,env(safe-area-inset-bottom,0px))]",
                turns.length > 0 && "absolute inset-x-0 bottom-0 z-10",
              )}
            >
              {/* 임신 여부 토글은 대상이 남성 프로필이면 그리지 않는다(FE-11-09 C). 안내·오류 줄도 토글과 함께 빠진다.
                  대상 프로필 칩은 로그인하고 프로필이 있을 때만 입력창 안에 둔다. 게스트·프로필 없음도 같은 두 줄 배치다(FE-17 U-09, 칩만 없다).
                  고지는 입력창 아래 통합 고지 한 단락(FE-17 U-02, `ChatInput`)이다. 시작 화면 119 안내 줄은 없다(FE-17 U-04: 119는 머리줄·응급 배너 두 곳) */}
              <ChatInput
                onSend={(question) => send(question)}
                onPhoto={openPhoto}
                target={targetChoice && <TargetChip {...targetChoice} container={layer} />}
                pregnancy={
                  pregnancyHidden
                    ? undefined
                    : {
                        value: pregnant,
                        onChange: changePregnant,
                        hint: pregnancyHint ? PREGNANCY_SAVE_CONSENT_HINT : null,
                        error: pregnancyError ? failureMessage(pregnancyError) : null,
                      }
                }
              />
              {/* 입력 영역 위 짧은 페이드(대화 중에만, 보조기기에는 숨김). 위치는 절대 배치라 자식 순서와 무관하고, 입력 폼이 첫 자식으로 남게 맨 뒤에 둔다 */}
              {turns.length > 0 && <div aria-hidden="true" data-testid="dock-fade" className="pointer-events-none absolute inset-x-0 bottom-full h-4 bg-linear-to-t from-bg to-transparent" />}
            </div>
          </div>
        </main>
        {layout.panelOpen && evidenceResponse && (
          <div
            inert={layout.sidebarOverlay}
            data-testid="panel-column"
            className="h-full w-[400px] flex-none"
            onFocus={() => {
              panelFocused.current = true;
            }}
            onBlur={(event) => {
              if (event.relatedTarget) panelFocused.current = false;
            }}
          >
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
            // 응급이면 배너 아래 영역에만 그린다(사용자 결정 2026-11-16 후보 5 B). 아니면 화면 전체(기존 동작). 시트 안에 119 진입점은 두지 않는다(FE-17 U-04)
            container={emergency ? layer : undefined}
          >
            {evidenceResponse && <EvidenceDetail response={evidenceResponse} />}
          </EvidencePanel>
        )}
        {accountEnabled && <AccountModal store={account} container={layer} hasEmergency={emergency !== null} />}
        {/* 사진 입력 모달(FE-05 사진 부분): 배너 아래 영역에만 그린다. 승인(`이대로 확인`)만 `/chat`을 부르고 `닫기`·Esc·`글자로 입력`은 버린다(H19) */}
        <PhotoModal
          open={photoOpen}
          onOpenChange={setPhotoOpen}
          onConfirm={sendFromPhoto}
          onTypeInstead={photoTypeInstead}
          onCloseAutoFocus={photoClosed}
          container={layer}
          hasEmergency={emergency !== null}
        />
        {/* 약관·정책 열람 화면(계정 메뉴 항목): 배너 아래 영역에만 그린다. 게스트도 연다 */}
        <LegalDialog open={legalOpen} onOpenChange={setLegalOpen} container={layer} member={member} onCloseAutoFocus={legalClosed} />
        <SidebarOverlay open={layout.sidebarOverlay} onClose={() => dispatch({ type: "collapseSidebar" })} container={layer} {...sidebar} />
        <MenuDrawer open={!layout.desktop && shell.drawerOpen} onClose={() => dispatch({ type: "closeDrawer" })} container={layer} {...sidebar} />
      </div>
    </div>
  );
}
