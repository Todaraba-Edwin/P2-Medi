// `POST /api/ingest/image`(BE-14, rewrites 경유 백엔드 `/ingest/image`). 게스트 허용(〔D3〕A)이라 토큰을 붙이지 않는다.
// 이 호출은 판정·그래프와 무관한 변환 함수다(H19): 승인 카드에서 `이대로 확인`을 누르기 전에는 `/chat`을 부르지 않는다(〔D7〕A).
// 응답에 사진·질문은 되돌아오지 않고, 요청의 data URL은 이 함수 밖(부르는 쪽)에서 바로 버린다.
import { apiClient, resolveApiBase } from "@/lib/api/client";
import { IngestImageOutSchema } from "./types";
import type { IngestImageIn, IngestImageOut } from "./types";

export type PhotoApiErrorKind = "network" | "http" | "invalid";

/** 변환 API 실패. 상태 코드만 싣고 본문·입력 값은 싣지 않는다 */
export class PhotoApiError extends Error {
  constructor(
    readonly kind: PhotoApiErrorKind,
    readonly status: number,
  ) {
    super(`photo api ${kind} ${status}`);
    this.name = "PhotoApiError";
  }
}

export async function postIngestImage(body: IngestImageIn, signal?: AbortSignal): Promise<IngestImageOut> {
  let response: Response;
  try {
    response = await apiClient.post("ingest/image", { prefix: resolveApiBase(), json: body, signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal?.aborted) throw error; // 닫기로 끊은 요청은 실패가 아니다
    throw new PhotoApiError("network", 0);
  }
  if (!response.ok) throw new PhotoApiError("http", response.status);
  const parsed = IngestImageOutSchema.safeParse(await response.json().catch(() => null));
  if (!parsed.success) throw new PhotoApiError("invalid", response.status);
  return parsed.data;
}
