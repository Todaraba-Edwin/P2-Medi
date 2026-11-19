// 계약 대조(컴파일 시점). 실행되는 코드는 없다: `pnpm typecheck`가 이 파일로 zod 스키마와 생성 타입의 어긋남을 잡는다.
// 백엔드 스키마가 바뀌면 `pnpm gen:api` → 여기서 오류 → schemas.ts를 맞춘다.
//
// 보는 것 두 가지
// 1. zod 검증을 통과한 모양(기본값이 채워진 뒤)은 모두 OpenAPI 모양 안에 있다(zod가 더 엄격한 것은 괜찮다: 라벨·날짜 형식 등).
// 2. 모델마다 칸 이름 집합이 같다(백엔드가 칸을 더하거나 빼면 여기서 걸린다. zod가 `.strict()`라 모르는 칸은 런타임에도 오류다).
import type { z } from "zod";
import type { components } from "./generated";
import type * as A from "./account";
import type * as S from "./schemas";

type Gen = components["schemas"];
type Extends<A, B> = [A] extends [B] ? true : false;
type SameKeys<A, B> = [keyof A] extends [keyof B] ? ([keyof B] extends [keyof A] ? true : false) : false;
type Expect<T extends true> = T;
/** zod를 통과한 모양 ⊆ 생성 타입, 칸 이름 집합 같음 */
type Conforms<Schema extends z.ZodType, G> = Extends<z.output<Schema>, G> extends true ? SameKeys<z.output<Schema>, G> : false;

