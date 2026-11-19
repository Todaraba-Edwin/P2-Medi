"use client";

import { useEffect, useRef } from "react";
import type { Candidate } from "@/lib/api";
import { PRIMARY_BUTTON } from "@/components/button";
import { NoMascotZone } from "@/components/NoMascotZone";
import { ErrorState, MessageBubble, ProgressSteps } from "@/features/chat";
import { FixedNoticeBox } from "@/features/emergency";
import { EvidenceEntryButton } from "@/features/evidence";
import type { EvidenceMode } from "@/features/evidence";
import { ResultView } from "@/features/result";
import type { ChatTurn } from "@/stores/chat";
import { RESEND_WITH_PICK_LABEL } from "./copy";

export interface ConversationProps {
  turns: ChatTurn[];
  /** 대화에 119 안내가 떠 있는지(진행 표시·오류의 마스코트를 숨긴다) */
  hasEmergency: boolean;
  /** 이 차례의 고정 안내는 아래 고정 영역이 보이고 있다(대화 안에 한 번 더 그리지 않는다) */
  dockTurnId: string | null;
  /** 근거 상세가 열려 있는 차례 */
  evidenceTurnId: string | null;
  /** 진입 버튼 글자 종류(폭으로 정한다) */
  entryLabelMode: EvidenceMode;
  /** 되묻기에서 고른 후보(차례별). 고르기만 하고 보내지 않는다 */
  picked: Readonly<Record<string, Candidate>>;
  onOpenEvidence: (turnId: string) => void;
  onRetry: (turnId: string) => void;
  onPick: (turnId: string, candidate: Candidate) => void;
  /** "목록에 없어요 · 직접 입력", "이름 다시 입력": 입력창으로 간다 */
  onOther: () => void;
  /** 고른 후보를 붙여 같은 질문을 다시 보낸다 */
  onResend: (turnId: string) => void;
}

interface TurnProps extends Omit<ConversationProps, "turns"> {
  turn: ChatTurn;
  isLast: boolean;
}

function TurnAnswer({ turn, isLast, hasEmergency, dockTurnId, evidenceTurnId, entryLabelMode, picked, onOpenEvidence, onRetry, onPick, onOther, onResend }: TurnProps) {
  const { stream } = turn;
  // 검증을 통과한 응답이 있으면 어떤 상태로 끝났든 그 결과를 보인다(done 없이 끊겨도 유지)
  if (stream.response) {
    const response = stream.response;
    const pick = isLast ? picked[turn.id] : undefined;
    return (
      <div data-testid="turn-answer" className="flex flex-col gap-2.5">
        <ResultView
          response={response}
          footer={
            // 판정 줄이 있는 결과만 근거 상세로 들어간다(카드가 없으면 버튼 자리도 없다)
            response.findings.length > 0 ? (
              <EvidenceEntryButton
                mode={entryLabelMode}
                expanded={evidenceTurnId === turn.id}
                onClick={() => onOpenEvidence(turn.id)}
                // 약을 찾지 못한 줄(서버가 입력한 이름을 실어 보낸 줄)이 있으면 `· 찾아본 곳`
                lookup={response.findings.some((finding) => finding.input_name !== null)}
              />
            ) : undefined
          }
          // 후보는 마지막 차례에서만 고를 수 있다(지난 되묻기로는 다시 보내지 않는다)
          onPickCandidate={isLast ? (candidate) => onPick(turn.id, candidate) : undefined}
          onOtherCandidate={isLast ? onOther : undefined}
          selectedCandidate={isLast ? (pick ?? null) : undefined}
          // `이름 다시 입력`도 마지막 차례에서만 둔다(입력창으로 간다)
          onRetryName={isLast ? onOther : undefined}
        />
        {pick && (
          <NoMascotZone>
            <div data-testid="resend-pick" className="flex flex-wrap items-center gap-2 rounded-2xl border border-line bg-bg-softer px-3.5 py-2">
              {/* 고른 후보의 이름은 응답 값 그대로다 */}
              <b data-testid="picked-name" className="min-w-0 flex-1 basis-40 text-sm font-semibold [overflow-wrap:break-word] [word-break:keep-all]">
                {pick.name}
              </b>
              <button type="button" onClick={() => onResend(turn.id)} className={`${PRIMARY_BUTTON} flex-none`}>
                {RESEND_WITH_PICK_LABEL}
              </button>
            </div>
          </NoMascotZone>
        )}
        {/* 지난 답의 고정 안내는 그 답 아래에 접히지 않게 남긴다(가장 최근 답의 것은 아래 고정 영역에 있다) */}
        {dockTurnId !== turn.id && <FixedNoticeBox lines={response.fixed_notice} />}
      </div>
    );
  }
  if (stream.status === "streaming") return <ProgressSteps stage={stream.stage} label={stream.label} hideMascot={hasEmergency} />;
  if (stream.status === "error" || stream.status === "interrupted") {
    return <ErrorState stream={stream} onRetry={() => onRetry(turn.id)} allowRetry={isLast} hideMascot={hasEmergency} />;
  }
  return null; // idle, 사용자가 끊은 차례(aborted)는 질문만 남긴다
}

/** 대화 스레드: 질문과 그 답(진행 표시 → 결과 또는 오류)을 받은 순서대로 그린다 */
export function Conversation({ turns, ...rest }: ConversationProps) {
  const end = useRef<HTMLDivElement>(null);
  const last = turns[turns.length - 1];
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [turns.length, last?.stream.status, last?.stream.stage, last?.stream.response]);

  return (
    <div data-testid="chat-thread" className="flex min-h-0 flex-1 flex-col gap-3.5 overflow-y-auto px-0.5 pt-2 pb-3">
      {turns.map((turn) => (
        <div key={turn.id} data-turn={turn.id} data-status={turn.stream.status} className="flex flex-col gap-2.5">
          <MessageBubble side="me">{turn.question}</MessageBubble>
          <TurnAnswer turn={turn} isLast={turn === last} {...rest} />
        </div>
      ))}
      <div ref={end} />
    </div>
  );
}
