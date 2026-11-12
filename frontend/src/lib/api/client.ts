// ky 클라이언트. 브라우저는 같은 출처의 `/api/*`만 부른다(next.config rewrites가 백엔드로 넘긴다, FE-01-06 A).
import ky from "ky";
import type { ChatRequest } from "./types";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "/api";

/** 상대 기준 주소(`/api`)를 지금 페이지 출처에 붙인다. `Request`가 상대 주소를 받지 않는 환경(Node 시험)에서도 같게 돈다. */
export function resolveApiBase(base: string = API_BASE_URL): string {
  if (/^https?:\/\//.test(base) || typeof location === "undefined") return base;
  return new URL(base, location.origin).toString();
}

export const apiClient = ky.create({
  retry: 0, // POST 자동 재시도 없음(같은 질문이 두 번 처리되지 않게)
  timeout: false, // 스트리밍이라 요청 시간 상한을 두지 않는다. 무응답 상한은 run-stream.ts가 맡는다
  throwHttpErrors: false, // 상태 코드는 stream.ts가 보고 오류로 바꾼다
});

/** `POST /api/chat`. 본문을 읽지 않은 `Response`를 돌려준다(`.json()`을 쓰지 않고 `response.body`를 줄 단위로 읽는다). */
export async function postChatStream(request: ChatRequest, signal?: AbortSignal): Promise<Response> {
  return apiClient.post("chat", {
    prefix: resolveApiBase(),
    json: request,
    signal,
    headers: { Accept: "application/x-ndjson" },
  });
}