export type ContractChecks = [
  Expect<Conforms<typeof S.DateLineSchema, Gen["DateLine"]>>,
  Expect<Conforms<typeof S.CitationSchema, Gen["Citation"]>>,
  Expect<Conforms<typeof S.QuoteSchema, Gen["Quote"]>>,
  Expect<Conforms<typeof S.SentenceRefSchema, Gen["SentenceRef"]>>,
  Expect<Conforms<typeof S.DetailItemSchema, Gen["DetailItem"]>>,
  Expect<Conforms<typeof S.IngredientSchema, Gen["Ingredient"]>>,
  Expect<Conforms<typeof S.BadgeSchema, Gen["Badge"]>>,
  Expect<Conforms<typeof S.SearchedSchema, Gen["Searched"]>>,
  Expect<Conforms<typeof S.FindingSchema, Gen["Finding"]>>,
  Expect<Conforms<typeof S.CandidateSchema, Gen["Candidate"]>>,
  Expect<Conforms<typeof S.NameCorrectionSchema, Gen["NameCorrection"]>>,
  Expect<Conforms<typeof S.EmergencySchema, Gen["Emergency"]>>,
  Expect<Conforms<typeof S.GradeDefSchema, Gen["GradeDef"]>>,
  Expect<Conforms<typeof S.PairRefSchema, Gen["PairRef"]>>,
  Expect<Conforms<typeof S.PairFoundSchema, Gen["PairFound"]>>,
  Expect<Conforms<typeof S.ResultSummarySchema, Gen["ResultSummary"]>>,
  Expect<Conforms<typeof S.RestFoldSchema, Gen["RestFold"]>>,
  Expect<Conforms<typeof S.DoseCheckSchema, Gen["DoseCheck"]>>,
  Expect<Conforms<typeof S.ChatResponseSchema, Gen["ChatResponse"]>>,
  Expect<Conforms<typeof S.AgeInputSchema, Gen["AgeInput"]>>,
  Expect<Conforms<typeof S.ConfirmedDrugSchema, Gen["ConfirmedDrug"]>>,
  Expect<Conforms<typeof S.RequestContextSchema, Gen["ConversationContext"]>>,
  Expect<Conforms<typeof S.ChatRequestSchema, Gen["ChatRequest"]>>,
  Expect<Conforms<typeof S.ErrorBodySchema, Gen["ErrorBody"]>>,
  Expect<Conforms<typeof S.ProgressEventSchema, Gen["ProgressEvent"]>>,
  Expect<Conforms<typeof S.EmergencyEventSchema, Gen["EmergencyEvent"]>>,
  Expect<Conforms<typeof S.AnswerEventSchema, Gen["AnswerEvent"]>>,
  Expect<Conforms<typeof S.ErrorEventSchema, Gen["ErrorEvent"]>>,
  Expect<Conforms<typeof S.DoneEventSchema, Gen["DoneEvent"]>>,
  Expect<Extends<z.output<typeof S.ChatEventSchema>, Gen["ChatEvent"]>>,
  // 값 목록(enum)은 양쪽이 같아야 한다
  Expect<Extends<Gen["ProgressEvent"]["stage"], z.infer<typeof S.ProgressStageSchema>>>,
  Expect<Extends<Gen["ErrorEvent"]["code"], z.infer<typeof S.ErrorCodeSchema>>>,
  Expect<Extends<Gen["ChatResponse"]["route"], z.infer<typeof S.RouteSchema>>>,
  Expect<Extends<NonNullable<Gen["ChatResponse"]["end_reason"]>, z.infer<typeof S.EndReasonSchema>>>,
  Expect<Extends<Gen["Finding"]["bucket"], z.infer<typeof S.BucketSchema>>>,
  Expect<Extends<NonNullable<Gen["Finding"]["target"]>, z.infer<typeof S.TargetSchema>>>,
  Expect<Extends<NonNullable<Gen["Finding"]["section"]>, z.infer<typeof S.SectionSchema>>>,
  Expect<Extends<NonNullable<Gen["Badge"]["grade"]>, z.infer<typeof S.GradeSchema>>>,
  Expect<Extends<NonNullable<Gen["Badge"]["source"]>, z.infer<typeof S.SourceKindSchema>>>,
  Expect<Extends<NonNullable<Gen["GradeDef"]["missing_reason"]>, z.infer<typeof S.GradeMissingReasonSchema>>>,
  Expect<Extends<NonNullable<Gen["ChatResponse"]["pharmacist_advice_kinds"]>[number], z.infer<typeof S.AdviceKindSchema>>>,
  Expect<Extends<NonNullable<Gen["AgeInput"]["unit"]>, z.infer<typeof S.AgeUnitSchema>>>,
  Expect<Extends<Gen["ChatResponse"]["schema_version"], typeof S.CHAT_RESPONSE_SCHEMA_VERSION | undefined>>,
  Expect<Extends<Gen["DoneEvent"]["schema_version"], typeof S.CHAT_EVENT_SCHEMA_VERSION | undefined>>,
  // ---- 계정 API(BE-11, `account.ts`): 응답 모양과 값 목록
  Expect<Conforms<typeof A.LegalDocSchema, Gen["LegalDocumentOut"]>>,
  Expect<Conforms<typeof A.ConsentStateSchema, Gen["ConsentState"]>>,
  Expect<Conforms<typeof A.MeSchema, Gen["MeResponse"]>>,
  Expect<Conforms<typeof A.MedicationSchema, Gen["MedicationOut"]>>,
  Expect<Conforms<typeof A.ProfileSchema, Gen["ProfileOut"]>>,
  Expect<Extends<Gen["LegalDocumentOut"]["doc_type"], A.LegalDocType>>,
  Expect<Extends<Gen["LegalDocumentOut"]["legal_review"], z.infer<typeof A.LegalReviewSchema>>>,
  Expect<Extends<Gen["ConsentState"]["doc_type"], A.ConsentDocType>>,
  Expect<Extends<Gen["MeResponse"]["onboarding_step"], A.OnboardingStep>>,
  Expect<Extends<Gen["ProfileOut"]["relation"], A.Relation>>,
  Expect<Extends<NonNullable<Gen["ProfileOut"]["age_band"]>, A.AgeBand>>,
  Expect<Extends<NonNullable<Gen["ProfileOut"]["pregnancy_status"]>, A.PregnancyStatus>>,
];
