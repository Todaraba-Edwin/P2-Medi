"use client";

import { useEffect } from "react";
import { chatStore, useChatStore } from "@/stores/chat";
import type { ChatStore } from "@/stores/chat";
import { cn } from "@/lib/utils";
import { ChatInput } from "./ChatInput";
import { ChatThread } from "./ChatThread";
import { EmergencySlot } from "./EmergencySlot";
import { ExampleChips } from "./ExampleChips";
import { HomeHero } from "./HomeHero";

/**
 * 채팅 부품 묶음: 119 자리(맨 위) → 시작 화면 또는 대화 → 입력창(아래 고정).
 * 미리보기와 시험이 쓰는 묶음이며, 실제 화면 조립(셸·결과 카드·근거 상세)은 FE-IMPL-06이 한다.
 */
export interface ChatScreenProps {
  store?: ChatStore;
  /** 높이를 정하는 class. 기본은 화면 높이 전체다. 셸 안에 넣을 때는 부모가 준 높이를 채우게 바꾼다 */
  className?: string;
}

export function ChatScreen({ store = chatStore, className = "h-dvh" }: ChatScreenProps) {
  const turns = useChatStore((state) => state.turns, store);
  const emergency = useChatStore((state) => state.emergency, store);
  const send = useChatStore((state) => state.send, store);
  const retry = useChatStore((state) => state.retry, store);

  // 화면을 떠나면 진행 중인 요청을 끊는다
  useEffect(() => () => store.getState().abort(), [store]);

  return (
    <div data-testid="chat-screen" className={cn("mx-auto flex w-full max-w-[430px] flex-col gap-2 px-3 pt-2", className)}>
      {/* 119 안내는 항상 첫 요소다. 한 번 뜨면 내리지 않는다 */}
      {emergency && <EmergencySlot emergency={emergency} />}
      {turns.length === 0 ? (
        <div className="flex min-h-0 flex-1 flex-col justify-center gap-4 overflow-y-auto py-2">
          <HomeHero />
          <ExampleChips onPick={(question) => void send(question)} />
        </div>
      ) : (
        <ChatThread turns={turns} hasEmergency={emergency !== null} onRetry={(turnId) => void retry(turnId)} />
      )}
      <div className="flex-none pb-[max(14px,env(safe-area-inset-bottom,0px))]">
        <ChatInput onSend={(question) => void send(question)} />
      </div>
    </div>
  );
}
