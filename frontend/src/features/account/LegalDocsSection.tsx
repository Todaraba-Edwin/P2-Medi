"use client";

import { useEffect, useId, useState } from "react";
import { ChevronDownIcon } from "lucide-react";
import { HOVER_ROW, SECONDARY_BUTTON } from "@/components/button";
import type { LegalMenuDoc } from "@/lib/api/account";
import { cn } from "@/lib/utils";
import { LEGAL_LOADING, LEGAL_LOAD_FAILED, LEGAL_MENU_LABEL, LEGAL_NOT_REVIEWED_TAG, RETRY_LOAD_LABEL, docVersionLine } from "./copy";
import { fetchLegalMenu } from "./legal-menu";
import { Markdown } from "./Markdown";

type Status = "loading" | "ready" | "failed";

/** 받은 결과. `key`가 지금 요청 열쇠(상태·재시도 횟수)와 같을 때만 유효하다(효과 안에서 상태를 "loading"으로 되돌리지 않는다) */
interface Loaded {
  key: string;
  docs: LegalMenuDoc[];
  failed: boolean;
}

export interface LegalDocsSectionProps {
  /** 로그인했는가. 게스트/회원 목록이 다르다(`legal-menu.ts`) */
  member: boolean;
  /** 묶음 제목 요소의 id(설정 화면이 이 묶음으로 바로 초점을 옮길 때 쓴다) */
  headingId?: string;
  /** 시험용 주입. 기본은 `fetchLegalMenu` */
  load?: (member: boolean) => Promise<LegalMenuDoc[]>;
}

/**
 * 약관·정책 열람 묶음(설정 화면 안, 2026-11-23). **읽기 전용**이다: 동의 체크·제출이 없고 동의 기록을 만들지 않는다(철회는 기존 규칙대로 탈퇴로만).
 * - 항목 이름·본문·버전은 서버 문서 값 그대로(화면 상수는 묶음 제목 `LEGAL_MENU_LABEL`뿐)
 * - 게스트/회원 목록은 `legal-menu.ts`의 매핑 한 곳. 서버에 없는 종류(404·422)는 목록에서 빠진다(안내 글자 없음)
 * - 항목을 누르면 그 자리에서 펼쳐진다(`aria-expanded`·`aria-controls`). 본문은 상자 안에서 스크롤하고 키보드로도 내려 읽게 초점을 받는다(동의 화면과 같은 규칙)
 * - 목록은 묶음이 그려질 때(설정 화면이 열릴 때) 받는다. 실패하면 한 줄 + 다시 불러오기
 */
export function LegalDocsSection({ member, headingId, load = fetchLegalMenu }: LegalDocsSectionProps) {
  const id = useId();
  const [openDocType, setOpenDocType] = useState<string | null>(null);
  /** 다시 불러오기 횟수(효과를 다시 돌리는 열쇠) */
  const [attempt, setAttempt] = useState(0);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const key = `${member}|${attempt}`;
  const current = loaded?.key === key ? loaded : null;
  const status: Status = current === null ? "loading" : current.failed ? "failed" : "ready";
  const docs = current?.docs ?? [];

  useEffect(() => {
    let cancelled = false;
    load(member).then(
      (result) => {
        if (!cancelled) setLoaded({ key, docs: result, failed: false });
      },
      () => {
        if (!cancelled) setLoaded({ key, docs: [], failed: true });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [load, member, key]);

  // 목록에 문서가 하나도 없으면(서버가 모두 없다고 함) 묶음 자체를 그리지 않는다: "준비 중" 같은 빈 안내를 두지 않는다
  if (status === "ready" && docs.length === 0) return null;

  const heading = headingId ?? `${id}-heading`;
  return (
    <section aria-labelledby={heading} data-testid="legal-menu" data-audience={member ? "member" : "guest"} className="flex flex-col gap-2.5">
      <h3 id={heading} tabIndex={-1} className="m-0 text-xs font-bold text-mute outline-none">
        {LEGAL_MENU_LABEL}
      </h3>
      {status === "loading" ? (
        <p role="status" className="m-0 text-sm text-mute">
          {LEGAL_LOADING}
        </p>
      ) : status === "failed" ? (
        <div className="flex flex-col items-start gap-2">
          <p role="alert" className="m-0 text-sm font-semibold text-red-ink">
            {LEGAL_LOAD_FAILED}
          </p>
          <button type="button" onClick={() => setAttempt((n) => n + 1)} className={SECONDARY_BUTTON}>
            {RETRY_LOAD_LABEL}
          </button>
        </div>
      ) : (
        <ul className="m-0 flex list-none flex-col p-0">
          {docs.map((doc) => {
            const open = openDocType === doc.doc_type;
            const panelId = `${id}-${doc.doc_type}`;
            return (
              <li key={doc.doc_type} data-testid="legal-menu-item" data-doc-type={doc.doc_type} className="flex flex-col border-b border-line last:border-b-0">
                <button
                  type="button"
                  aria-expanded={open}
                  aria-controls={panelId}
                  onClick={() => setOpenDocType(open ? null : doc.doc_type)}
                  className={cn("flex min-h-11 w-full items-center gap-2 rounded-[10px] px-2 py-2 text-left", HOVER_ROW)}
                >
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="text-sm leading-5 font-semibold text-ink [word-break:keep-all]">{doc.title}</span>
                    <span className="text-xs text-mute">
                      {docVersionLine(doc.version, doc.effective_at)}
                      {doc.legal_review === "not_reviewed" && (
                        <>
                          {" · "}
                          <span data-testid="legal-not-reviewed" className="font-semibold text-ink-2">
                            {LEGAL_NOT_REVIEWED_TAG}
                          </span>
                        </>
                      )}
                    </span>
                  </span>
                  <ChevronDownIcon aria-hidden="true" className={cn("size-4 flex-none text-mute transition-transform", open && "rotate-180")} />
                </button>
                {/* 펼친 본문: 상자 안에서 스크롤한다. 키보드로도 내려 읽을 수 있게 초점을 받는다 */}
                {open && (
                  // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
                  <div id={panelId} tabIndex={0} role="group" aria-label={doc.title} data-testid="legal-menu-body" className="mb-2 max-h-72 overflow-y-auto rounded-xl bg-bg-softer p-2.5">
                    <Markdown source={doc.body_md} />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
