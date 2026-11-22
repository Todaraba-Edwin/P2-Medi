// 계정 스토어(Zustand, 메모리 전용. persist를 쓰지 않는다: FE-01-08 A, FE-04 할 일 6).
// 동의·프로필(건강 정보 포함)은 이 메모리에만 있고 새로고침하면 사라진다. 이 스토어는 브라우저 저장소·쿠키·콘솔에 아무것도 남기지 않는다.
// 로그인 세션만 로그인 모듈(`@/lib/api/auth`)의 기본 동작(쿠키)으로 남고, 새로고침하면 `bootstrap()`이 그 세션으로 서버 값을 다시 읽는다.
// 서버 호출은 `@/lib/api/account`(BE-11 계약) 한 곳을 거친다.
import { useStore } from "zustand";
import { createStore } from "zustand/vanilla";
import type { StoreApi } from "zustand/vanilla";
import { AccountApiError, FAMILY_PROFILE_MAX, SELF_PROFILE_MAX, accountApi, isConsentDocType } from "@/lib/api/account";
import type { AccountApi, AccountErrorKind, ConsentChannel, ConsentDocType, ConsentItem, LegalDoc, Me, PregnancyStatus, Profile, ProfileDraft, SocialProvider } from "@/lib/api/account";

/** 계정 모달의 화면(단계). `flow`의 마지막이 지금 화면이다 */
export type AccountStep = "login" | "signup" | "consent" | "profiles" | "profile-form";

/** 실패 한 건. 서버가 준 코드와 칸 이름(`fields`)만 싣고 입력 값은 싣지 않는다 */
export interface AccountFailure {
  kind: AccountErrorKind | "unknown";
  status: number;
  code: string | null;
  fields: readonly string[];
}

/** 동의 화면에서 고른 값(동의 대상 문서만. 고지 문서 `privacy_policy`는 없다) */
export type ConsentChoices = Partial<Record<ConsentDocType, boolean>>;

/** 프로필 폼이 다루는 대상: 새로 만들기(`profileId` null) 또는 고치기 */
export interface ProfileFormTarget {
  profileId: string | null;
  /** 본인 프로필인지(관계가 `self`로 고정된다) */
  self: boolean;
}

export type LegalDocsStatus = "idle" | "loading" | "ready" | "failed";

/** `signup-confirm`: 가입 확인 메일을 보냈고 아직 로그인되지 않았다 */
export type AccountNotice = "signup-confirm";

export interface AccountState {
  /** 로그인 여부. 게스트가 기본이고 게스트는 아무것도 저장하지 않는다 */
  status: "guest" | "member";
  /**
   * 서버가 아는 계정 상태. 로그인했어도 계정 서버가 아직 답하지 못하면(501 미설정·503 장애) null이다:
   * 그때는 로그인 표시·로그아웃만 되고 동의·프로필은 서버가 답한 뒤에 쓸 수 있다(BE-11-20 A·BE-11-23 A)
   */
  me: Me | null;
  profiles: Profile[];
  legalDocs: LegalDoc[];
  legalDocsStatus: LegalDocsStatus;
  /** 질문할 때 고른 대상("누가 먹나요"). 고르지 않았으면 null */
  targetProfileId: string | null;
  /** 계정 모달의 단계 이력. 비어 있으면 닫혀 있다. 길이가 2 이상일 때만 `<`(뒤로)가 있다(PRD-13-02 A) */
  flow: AccountStep[];
  form: ProfileFormTarget | null;
  pending: boolean;
  failure: AccountFailure | null;
  /** 오류가 아닌 안내 한 줄(가입 확인 메일을 보냈다). 단계를 옮기거나 닫으면 지운다 */
  notice: AccountNotice | null;
  /** 시작 화면에서 "게스트로 시작"을 눌렀다(진입 선택을 접는다) */
  entryDismissed: boolean;

