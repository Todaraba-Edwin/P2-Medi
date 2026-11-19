"use client";

import { useId, useState } from "react";
import Image from "next/image";
import { BrandLogo } from "@/components/BrandLogo";
import { Mascot } from "@/components/Mascot";
import { SOCIAL_PROVIDERS } from "@/lib/api/account";
import type { SocialProvider } from "@/lib/api/account";
import { cn } from "@/lib/utils";
import { isApiMockingEnabled } from "@/mocks";
import { useAccountStore } from "@/stores/account";
import {
  CONTINUE_AS_GUEST_LABEL,
  EMAIL_LABEL,
  EMAIL_LOGIN_HEADING,
  ERROR_EMAIL_FORMAT,
  ERROR_PASSWORD_EMPTY,
  LOGIN_DESCRIPTION,
  LOGIN_SUBMIT_LABEL,
  LOGIN_TITLE,
  MOCK_NOTE,
  PASSWORD_LABEL,
  SIGNUP_CONFIRM_NOTICE,
  SIGNUP_ENTRY_LABEL,
  SIGNUP_SUBMIT_LABEL,
  SIGNUP_TITLE,
  SOCIAL_HEADING,
  SOCIAL_LABELS,
} from "./copy";
import { EmergencyEntrySlot, FIELD_CLASS, FailureLine, PRIMARY_BUTTON, SECONDARY_BUTTON, SOCIAL_BUTTON, StepTitle, TEXT_BUTTON, useAccountModal } from "./parts";

/**
 * PRD-01-10 A(2026-11-19): 이메일 로그인·가입은 화면에서 숨긴다. 메일 인증을 갖춘 뒤 재검토한다.
 * `true`로 바꾸면 이메일 폼과 "이메일로 가입하기"(`signup` 단계 진입)가 다시 보인다. 스토어 동작·API 함수·문구는 그대로 남아 있다.
 */
const EMAIL_AUTH_ENABLED: boolean = false;

const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+$/;

/**
 * 소셜 로그인 버튼의 면: 각 회사가 배포한 그림을 그대로 쓴다(직접 그리지 않고 색·비율을 바꾸지 않는다. 크기는 원본 비율로만 맞춘다).
 * - Google: Sign in with Google 승인 아이콘 버튼(Light·Pill·글자 없음, 흰 바탕 + 회색 테두리 + 4색 G). 원본 40×40을 46×46으로 같은 비율 확대
 *   출처 https://developers.google.com/identity/branding-guidelines 의 signin-assets.zip(2026-11-19 받음)
 * - Kakao: 카카오 로그인 축약형 버튼(노랑 바탕 + 말풍선 심볼 + "로그인"), 원본 112×46 그대로.
 *   카카오 디자인 가이드는 레이블을 완성형·축약형으로만 두고 심볼만 쓰는 형태를 허용 목록에 두지 않아, 허용되는 가장 짧은 형태(축약형)를 쓴다
 *   출처 https://developers.kakao.com/tool/resource/login 의 축약형 그림(2026-11-19 받음), 가이드 https://developers.kakao.com/docs/latest/ko/kakaologin/design-guide
 * 모서리 값(`shape`)은 호버 그림자·초점 윤곽선이 그림 모양을 따라가게 하는 값이다.
 */
const SOCIAL_FACES: Readonly<Record<SocialProvider, { src: string; width: number; height: number; shape: string }>> = {
  google: { src: "/social/google-signin-icon.svg", width: 46, height: 46, shape: "rounded-full" },
  kakao: { src: "/social/kakao-login-simple-ko.svg", width: 112, height: 46, shape: "rounded-lg" },
};

/**
 * 로그인(S10 1단계). 넓으면 2열(왼쪽 소개, 오른쪽 로그인 방법), 모달 폭이 좁으면 1열로 쌓인다(PRD-13 §4.3, 가로 스크롤 없음).
 * S1 로그인은 소셜(Google·Kakao)만이다(PRD-01-10 A). Naver는 S2에서 다시 넣고 Apple은 없다(사용자 결정 2026-11-18).
 * Google·Kakao를 누르면 공급자 동의 화면으로 페이지가 옮겨 가고 `/auth/callback`을 거쳐 첫 화면으로 돌아온다(목 모드는 옮기지 않고 목 세션만 만든다).
 * 콜백이 실패해 돌아오면(이메일 없는 카카오계정 등) 이 화면이 열리고 실패 안내가 보인다.
 * 마스코트는 왼쪽 소개에만 있고 로그인 방법 영역에는 쓰지 않는다.
 */
