// `POST /ingest/image`(BE-14, develop `aa0ed8b`) 계약. 원본은 백엔드 `backend/app/api/ingest.py`(`IngestImageIn`·`IngestDrugOut`·`IngestImageOut`)이고,
// 모양은 `pnpm gen:api`(사본 `data/mock/openapi/openapi-v1-be14.json`)가 만든 `lib/api/generated.ts`와 `lib/api/contract-check.ts`가 컴파일 시점에 대조한다.
// - 확신도 칸은 없다(응답에도 화면에도 두지 않는다, PRD-08-06 A). `selected` 같은 기본 선택 칸도 없다
// - `question`은 되돌려 주지 않는다. `emergency`는 서버가 질문 글자를 보고 채운 서버 상수다(프런트 키워드 목록 없음, RFP-35-03)
// - 모르는 칸은 런타임에도 오류다(`strictObject`, 백엔드 `extra="forbid"`와 같다)
import { z } from "zod";
import { DrugCandidateSchema } from "@/lib/api/account";
import type { components } from "@/lib/api/generated";
import { EmergencySchema } from "@/lib/api/schemas";

/** 요청 본문(〔D1〕A: JSON의 data URL, 생성 타입 그대로). `question`은 선택이고 500자 이하다(서버 `QUESTION_MAX_LEN`) */
export type IngestImageIn = components["schemas"]["IngestImageIn"];
export const INGEST_QUESTION_MAX_CHARS = 500;

export const INGEST_STATUSES = ["OK", "UNREADABLE", "UNAVAILABLE"] as const;
export const IngestStatusSchema = z.enum(INGEST_STATUSES);
export type IngestStatus = z.infer<typeof IngestStatusSchema>;

/** 이유 코드. 화면 분기는 `status`로만 한다(상한 도달 `CAP_REACHED`는 `UNAVAILABLE`로 온다) */
export const INGEST_REASONS = ["NONE_READ", "MODEL_ERROR", "REFUSED", "PARSE_ERROR", "CAP_REACHED"] as const;
export const IngestReasonSchema = z.enum(INGEST_REASONS);

/** 사진에서 읽은 약 한 항목(`IngestDrugOut`): 읽은 글자(상품명·성분명·용량/제형)와 사전 후보(≤5, 기본 선택 없음) */
export const IngestDrugSchema = z.strictObject({
  read_name: z.string().nullable(),
  read_ingredient: z.string().nullable(),
  strength_or_form: z.string().nullable(),
  candidates: z.array(DrugCandidateSchema),
});
export type IngestDrug = z.infer<typeof IngestDrugSchema>;

export const IngestImageOutSchema = z.strictObject({
  status: IngestStatusSchema,
  reason: IngestReasonSchema.nullable(),
  drugs: z.array(IngestDrugSchema),
  emergency: EmergencySchema.nullable(),
  /** 사전 공급자가 없거나 적재 실패면 true(후보 빈 목록, 오류로 막지 않는다) */
  dict_unavailable: z.boolean(),
  dict_version: z.string(),
});
export type IngestImageOut = z.infer<typeof IngestImageOutSchema>;
/** fixture·시험이 선택 칸을 생략하고 쓸 때의 입력 모양 */
export type IngestImageOutInput = z.input<typeof IngestImageOutSchema>;