  /** 화면이 뜰 때 한 번: 로그인 세션이 있으면 로그인 상태로 만든다. 실패해도 오류를 띄우지 않고 지금 상태를 지킨다 */
  bootstrap: () => Promise<void>;
  /** 로그인 콜백이 실패해 돌아왔다: 로그인 화면을 열고 실패 코드에 맞는 안내를 보인다 */
  failLogin: (code: string) => void;
  startGuest: () => void;
  /** 계정 모달을 연다: 게스트 → 로그인, 동의 전 → 동의, 그 밖 → 프로필 */
  open: () => void;
  close: () => void;
  back: () => void;
  go: (step: AccountStep) => void;
  editProfile: (target: ProfileFormTarget) => void;
  loginEmail: (email: string, password: string) => Promise<boolean>;
  signupEmail: (email: string, password: string) => Promise<boolean>;
  loginSocial: (provider: SocialProvider) => Promise<boolean>;
  logout: () => Promise<boolean>;
  /** `force`면 이미 받았어도 다시 받는다(문서 버전이 바뀌었을 때) */
  loadLegalDocs: (force?: boolean) => Promise<void>;
  /** 문서별 동의 여부에서 달라진 것만 동의·철회로 보낸다. 필수 문서를 모두 동의하지 않았으면 보내지 않는다 */
  submitConsents: (agreed: ConsentChoices) => Promise<boolean>;
  saveProfile: (draft: ProfileDraft) => Promise<boolean>;
  /**
   * 질문 화면의 임신 여부 토글로 대상 프로필의 `pregnancy_status`만 바꾼다(FE-11-13). 모달의 `pending`·`failure`는 건드리지 않고
   * 실패를 돌려준다(성공은 null). 성공하면 프로필 목록을 갱신해 프로필 화면에서 바뀐 값이 보인다
   */
  savePregnancy: (profileId: string, status: PregnancyStatus) => Promise<AccountFailure | null>;
  removeProfile: (id: string) => Promise<boolean>;
  /** 탈퇴 */
  withdraw: () => Promise<boolean>;
  setTarget: (id: string | null) => void;
}

export type AccountStore = StoreApi<AccountState>;

const guest = { status: "guest", me: null, profiles: [] as Profile[], targetProfileId: null, form: null } as const;

function toFailure(error: unknown): AccountFailure {
  if (error instanceof AccountApiError) return { kind: error.kind, status: error.status, code: error.code, fields: error.fields };
  return { kind: "unknown", status: 0, code: null, fields: [] };
}

/** 계정 서버가 아직 답하지 못한다(501 미설정·503 장애). 로그아웃이 아니다(BE-11-20 A) */
const isServiceDown = (error: unknown) => error instanceof AccountApiError && error.kind === "http" && (error.status === 501 || error.status === 503);

/** 로그인은 했지만 계정 서버가 답하지 못해 동의·프로필을 아직 쓸 수 없는가 */
export const accountUnavailable = (state: Pick<AccountState, "status" | "me">) => state.status === "member" && state.me === null;

// ---------------------------------------------------------------- 상태에서 읽는 값(순수 함수)
/** 건강 정보(임신 여부·복용 약)를 지금 저장할 수 있는가(서버 값 `health_consent_active`: 동의 + 재동의 대기 아님) */
export function hasHealthConsent(me: Me | null): boolean {
  return me?.health_consent_active === true;
}

/** 이 문서에 지금 유효하게 동의해 있는가(동의 기록이 있고 재동의 대기가 아니다) */
export function consentActive(me: Me | null, docType: ConsentDocType): boolean {
  const state = me?.consents.find((consent) => consent.doc_type === docType);
  return state !== undefined && !state.needs_consent && !state.needs_reconsent;
}

/** 필수 동의(약관·개인정보)가 남아 있어 동의 화면이 먼저인가(서버가 계산한 온보딩 단계) */
export const needsConsentStep = (me: Me | null) => me?.onboarding_step === "consent";

/** 동의 대상 문서(체크가 있는 문서). 고지 문서(`privacy_policy`)는 빠진다 */
export const consentDocs = (docs: readonly LegalDoc[]) => docs.filter((doc): doc is LegalDoc & { doc_type: ConsentDocType } => isConsentDocType(doc.doc_type));

