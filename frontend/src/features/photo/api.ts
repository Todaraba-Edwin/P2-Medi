// `POST /api/ingest/image`(BE-14, rewrites 경유 백엔드 `/ingest/image`). 게스트 허용(〔D3〕A)이라 토큰을 붙이지 않는다.
// 이 호출은 판정·그래프와 무관한 변환 함수다(H19): 승인 카드에서 `이대로 확인`을 누르기 전에는 `/chat`을 부르지 않는다(〔D7〕A).
// 응답에 사진·질문은 되돌아오지 않고, 요청의 data URL은 이 함수 밖(부르는 쪽)에서 바로 버린다.
import { DRUG_QUERY_MAX_CHARS, DrugSearchResultSchema } from "@/lib/api/account";
import type { DrugSearchBody, DrugSearchResult } from "@/lib/api/account";
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

// ---------------------------------------------------------------- 확인 카드 행의 사전 후보 검색(2026-11-23 사용자 결정 "아스피린 A")
/** 입력이 멈춘 뒤 이만큼 지나야 찾는다(글자마다 부르지 않는다) */
export const PHOTO_ROW_SEARCH_DEBOUNCE_MS = 400;
/** 앞뒤 공백을 뺀 글자가 이보다 짧으면 찾지 않는다 */
export const PHOTO_ROW_SEARCH_MIN_CHARS = 2;
export { DRUG_QUERY_MAX_CHARS as PHOTO_ROW_SEARCH_MAX_CHARS };

/**
 * `POST /api/ingest/drugs/search`(백엔드 `ingest.py`, 게스트 허용): 확인 카드에서 직접 추가하거나 글자를 고친 행의 사전 후보를 찾는다.
 * 요청·응답 모양은 로그인 전용 `POST /drugs/search`(`lib/api/account.ts`의 `DrugSearchIn`·`DrugSearchOut`)와 같고 경로만 다르다(계약 가정, 생성 타입은 손대지 않았다).
 * - 토큰을 붙이지 않는다(사진 모달은 게스트도 쓴다). 검색어·후보는 상태(메모리)에만 있고 로그·저장소에 남기지 않는다
 * - 이 호출도 판정·그래프와 무관하다(H19): 확인 전에 `/chat`을 부르지 않는 규칙은 그대로다
 * - 실패(연결·상태 코드·모양)는 `PhotoApiError`로 던지고 부르는 쪽이 "후보 없음"으로 조용히 처리한다. 끊은 요청은 그대로 던진다
 */
export async function searchIngestDrugs(q: string, signal?: AbortSignal): Promise<DrugSearchResult> {
  const body: DrugSearchBody = { q };
  let response: Response;
  try {
    response = await apiClient.post("ingest/drugs/search", { prefix: resolveApiBase(), json: body, signal, headers: { Accept: "application/json" } });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new PhotoApiError("network", 0);
  }
  if (!response.ok) throw new PhotoApiError("http", response.status);
  const parsed = DrugSearchResultSchema.safeParse(await response.json().catch(() => null));
  if (!parsed.success) throw new PhotoApiError("invalid", response.status);
  return parsed.data;
}
