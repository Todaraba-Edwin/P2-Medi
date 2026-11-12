"use client";

import { useState } from "react";
import { ChatScreen, Splash } from "@/features/chat";
import { MockProvider } from "@/mocks/MockProvider";
import { SCENARIO_KEYWORDS } from "@/mocks/handlers";
import { isApiMockingEnabled } from "@/mocks";
import { chatStore } from "@/stores/chat";

/** 개발 전용: MSW 합성 fixture 시나리오를 골라 보낸다. 표시 글자는 mock 핸들러의 선택 규칙이다. */
export function ChatPreview() {
  const [splash, setSplash] = useState(false);
  const { send, reset } = chatStore.getState();
  return (
    <MockProvider>
      {splash && <Splash onDone={() => setSplash(false)} />}
      <div className="flex h-dvh flex-col">
      <details className="mx-auto w-full max-w-[430px] flex-none px-3 text-xs text-mute">
        <summary className="min-h-11 cursor-pointer py-3">
          미리보기 도구 · mock {isApiMockingEnabled() ? "켜짐" : "꺼짐(NEXT_PUBLIC_API_MOCKING)"}
        </summary>
        <div className="flex flex-wrap gap-1.5 pb-2">
          <button type="button" className="min-h-11 rounded-lg border border-line px-2" onClick={() => void send("mock 기본 질문")}>
            기본(금기 발견)
          </button>
          {SCENARIO_KEYWORDS.map(([keyword]) => (
            <button key={keyword} type="button" className="min-h-11 rounded-lg border border-line px-2" onClick={() => void send(`${keyword} 질문`)}>
              {keyword}
            </button>
          ))}
          <button type="button" className="min-h-11 rounded-lg border border-line-2 px-2 font-bold" onClick={() => reset()}>
            새 대화
          </button>
          <button type="button" className="min-h-11 rounded-lg border border-line-2 px-2 font-bold" onClick={() => setSplash(true)}>
            여는 화면
          </button>
        </div>
      </details>
      <ChatScreen className="min-h-0 flex-1" />
      </div>
    </MockProvider>
  );
}