/** 필수 동의 문서에 모두 동의했는가 */
export function requiredAgreed(docs: readonly LegalDoc[], agreed: ConsentChoices): boolean {
  const targets = consentDocs(docs);
  return targets.length > 0 && targets.filter((doc) => doc.required).every((doc) => agreed[doc.doc_type] === true);
}

/**
 * 고른 값과 지금 상태가 다른 문서만 요청 항목으로 만든다: 새로 동의(재동의 포함) → `agree`, 동의해 둔 선택 문서를 끔 → `withdraw`.
 * 버전은 사용자가 화면에서 본 문서의 버전이다(그 사이 문서가 바뀌었으면 서버가 409 `VERSION_MISMATCH`로 막는다).
 */
export function consentItems(docs: readonly LegalDoc[], me: Me | null, agreed: ConsentChoices): ConsentItem[] {
  const items: ConsentItem[] = [];
  for (const doc of consentDocs(docs)) {
    const want = agreed[doc.doc_type] === true;
    const state = me?.consents.find((consent) => consent.doc_type === doc.doc_type);
    if (want && !consentActive(me, doc.doc_type)) items.push({ doc_type: doc.doc_type, version: doc.version, action: "agree" });
    else if (!want && state !== undefined && !state.needs_consent) items.push({ doc_type: doc.doc_type, version: doc.version, action: "withdraw" });
  }
  return items;
}

/** 동의를 받은 자리: 재동의가 섞여 있으면 `reconsent`, 첫 동의(온보딩 단계 `consent`)면 `onboarding`, 그 밖은 `settings` */
export function consentChannel(me: Me | null, items: readonly ConsentItem[]): ConsentChannel {
  const reconsent = items.some((item) => item.action === "agree" && me?.consents.find((consent) => consent.doc_type === item.doc_type)?.needs_reconsent === true);
  return reconsent ? "reconsent" : needsConsentStep(me) ? "onboarding" : "settings";
}

export const selfProfiles = (profiles: readonly Profile[]) => profiles.filter((profile) => profile.relation === "self");
export const familyProfiles = (profiles: readonly Profile[]) => profiles.filter((profile) => profile.relation !== "self");
export const canAddSelf = (profiles: readonly Profile[]) => selfProfiles(profiles).length < SELF_PROFILE_MAX;
/** 가족은 3명까지: 4번째 추가는 막는다 */
export const canAddFamily = (profiles: readonly Profile[]) => familyProfiles(profiles).length < FAMILY_PROFILE_MAX;

export function selectTargetProfile(state: Pick<AccountState, "status" | "profiles" | "targetProfileId">): Profile | null {
  if (state.status !== "member") return null;
  return state.profiles.find((profile) => profile.profile_id === state.targetProfileId) ?? null;
}

/**
 * 질문 입력창의 임신 여부 토글을 숨기는가(FE-11-09 C, GROUP-03 3단계): **대상 프로필의 성별이 남성일 때만** 숨긴다.
 * 여성·성별 미입력·대상 없음(게스트·선택 안 함)은 보인다. 숨겼을 때 `context.pregnant`는 false다(FE-11-12 A, `AppShell`이 보장).
 * 성별은 여기서 토글 표시에만 쓰고 `/chat` 요청에는 싣지 않는다(S10). 요청을 만드는 `profile-context.ts`에는 두지 않는다(정적 검사)
 */
export function hidesPregnancyToggle(profile: Profile | null): boolean {
  return profile?.sex === "male";
}

