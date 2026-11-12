import type { z } from "zod";
import type {
  AnswerEventSchema,
  BadgeSchema,
  ChatEventSchema,
  ChatRequestSchema,
  ChatResponseSchema,
  CitationSchema,
  DateLineSchema,
  DetailItemSchema,
  DoneEventSchema,
  EmergencyEventSchema,
  EmergencySchema,
  EndReasonSchema,
  ErrorEventSchema,
  FindingSchema,
  ProgressEventSchema,
  ProgressStageSchema,
  SentenceRefSchema,
} from "./schemas";

export type ChatRequest = z.infer<typeof ChatRequestSchema>;
export type ChatResponse = z.infer<typeof ChatResponseSchema>;
/** fixture·시험이 기본값 칸을 생략하고 쓸 때의 입력 모양 */
export type ChatResponseInput = z.input<typeof ChatResponseSchema>;
export type DateLine = z.infer<typeof DateLineSchema>;
export type Citation = z.infer<typeof CitationSchema>;
export type DetailItem = z.infer<typeof DetailItemSchema>;
export type Finding = z.infer<typeof FindingSchema>;
export type Badge = z.infer<typeof BadgeSchema>;
export type SentenceRef = z.infer<typeof SentenceRefSchema>;
export type Emergency = z.infer<typeof EmergencySchema>;
export type EndReason = z.infer<typeof EndReasonSchema>;
export type ProgressStage = z.infer<typeof ProgressStageSchema>;

export type ChatEvent = z.infer<typeof ChatEventSchema>;
export type ChatEventInput = z.input<typeof ChatEventSchema>;
export type ProgressEvent = z.infer<typeof ProgressEventSchema>;
export type EmergencyEvent = z.infer<typeof EmergencyEventSchema>;
export type AnswerEvent = z.infer<typeof AnswerEventSchema>;
export type ErrorEvent = z.infer<typeof ErrorEventSchema>;
export type DoneEvent = z.infer<typeof DoneEventSchema>;
