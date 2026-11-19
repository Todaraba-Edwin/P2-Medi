"use client";

import { useEffect, useId, useState } from "react";
import { HEALTH_CONSENT_DOC, isConsentDocType } from "@/lib/api/account";
import { consentActive, requiredAgreed, useAccountStore } from "@/stores/account";
import type { ConsentChoices } from "@/stores/account";
import {
  CONSENT_DESCRIPTION,
  CONSENT_REQUIRED_HINT,
  CONSENT_SUBMIT_LABEL,
  CONSENT_TITLE,
  HEALTH_WITHDRAW_CONFIRM_BODY,
  HEALTH_WITHDRAW_CONFIRM_LABEL,
  HEALTH_WITHDRAW_CONFIRM_TITLE,
  HEALTH_WITHDRAW_WARNING,
  LEGAL_LOADING,
  LEGAL_LOAD_FAILED,
  LEGAL_NOT_REVIEWED_TAG,
  NOTICE_TAG,
  OPTIONAL_TAG,
  REQUIRED_TAG,
  RETRY_LOAD_LABEL,
  agreeLabel,
  docVersionLine,
} from "./copy";
import { Markdown } from "./Markdown";
import { ConfirmDialog, EmergencyEntrySlot, FailureLine, PRIMARY_BUTTON, SECONDARY_BUTTON, StepBody, StepTitle, useAccountModal } from "./parts";

type Agreed = ConsentChoices;

/**
 * 약관 동의(S10 2단계). 문서의 제목·본문·버전·필수 여부는 `GET /api/legal/*` 값을 그대로 그린다(프런트에 문구를 두지 않는다).
 * 필수 문서(이용약관·개인정보 수집·이용)에 모두 동의해야 다음으로 갈 수 있다. 선택 문서(건강 정보)는 동의하지 않아도 된다.
 * 고지 문서(`privacy_policy` 처리방침: 외부 AI 전송 안내가 여기 있다)는 **체크 없는 고지**로만 보이고 동의 항목에 들어가지 않는다(FE-04-03 A).
 * 법률 검토 전 문서(`legal_review: "not_reviewed"`)에는 "초안·법률 검토 전" 표지를 붙인다.
 * 동의해 둔 건강 정보 동의를 끄고 보내려 하면 확인 모달을 먼저 띄운다(FE-04-06 A): 철회하면 서버가 건강 정보를 즉시 지우고 되돌릴 수 없다.
 */
