// 화면·스토어가 쓰는 타입. zod 검증을 통과한 뒤의 모양이다(기본값이 채워져 선택 칸이 없다).
// 백엔드 OpenAPI에서 만든 타입(generated.ts)과의 대조는 contract-check.ts가 한다.
import type { z } from "zod";
import type {
  AgeInputSchema,
  AnswerEventSchema,
  BadgeSchema,
  CandidateSchema,
  ChatEventSchema,
  ChatRequestSchema,
  ChatResponseSchema,
  CitationSchema,
  ConfirmedDrugSchema,
  DateLineSchema,
  DetailItemSchema,
  DoneEventSchema,
  EmergencyEventSchema,
  EmergencySchema,
  GradeDefSchema,
  EndReasonSchema,
  ErrorBodySchema,
  ErrorCodeSchema,
  ErrorEventSchema,
  FindingSchema,
  IngredientSchema,
  NameCorrectionSchema,
  ProgressEventSchema,
  ProgressStageSchema,
  RequestContextSchema,
  SearchedSchema,
  SentenceRefSchema,
} from "./schemas";

/** 요청 본문(보내는 쪽 모양). `context`를 생략하면 빈 묶음으로 간다 */
export type ChatRequest = z.input<typeof ChatRequestSchema>;
export type RequestContext = z.input<typeof RequestContextSchema>;
export type AgeInput = z.input<typeof AgeInputSchema>;
export type ConfirmedDrug = z.input<typeof ConfirmedDrugSchema>;
export type ErrorBody = z.infer<typeof ErrorBodySchema>;

export type ChatResponse = z.infer<typeof ChatResponseSchema>;
/** fixture·시험이 기본값 칸을 생략하고 쓸 때의 입력 모양 */
export type ChatResponseInput = z.input<typeof ChatResponseSchema>;
export type DateLine = z.infer<typeof DateLineSchema>;
export type Citation = z.infer<typeof CitationSchema>;
export type DetailItem = z.infer<typeof DetailItemSchema>;
export type Finding = z.infer<typeof FindingSchema>;
export type Badge = z.infer<typeof BadgeSchema>;
export type Ingredient = z.infer<typeof IngredientSchema>;
export type Searched = z.infer<typeof SearchedSchema>;
export type Candidate = z.infer<typeof CandidateSchema>;
export type NameCorrection = z.infer<typeof NameCorrectionSchema>;
export type SentenceRef = z.infer<typeof SentenceRefSchema>;
export type Emergency = z.infer<typeof EmergencySchema>;
export type GradeDef = z.infer<typeof GradeDefSchema>;
export type EndReason = z.infer<typeof EndReasonSchema>;
export type ProgressStage = z.infer<typeof ProgressStageSchema>;
export type ErrorCode = z.infer<typeof ErrorCodeSchema>;

export type ChatEvent = z.infer<typeof ChatEventSchema>;
export type ChatEventInput = z.input<typeof ChatEventSchema>;
export type ProgressEvent = z.infer<typeof ProgressEventSchema>;
export type EmergencyEvent = z.infer<typeof EmergencyEventSchema>;
export type AnswerEvent = z.infer<typeof AnswerEventSchema>;
export type ErrorEvent = z.infer<typeof ErrorEventSchema>;
export type DoneEvent = z.infer<typeof DoneEventSchema>;
