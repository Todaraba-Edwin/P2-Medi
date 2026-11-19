"use client";

import { useEffect, useId, useState } from "react";
import type { LegalDocType } from "@/lib/api/account";
import { requiredAgreed, useAccountStore } from "@/stores/account";
import {
  CONSENT_DESCRIPTION,
  CONSENT_REQUIRED_HINT,
  CONSENT_SUBMIT_LABEL,
  CONSENT_TITLE,
  LEGAL_LOADING,
  LEGAL_LOAD_FAILED,
  OPTIONAL_TAG,
  REQUIRED_TAG,
  RETRY_LOAD_LABEL,
  agreeLabel,
  docVersionLine,
} from "./copy";
import { Markdown } from "./Markdown";
import { EmergencyEntrySlot, FailureLine, PRIMARY_BUTTON, SECONDARY_BUTTON, StepBody, StepTitle, useAccountModal } from "./parts";

type Agreed = Partial<Record<LegalDocType, boolean>>;

/**
 * 약관 동의(S10 2단계). 문서의 제목·본문·버전·필수 여부는 `GET /api/legal/*` 값을 그대로 그린다(프런트에 문구를 두지 않는다).
 * 필수 문서에 모두 동의해야 다음으로 갈 수 있다. 선택 문서(건강 정보 등)는 동의하지 않아도 된다.
 */
export function ConsentStep() {
  const { store } = useAccountModal();
  const docs = useAccountStore((state) => state.legalDocs, store);
  const status = useAccountStore((state) => state.legalDocsStatus, store);
  const me = useAccountStore((state) => state.me, store);
  const pending = useAccountStore((state) => state.pending, store);
  const failure = useAccountStore((state) => state.failure, store);
  const id = useId();
  /** 사용자가 이 화면에서 바꾼 값. 건드리지 않은 문서는 이미 동의한 기록(같은 버전)을 따른다 */
  const [touched, setTouched] = useState<Agreed>({});

  useEffect(() => {
    void store.getState().loadLegalDocs();
  }, [store]);

  const agreed: Agreed = {};
  for (const doc of docs) {
    agreed[doc.doc_type] = touched[doc.doc_type] ?? (me?.consents.some((consent) => consent.doc_type === doc.doc_type && consent.version === doc.version) === true);
  }
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
          {docs.map((doc) => (
            <li key={doc.doc_type} data-testid="legal-doc" data-doc-type={doc.doc_type} data-required={doc.required} className="flex flex-col gap-1.5 rounded-2xl border border-line p-3">
              <h3 className="m-0 text-sm leading-5 font-bold [word-break:keep-all]">
                <span className={doc.required ? "text-red-ink" : "text-mute"}>[{doc.required ? REQUIRED_TAG : OPTIONAL_TAG}]</span> {doc.title}
              </h3>
              <p className="m-0 text-xs text-mute">{docVersionLine(doc.version, doc.effective_at)}</p>
              {/* 본문은 상자 안에서 스크롤한다. 키보드로도 내려 읽을 수 있게 초점을 받는다 */}
              {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex */}
              <div tabIndex={0} role="group" aria-label={doc.title} className="max-h-36 overflow-y-auto rounded-xl bg-bg-softer p-2.5">
                <Markdown source={doc.body_md} />
              </div>
              <label htmlFor={`${id}-${doc.doc_type}`} className="flex min-h-11 cursor-pointer items-center gap-2.5 text-sm font-semibold">
                <input
                  id={`${id}-${doc.doc_type}`}
                  type="checkbox"
                  checked={agreed[doc.doc_type] === true}
                  onChange={(event) => setTouched((prev) => ({ ...prev, [doc.doc_type]: event.target.checked }))}
                  className="size-5 flex-none accent-ink"
                />
                <span className="min-w-0 [word-break:keep-all]">{agreeLabel(doc.title)}</span>
              </label>
            </li>
          ))}
        </ul>
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
        onClick={() => void store.getState().submitConsents(agreed)}
        className={PRIMARY_BUTTON}
      >
        {CONSENT_SUBMIT_LABEL}
      </button>
      <EmergencyEntrySlot />
    </StepBody>
  );
}