export function ConsentStep() {
  const { store } = useAccountModal();
  const docs = useAccountStore((state) => state.legalDocs, store);
  const status = useAccountStore((state) => state.legalDocsStatus, store);
  const me = useAccountStore((state) => state.me, store);
  const pending = useAccountStore((state) => state.pending, store);
  const failure = useAccountStore((state) => state.failure, store);
  const id = useId();
  /** 사용자가 이 화면에서 바꾼 값. 건드리지 않은 문서는 지금 유효한 동의 상태(`GET /me`의 `consents[]`)를 따른다 */
  const [touched, setTouched] = useState<Agreed>({});
  /** 건강 정보 동의 철회 확인 모달이 열려 있는가 */
  const [confirmingWithdraw, setConfirmingWithdraw] = useState(false);

  useEffect(() => {
    void store.getState().loadLegalDocs();
  }, [store]);

  const agreed: Agreed = {};
  for (const doc of docs) {
    if (isConsentDocType(doc.doc_type)) agreed[doc.doc_type] = touched[doc.doc_type] ?? consentActive(me, doc.doc_type);
  }
  /** 동의해 둔 건강 정보 동의를 끄려는 중이다(보내면 철회되고 서버가 건강 정보를 즉시 지운다) */
  const withdrawingHealth = consentActive(me, HEALTH_CONSENT_DOC) && agreed[HEALTH_CONSENT_DOC] === false;
  const ready = status === "ready";
  const canSubmit = ready && requiredAgreed(docs, agreed) && !pending;

  return (
    <StepBody data-testid="consent-step">
      <StepTitle>{CONSENT_TITLE}</StepTitle>
      <p className="m-0 text-sm leading-5 text-ink-2">{CONSENT_DESCRIPTION}</p>
      {status === "loading" || status === "idle" ? (
        <p role="status" className="m-0 text-sm text-mute">
          {LEGAL_LOADING}
        </p>
      ) : status === "failed" ? (
        <div className="flex flex-col items-start gap-2">
          <p role="alert" className="m-0 text-sm font-semibold text-red-ink">
            {LEGAL_LOAD_FAILED}
          </p>
          <button type="button" onClick={() => void store.getState().loadLegalDocs()} className={SECONDARY_BUTTON}>
            {RETRY_LOAD_LABEL}
          </button>
        </div>
      ) : (
        <ul className="m-0 flex list-none flex-col gap-3 p-0">
          {docs.map((doc) => {
            const docType = doc.doc_type;
            const consentable = isConsentDocType(docType);
            return (
            <li key={docType} data-testid="legal-doc" data-doc-type={docType} data-required={doc.required} data-consent={consentable} className="flex flex-col gap-1.5 rounded-2xl border border-line p-3">
              <h3 className="m-0 text-sm leading-5 font-bold [word-break:keep-all]">
                <span className={consentable && doc.required ? "text-red-ink" : "text-mute"}>[{!consentable ? NOTICE_TAG : doc.required ? REQUIRED_TAG : OPTIONAL_TAG}]</span> {doc.title}
              </h3>
              <p className="m-0 text-xs text-mute">
                {docVersionLine(doc.version, doc.effective_at)}
                {doc.legal_review === "not_reviewed" && (
                  <>
                    {" · "}
                    <span data-testid="legal-not-reviewed" className="font-semibold text-ink-2">
                      {LEGAL_NOT_REVIEWED_TAG}
                    </span>
                  </>
                )}
              </p>
              {/* 본문은 상자 안에서 스크롤한다. 키보드로도 내려 읽을 수 있게 초점을 받는다 */}
              {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
              <div tabIndex={0} role="group" aria-label={doc.title} className="max-h-36 overflow-y-auto rounded-xl bg-bg-softer p-2.5">
                <Markdown source={doc.body_md} />
              </div>
              {/* 고지 문서에는 체크가 없다: 읽는 문서이지 동의 관문이 아니다 */}
              {consentable && (
                <label htmlFor={`${id}-${docType}`} className="flex min-h-11 cursor-pointer items-center gap-2.5 text-sm font-semibold">
                  <input
                    id={`${id}-${docType}`}
                    type="checkbox"
                    checked={agreed[docType] === true}
                    onChange={(event) => setTouched((prev) => ({ ...prev, [docType]: event.target.checked }))}
                    className="size-5 flex-none accent-ink"
                  />
                  <span className="min-w-0 [word-break:keep-all]">{agreeLabel(doc.title)}</span>
                </label>
              )}
            </li>
            );
          })}
        </ul>
      )}
      {ready && withdrawingHealth && (
        <p role="status" data-testid="health-withdraw-warning" className="m-0 rounded-xl bg-bg-softer px-3 py-2 text-xs leading-[17px] font-semibold text-red-ink">
          {HEALTH_WITHDRAW_WARNING}
        </p>
      )}
      <FailureLine failure={failure} />
      {ready && !requiredAgreed(docs, agreed) && (
        <p id={`${id}-hint`} data-testid="consent-hint" className="m-0 text-xs leading-[17px] text-mute">
          {CONSENT_REQUIRED_HINT}
        </p>
      )}
      <button
        type="button"
        data-testid="consent-submit"
        disabled={!canSubmit}
        aria-describedby={ready && !requiredAgreed(docs, agreed) ? `${id}-hint` : undefined}
        // 건강 정보 동의 철회가 섞여 있으면 바로 보내지 않고 확인을 받는다
        onClick={() => (withdrawingHealth ? setConfirmingWithdraw(true) : void store.getState().submitConsents(agreed))}
        className={PRIMARY_BUTTON}
      >
        {CONSENT_SUBMIT_LABEL}
      </button>
      <EmergencyEntrySlot />
      <ConfirmDialog
        open={confirmingWithdraw}
        onOpenChange={setConfirmingWithdraw}
        title={HEALTH_WITHDRAW_CONFIRM_TITLE}
        body={HEALTH_WITHDRAW_CONFIRM_BODY}
        confirmLabel={HEALTH_WITHDRAW_CONFIRM_LABEL}
        pending={pending}
        onConfirm={() => {
          // 확인 모달은 닫고 보낸다: 성공하면 프로필로 넘어가고, 실패하면 동의 화면에 오류 한 줄이 보인다
          setConfirmingWithdraw(false);
          void store.getState().submitConsents(agreed);
        }}
      />
    </StepBody>
  );
}