export function LoginStep({ mode: requested }: { mode: "login" | "signup" }) {
  const { store, hideMascot } = useAccountModal();
  const pending = useAccountStore((state) => state.pending, store);
  const failure = useAccountStore((state) => state.failure, store);
  const id = useId();
  // 이메일을 숨긴 동안에는 `signup` 단계로 들어와도 로그인 화면을 그린다
  const mode = EMAIL_AUTH_ENABLED ? requested : "login";

  const continueAsGuest = () => {
    store.getState().startGuest();
    store.getState().close();
  };

  return (
    <div className="flex min-h-full flex-col @min-[640px]:flex-row">
      {/* 왼쪽(1열에서는 위): 소개. 바탕이 모달 맨 위 모서리까지 이어진다 */}
      <div className="flex flex-col items-center gap-2 bg-bg-soft px-5 pt-14 pb-5 text-center @min-[640px]:w-[44%] @min-[640px]:flex-none @min-[640px]:justify-center @min-[640px]:pb-8">
        {!hideMascot && <Mascot variant="question" size={96} eager />}
        <b className="text-lg">
          <BrandLogo size={24} />
        </b>
        <StepTitle>{mode === "login" ? LOGIN_TITLE : SIGNUP_TITLE}</StepTitle>
        <p className="m-0 text-sm leading-5 text-ink-2 [word-break:keep-all]">{LOGIN_DESCRIPTION}</p>
        <EmergencyEntrySlot className="justify-center" />
      </div>
      {/* 오른쪽(1열에서는 아래): 로그인 방법 */}
      <div className="flex min-w-0 flex-1 flex-col justify-center gap-3 px-5 pt-5 pb-5 @min-[640px]:pt-14">
        {EMAIL_AUTH_ENABLED && <EmailForm mode={mode} />}
        {mode === "login" && (
          <>
            {EMAIL_AUTH_ENABLED && (
              <button type="button" disabled={pending} onClick={() => store.getState().go("signup")} className={SECONDARY_BUTTON}>
                {SIGNUP_ENTRY_LABEL}
              </button>
            )}
            <div role="group" aria-labelledby={`${id}-social`} data-testid="social-login" className="flex flex-col items-center gap-3">
              <h3 id={`${id}-social`} className="m-0 text-base font-bold">
                {SOCIAL_HEADING}
              </h3>
              <div className="flex flex-wrap items-center justify-center gap-4">
                {SOCIAL_PROVIDERS.map((provider) => {
                  const face = SOCIAL_FACES[provider];
                  return (
                    <button
                      key={provider}
                      type="button"
                      data-testid={`social-${provider}`}
                      aria-label={SOCIAL_LABELS[provider]}
                      disabled={pending}
                      onClick={() => void store.getState().loginSocial(provider)}
                      className={cn(SOCIAL_BUTTON, face.shape)}
                    >
                      {/* 이름은 버튼의 aria-label이 읽는다. 그림은 장식이라 두 번 읽히지 않게 비운다 */}
                      <Image src={face.src} alt="" width={face.width} height={face.height} unoptimized className={face.shape} />
                    </button>
                  );
                })}
              </div>
            </div>
          </>
        )}
        {!EMAIL_AUTH_ENABLED && <FailureLine failure={failure} />}
        <button type="button" onClick={continueAsGuest} className={TEXT_BUTTON}>
          {CONTINUE_AS_GUEST_LABEL}
        </button>
        {isApiMockingEnabled() && <p className="m-0 text-center text-xs text-mute">{MOCK_NOTE}</p>}
      </div>
    </div>
  );
}

/**
 * 이메일 로그인·가입 폼. PRD-01-10 A로 지금은 그리지 않는다(`EMAIL_AUTH_ENABLED`): 메일 인증을 갖춘 뒤 재검토.
 * 적은 이메일·비밀번호는 이 부품의 메모리에만 있고 어디에도 저장하지 않는다.
 */
function EmailForm({ mode }: { mode: "login" | "signup" }) {
  const { store } = useAccountModal();
  const pending = useAccountStore((state) => state.pending, store);
  const failure = useAccountStore((state) => state.failure, store);
  const notice = useAccountStore((state) => state.notice, store);
  const id = useId();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [invalid, setInvalid] = useState<"email" | "password" | null>(null);

  const submit = () => {
    const address = email.trim();
    if (!EMAIL_SHAPE.test(address)) return setInvalid("email");
    if (password.length === 0) return setInvalid("password");
    setInvalid(null);
    const { loginEmail, signupEmail } = store.getState();
    void (mode === "login" ? loginEmail(address, password) : signupEmail(address, password));
  };

  return (
    <form
      noValidate
      data-testid={mode === "login" ? "login-form" : "signup-form"}
      className="flex flex-col gap-2.5"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      {mode === "login" && <h3 className="m-0 text-base font-bold">{EMAIL_LOGIN_HEADING}</h3>}
      <label htmlFor={`${id}-email`} className="text-xs font-bold text-ink-2">
        {EMAIL_LABEL}
      </label>
      <input
        id={`${id}-email`}
        type="email"
        inputMode="email"
        autoComplete="email"
        value={email}
        aria-invalid={invalid === "email"}
        aria-describedby={invalid === "email" ? `${id}-invalid` : undefined}
        onChange={(event) => setEmail(event.target.value)}
        className={FIELD_CLASS}
      />
      <label htmlFor={`${id}-password`} className="text-xs font-bold text-ink-2">
        {PASSWORD_LABEL}
      </label>
      <input
        id={`${id}-password`}
        type="password"
        autoComplete={mode === "login" ? "current-password" : "new-password"}
        value={password}
        aria-invalid={invalid === "password"}
        aria-describedby={invalid === "password" ? `${id}-invalid` : undefined}
        onChange={(event) => setPassword(event.target.value)}
        className={FIELD_CLASS}
      />
      {invalid && (
        <p id={`${id}-invalid`} role="alert" className="m-0 text-sm leading-5 font-semibold text-red-ink">
          {invalid === "email" ? ERROR_EMAIL_FORMAT : ERROR_PASSWORD_EMPTY}
        </p>
      )}
      <FailureLine failure={failure} />
      {notice === "signup-confirm" && (
        <p role="status" data-testid="signup-confirm-notice" className="m-0 rounded-xl bg-bg-softer px-3 py-2 text-sm leading-5 text-ink-2 [word-break:keep-all]">
          {SIGNUP_CONFIRM_NOTICE}
        </p>
      )}
      <button type="submit" disabled={pending} className={PRIMARY_BUTTON}>
        {mode === "login" ? LOGIN_SUBMIT_LABEL : SIGNUP_SUBMIT_LABEL}
      </button>
    </form>
  );
}
