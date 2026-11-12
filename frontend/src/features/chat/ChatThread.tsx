"use client";

import { useEffect, useRef } from "react";
import type { ChatTurn } from "@/stores/chat";
import { ErrorState } from "./ErrorState";
import { MessageBubble } from "./MessageBubble";
import { ProgressSteps } from "./ProgressSteps";
import { ResultSlot } from "./ResultSlot";

export interface ChatThreadProps {
  turns: ChatTurn[];
  /** 대화에 119 안내가 떠 있는지(진행 표시·오류의 마스코트를 숨긴다) */
  hasEmergency: boolean;
  onRetry: (turnId: string) => void;
}

function TurnAnswer({ turn, isLast, hasEmergency, onRetry }: { turn: ChatTurn; isLast: boolean; hasEmergency: boolean; onRetry: () => void }) {
  const { stream } = turn;
  // 검증을 통과한 응답이 있으면 어떤 상태로 끝났든 그 결과를 보인다(done 없이 끊겨도 유지)
  if (stream.response) return <ResultSlot response={stream.response} />;
  if (stream.status === "streaming") return <ProgressSteps stage={stream.stage} label={stream.label} hideMascot={hasEmergency} />;
  if (stream.status === "error" || stream.status === "interrupted") return <ErrorState stream={stream} onRetry={onRetry} allowRetry={isLast} hideMascot={hasEmergency} />;
  return null; // idle, 사용자가 끊은 차례(aborted)는 질문만 남긴다
}

/** 대화 스레드. 질문과 그 답 자리를 받은 순서대로 그린다. */
export function ChatThread({ turns, hasEmergency, onRetry }: ChatThreadProps) {
  const end = useRef<HTMLDivElement>(null);
  const last = turns[turns.length - 1];
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [turns.length, last?.stream.status, last?.stream.stage]);

  return (
    <div data-testid="chat-thread" className="flex min-h-0 flex-1 flex-col gap-3.5 overflow-y-auto px-0.5 pt-2 pb-3">
      {turns.map((turn) => (
        <div key={turn.id} data-turn={turn.id} data-status={turn.stream.status} className="flex flex-col gap-2.5">
          <MessageBubble side="me">{turn.question}</MessageBubble>
          <TurnAnswer turn={turn} isLast={turn === last} hasEmergency={hasEmergency} onRetry={() => onRetry(turn.id)} />
        </div>
      ))}
      <div ref={end} />
    </div>
  );
}
