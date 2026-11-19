"use client";

import { useId, useState } from "react";
import { BrandLogo } from "@/components/BrandLogo";
import { Mascot } from "@/components/Mascot";
import { SOCIAL_PROVIDERS } from "@/lib/api/account";
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
  NAVER_LABEL,
  NAVER_PENDING,
  PASSWORD_LABEL,
  SIGNUP_CONFIRM_NOTICE,
  SIGNUP_ENTRY_LABEL,
  SIGNUP_SUBMIT_LABEL,
  SIGNUP_TITLE,
  SOCIAL_HEADING,
  SOCIAL_LABELS,
} from "./copy";
import { EmergencyEntrySlot, FIELD_CLASS, FailureLine, PRIMARY_BUTTON, SECONDARY_BUTTON, StepTitle, TEXT_BUTTON, useAccountModal } from "./parts";

const EMAIL_SHAPE = /^[^\s@]+@[^\s@]+$/;

/**
 * 로그인·이메일 가입(S10 1단계). 넓으면 2열(왼쪽 소개, 오른쪽 폼), 모달 폭이 좁으면 1열로 쌓인다(PRD-13 §4.3, 가로 스크롤 없음).
 * 적은 이메일·비밀번호는 이 부품의 메모리에만 있고 어디에도 저장하지 않는다.
 * 소셜 로그인은 Google·Kakao이고 Naver는 버튼만 두고 비활성("준비 중")이다. Apple은 없다(사용자 결정 2026-11-18).
 * Google·Kakao를 누르면 공급자 동의 화면으로 페이지가 옮겨 가고 `/auth/callback`을 거쳐 첫 화면으로 돌아온다(목 모드는 옮기지 않고 목 세션만 만든다).
 * 콜백이 실패해 돌아오면(이메일 없는 카카오계정 등) 이 화면이 열리고 실패 안내가 보인다.
 */
export function LoginStep({ mode }: { mode: "login" | "signup" }) {
  const { store, hideMascot } = useAccountModal();
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
      {/* 오른쪽(1열에서는 아래): 폼 */}
      <div className="flex min-w-0 flex-1 flex-col gap-3 px-5 pt-5 pb-5 @min-[640px]:pt-14">
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
        {mode === "login" && (
          <>
            <button type="button" disabled={pending} onClick={() => store.getState().go("signup")} className={SECONDARY_BUTTON}>
              {SIGNUP_ENTRY_LABEL}
            </button>
            <div role="group" aria-labelledby={`${id}-social`} className="flex flex-col gap-2">
              <h3 id={`${id}-social`} className="m-0 mt-1 text-xs font-bold text-ink-2">
                {SOCIAL_HEADING}
              </h3>
              {SOCIAL_PROVIDERS.map((provider) => (
                <button
                  key={provider}
                  type="button"
                  data-testid={`social-${provider}`}
                  disabled={pending}
                  onClick={() => void store.getState().loginSocial(provider)}
                  className={SECONDARY_BUTTON}
                >
                  {SOCIAL_LABELS[provider]}
                </button>
              ))}
              {/* Naver는 연동 방식 확인 중(S2): 버튼만 두고 누를 수 없다. 이유는 글자만 보인다 */}
              <button type="button" data-testid="social-naver" disabled className={SECONDARY_BUTTON}>
                {NAVER_LABEL} · {NAVER_PENDING}
              </button>
            </div>
          </>
        )}
        <button type="button" onClick={continueAsGuest} className={TEXT_BUTTON}>
          {CONTINUE_AS_GUEST_LABEL}
        </button>
        {isApiMockingEnabled() && <p className="m-0 text-center text-xs text-mute">{MOCK_NOTE}</p>}
      </div>
    </div>
  );
}