// ---------------------------------------------------------------- 스토어
export function createAccountStore({ api = accountApi }: { api?: AccountApi } = {}): AccountStore {
  return createStore<AccountState>()((set, get) => {
    /** 서버가 아는 로그인 상태를 읽어 온다. 로그인돼 있으면 true */
    const refreshSession = async (): Promise<boolean> => {
      const me = await api.fetchMe();
      if (!me) {
        set({ ...guest });
        return false;
      }
      const profiles = await api.fetchProfiles();
      set((state) => ({
        status: "member",
        me,
        profiles,
        targetProfileId: profiles.some((profile) => profile.profile_id === state.targetProfileId) ? state.targetProfileId : null,
      }));
      return true;
    };

    const run = async (task: () => Promise<void>): Promise<boolean> => {
      if (get().pending) return false;
      set({ pending: true, failure: null });
      try {
        await task();
        return true;
      } catch (error) {
        set({ failure: toFailure(error) });
        return false;
      } finally {
        set({ pending: false });
      }
    };

    /**
     * 로그인 세션은 있는데 계정 서버가 답하지 못했을 때(501·503): 로그인 상태만 보인다(`me`는 null).
     * 이미 로그인 상태면 그대로 두고, 세션이 없으면 아무것도 바꾸지 않는다. 로그인 상태가 됐으면 true
     */
    const keepSignedIn = async (): Promise<boolean> => {
      if (get().status === "member") return true;
      if (!(await api.hasSession().catch(() => false))) return false;
      set({ ...guest, status: "member" });
      return true;
    };

    /** 로그인에 성공한 뒤: `/api/me`를 반영하고 다음 단계로 간다 */
    const afterLogin = async () => {
      try {
        if (!(await refreshSession())) throw new AccountApiError("http", 401, null);
      } catch (error) {
        // 로그인은 됐는데 계정 서버가 준비 전이면 로그인 화면에 붙잡아 두지 않는다: 프로필 화면에서 준비 중 안내를 보인다
        if (isServiceDown(error) && (await keepSignedIn())) set({ flow: ["profiles"] });
        throw error;
      }
      const consentFirst = needsConsentStep(get().me);
      set((state) => ({ flow: consentFirst ? [...state.flow, "consent"] : ["profiles"] }));
    };

    return {
      ...guest,
      legalDocs: [],
      legalDocsStatus: "idle",
      flow: [],
      pending: false,
      failure: null,
      notice: null,
      entryDismissed: false,

      bootstrap: async () => {
        try {
          await refreshSession();
        } catch (error) {
          // 서버가 없거나 501(미설정)·503(검증 서버 장애)이면 오류를 띄우지도, 로그아웃시키지도 않는다(BE-11-20 A).
          // 로그인 세션이 있으면 로그인 상태만 보인다(계정 표시·로그아웃은 되고 동의·프로필은 서버가 답한 뒤에)
          if (isServiceDown(error)) await keepSignedIn();
        }
      },

      failLogin: (code) => set({ flow: ["login"], form: null, notice: null, failure: { kind: "http", status: 400, code, fields: [] } }),

      startGuest: () => set({ entryDismissed: true }),

      open: () => {
        const { status, me } = get();
        const first: AccountStep = status !== "member" ? "login" : needsConsentStep(me) ? "consent" : "profiles";
        set({ flow: [first], failure: null, notice: null, form: null });
        // 로그인했는데 계정 서버 값이 아직 없으면 다시 읽어 본다(그 사이 서버가 준비됐을 수 있다)
        if (accountUnavailable(get())) void get().bootstrap();
      },
      close: () => set({ flow: [], failure: null, notice: null, form: null }),
      back: () => set((state) => (state.flow.length > 1 ? { flow: state.flow.slice(0, -1), failure: null, notice: null } : state)),
      go: (step) => set((state) => ({ flow: [...state.flow, step], failure: null, notice: null })),
      editProfile: (target) => set((state) => ({ form: target, flow: [...state.flow, "profile-form"], failure: null, notice: null })),

      loginEmail: (email, password) =>
        run(async () => {
          await api.loginWithEmail(email, password);
          await afterLogin();
        }),

      signupEmail: (email, password) =>
        run(async () => {
          set({ notice: null });
          // 이메일 확인이 필요하면 아직 로그인되지 않았다: 가입 화면에 남아 안내만 보인다
          if ((await api.signupWithEmail(email, password)) === "confirm_email") set({ notice: "signup-confirm" });
          else await afterLogin();
        }),

      loginSocial: (provider) =>
        run(async () => {
          // `redirected`면 공급자 동의 화면으로 페이지가 옮겨 간다. `/auth/callback`을 거쳐 돌아온 뒤 `bootstrap()`이 상태를 읽는다
          if ((await api.startSocialLogin(provider)) === "completed") await afterLogin();
        }),

      logout: async () => {
        const ok = await run(() => api.logout());
        if (ok) set({ ...guest, flow: [] });
        return ok;
      },

      loadLegalDocs: async (force = false) => {
        const { legalDocsStatus } = get();
        if (legalDocsStatus === "loading" || (legalDocsStatus === "ready" && !force)) return;
        set({ legalDocsStatus: "loading" });
        try {
          set({ legalDocs: await api.fetchLegalDocs(), legalDocsStatus: "ready" });
        } catch {
          set({ legalDocsStatus: "failed" });
        }
      },

      submitConsents: async (agreed) => {
        const docs = get().legalDocs;
        if (!requiredAgreed(docs, agreed)) return false;
        const ok = await run(async () => {
          const items = consentItems(docs, get().me, agreed);
          if (items.length === 0) return; // 달라진 것이 없으면 보내지 않는다(서버는 빈 목록을 받지 않는다)
          const me = await api.postConsents(items, consentChannel(get().me, items));
          // 철회는 서버가 즉시 지운다(건강 동의 → 임신 여부·복용 약, 개인정보 동의 → 프로필): 프로필을 다시 읽어 화면에 남기지 않는다
          const profiles = await api.fetchProfiles();
          set((state) => ({ me, profiles, targetProfileId: profiles.some((profile) => profile.profile_id === state.targetProfileId) ? state.targetProfileId : null }));
        });
        // 그 사이 문서가 바뀌었으면(409) 새 본문을 다시 받아 보여 준다
        if (!ok && get().failure?.code === "VERSION_MISMATCH") void get().loadLegalDocs(true);
        // 프로필에서 동의를 다시 보러 왔으면 프로필로 돌아가고, 처음 동의면 프로필로 넘어간다
        if (ok) set((state) => ({ flow: state.flow.includes("profiles") ? state.flow.slice(0, state.flow.lastIndexOf("profiles") + 1) : [...state.flow, "profiles"] }));
        return ok;
      },

      saveProfile: async (draft) => {
        const target = get().form;
        if (!target) return false;
        const ok = await run(async () => {
          const saved = target.profileId === null ? await api.createProfile(draft) : await api.updateProfile(target.profileId, draft);
          set((state) => ({
            profiles: state.profiles.some((profile) => profile.profile_id === saved.profile_id)
              ? state.profiles.map((profile) => (profile.profile_id === saved.profile_id ? saved : profile))
              : [...state.profiles, saved],
          }));
        });
        if (ok) set((state) => ({ form: null, flow: state.flow.length > 1 ? state.flow.slice(0, -1) : ["profiles"] }));
        return ok;
      },

      savePregnancy: async (profileId, status) => {
        try {
          const saved = await api.updateProfilePregnancy(profileId, status);
          set((state) => ({ profiles: state.profiles.map((profile) => (profile.profile_id === saved.profile_id ? saved : profile)) }));
          return null;
        } catch (error) {
          return toFailure(error);
        }
      },

      removeProfile: (id) =>
        run(async () => {
          await api.deleteProfile(id);
          set((state) => ({
            profiles: state.profiles.filter((profile) => profile.profile_id !== id),
            targetProfileId: state.targetProfileId === id ? null : state.targetProfileId,
          }));
        }),

      withdraw: async () => {
        const ok = await run(() => api.deleteMe());
        if (ok) set({ ...guest, flow: [] });
        return ok;
      },

      setTarget: (id) => set({ targetProfileId: id }),
    };
  });
}

/** 앱 전체가 쓰는 스토어 하나 */
export const accountStore = createAccountStore();

export function useAccountStore<T>(selector: (state: AccountState) => T, store: AccountStore = accountStore): T {
  return useStore(store, selector);
}
