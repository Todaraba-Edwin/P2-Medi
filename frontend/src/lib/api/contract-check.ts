// 계약 대조(컴파일 시점). 실행되는 코드는 없다: `pnpm typecheck`가 이 파일로 zod 스키마와 생성 타입의 어긋남을 잡는다.
// 백엔드 스키마가 바뀌면 `pnpm gen:api` → 여기서 오류 → schemas.ts를 맞춘다.
//
// 보는 것 두 가지
// 1. zod 검증을 통과한 모양(기본값이 채워진 뒤)은 모두 OpenAPI 모양 안에 있다(zod가 더 엄격한 것은 괜찮다: 라벨·날짜 형식 등).
// 2. 모델마다 칸 이름 집합이 같다(백엔드가 칸을 더하거나 빼면 여기서 걸린다. zod가 `.strict()`라 모르는 칸은 런타임에도 오류다).
import type { z } from "zod";
import type { components } from "./generated";
import type * as S from "./schemas";

type Gen = components["schemas"];
type Extends<A, B> = [A] extends [B] ? true : false;
type SameKeys<A, B> = [keyof A] extends [keyof B] ? ([keyof B] extends [keyof A] ? true : false) : false;
type Expect<T extends true> = T;
/** zod를 통과한 모양 ⊆ 생성 타입, 칸 이름 집합 같음 */
type Conforms<Schema extends z.ZodType, G> = Extends<z.output<Schema>, G> extends true ? SameKeys<z.output<Schema>, G> : false;

// TODO(BE-06-40 A): 서버 `Ingredient.contra_kinds`·`dup`이 `None`(모름)을 받게 된 뒤 `pnpm gen:api`로 다시 만들고, 아래 임시 타입 다섯 개를
// 지우고 대조를 `Gen["Ingredient"]`·`Gen["Finding"]`·`Gen["ChatResponse"]`·`Gen["AnswerEvent"]`·`Gen["ChatEvent"]`로 되돌린다.
// 그때까지는 프런트가 먼저 `null`을 받으므로(서버보다 넓음) 이 두 칸의 값 모양만 넓혀서 대조한다. 칸 이름 집합과 나머지 칸은 그대로 대조된다
type Replace<T, R> = Omit<T, keyof R> & R;
type IngredientGen = Replace<Gen["Ingredient"], { contra_kinds?: string[] | null; dup?: boolean | null }>;
type FindingGen = Replace<Gen["Finding"], { ingredients?: IngredientGen[] }>;
type ChatResponseGen = Replace<Gen["ChatResponse"], { findings?: FindingGen[] }>;
type AnswerEventGen = Replace<Gen["AnswerEvent"], { response: ChatResponseGen }>;

export type ContractChecks = [
  Expect<Conforms<typeof S.DateLineSchema, Gen["DateLine"]>>,
  Expect<Conforms<typeof S.CitationSchema, Gen["Citation"]>>,
  Expect<Conforms<typeof S.QuoteSchema, Gen["Quote"]>>,
  Expect<Conforms<typeof S.SentenceRefSchema, Gen["SentenceRef"]>>,
  Expect<Conforms<typeof S.DetailItemSchema, Gen["DetailItem"]>>,
  Expect<Conforms<typeof S.IngredientSchema, IngredientGen>>,
  Expect<Conforms<typeof S.BadgeSchema, Gen["Badge"]>>,
  Expect<Conforms<typeof S.SearchedSchema, Gen["Searched"]>>,
  Expect<Conforms<typeof S.FindingSchema, FindingGen>>,
  Expect<Conforms<typeof S.CandidateSchema, Gen["Candidate"]>>,
  Expect<Conforms<typeof S.NameCorrectionSchema, Gen["NameCorrection"]>>,
  Expect<Conforms<typeof S.EmergencySchema, Gen["Emergency"]>>,
  Expect<Conforms<typeof S.GradeDefSchema, Gen["GradeDef"]>>,
  Expect<Conforms<typeof S.ChatResponseSchema, ChatResponseGen>>,
  Expect<Conforms<typeof S.AgeInputSchema, Gen["AgeInput"]>>,
  Expect<Conforms<typeof S.ConfirmedDrugSchema, Gen["ConfirmedDrug"]>>,
  Expect<Conforms<typeof S.RequestContextSchema, Gen["ConversationContext"]>>,
  Expect<Conforms<typeof S.ChatRequestSchema, Gen["ChatRequest"]>>,
  Expect<Conforms<typeof S.ErrorBodySchema, Gen["ErrorBody"]>>,
  Expect<Conforms<typeof S.ProgressEventSchema, Gen["ProgressEvent"]>>,
  Expect<Conforms<typeof S.EmergencyEventSchema, Gen["EmergencyEvent"]>>,
  Expect<Conforms<typeof S.AnswerEventSchema, AnswerEventGen>>,
  Expect<Conforms<typeof S.ErrorEventSchema, Gen["ErrorEvent"]>>,
  Expect<Conforms<typeof S.DoneEventSchema, Gen["DoneEvent"]>>,
  Expect<Extends<z.output<typeof S.ChatEventSchema>, Exclude<Gen["ChatEvent"], Gen["AnswerEvent"]> | AnswerEventGen>>,
  // 값 목록(enum)은 양쪽이 같아야 한다
  Expect<Extends<Gen["ProgressEvent"]["stage"], z.infer<typeof S.ProgressStageSchema>>>,
  Expect<Extends<Gen["ErrorEvent"]["code"], z.infer<typeof S.ErrorCodeSchema>>>,
  Expect<Extends<Gen["ChatResponse"]["route"], z.infer<typeof S.RouteSchema>>>,
  Expect<Extends<NonNullable<Gen["ChatResponse"]["end_reason"]>, z.infer<typeof S.EndReasonSchema>>>,
  Expect<Extends<Gen["Finding"]["bucket"], z.infer<typeof S.BucketSchema>>>,
  Expect<Extends<NonNullable<Gen["Finding"]["target"]>, z.infer<typeof S.TargetSchema>>>,
  Expect<Extends<NonNullable<Gen["Badge"]["grade"]>, z.infer<typeof S.GradeSchema>>>,
  Expect<Extends<NonNullable<Gen["Badge"]["source"]>, z.infer<typeof S.SourceKindSchema>>>,
  Expect<Extends<NonNullable<Gen["GradeDef"]["missing_reason"]>, z.infer<typeof S.GradeMissingReasonSchema>>>,
  Expect<Extends<NonNullable<Gen["ChatResponse"]["pharmacist_advice_kinds"]>[number], z.infer<typeof S.AdviceKindSchema>>>,
  Expect<Extends<NonNullable<Gen["AgeInput"]["unit"]>, z.infer<typeof S.AgeUnitSchema>>>,
  Expect<Extends<Gen["ChatResponse"]["schema_version"], typeof S.CHAT_RESPONSE_SCHEMA_VERSION | undefined>>,
  Expect<Extends<Gen["DoneEvent"]["schema_version"], typeof S.CHAT_EVENT_SCHEMA_VERSION | undefined>>,
];
