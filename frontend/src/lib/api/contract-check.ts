// 계약 대조(컴파일 시점). 실행되는 코드는 없다: `pnpm typecheck`가 이 파일로 zod 스키마와 생성 타입의 어긋남을 잡는다.
// 백엔드 스키마가 바뀌면 `pnpm gen:api` → 여기서 오류 → schemas.ts를 맞춘다.
//
// 보는 것 두 가지
// 1. zod 검증을 통과한 모양(기본값이 채워진 뒤)은 모두 OpenAPI 모양 안에 있다(zod가 더 엄격한 것은 괜찮다: 라벨·날짜 형식 등).
// 2. 모델마다 칸 이름 집합이 같다(백엔드가 칸을 더하거나 빼면 여기서 걸린다. zod가 `.strict()`라 모르는 칸은 런타임에도 오류다).
import type { z } from "zod";
import type { components } from "./generated";
import type * as P from "@/features/photo/types";
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
  // 기본 대상(FE-17 U-08, `PUT /me/default-target`): 응답 모양, 본문 칸, `MeResponse.default_target`
  Expect<Conforms<typeof A.DefaultTargetResultSchema, Gen["DefaultTargetOut"]>>,
  Expect<SameKeys<A.DefaultTargetBody, { target: A.DefaultTarget }>>,
  Expect<Extends<A.DefaultTarget, A.DefaultTargetBody["target"]>>,
  Expect<Extends<NonNullable<A.Me["default_target"]> | null, NonNullable<Gen["MeResponse"]["default_target"]> | null>>,
  Expect<Extends<Gen["LegalDocumentOut"]["doc_type"], A.LegalDocType>>,
  Expect<Extends<Gen["LegalDocumentOut"]["legal_review"], z.infer<typeof A.LegalReviewSchema>>>,
  Expect<Extends<Gen["ConsentState"]["doc_type"], A.ConsentDocType>>,
  Expect<Extends<Gen["MeResponse"]["onboarding_step"], A.OnboardingStep>>,
  Expect<Extends<Gen["ProfileOut"]["relation"], A.Relation>>,
  Expect<Extends<NonNullable<Gen["ProfileOut"]["age_band"]>, A.AgeBand>>,
  Expect<Extends<NonNullable<Gen["ProfileOut"]["pregnancy_status"]>, A.PregnancyStatus>>,
  // 성별(FE-11-09 C): 값 목록이 양쪽 같고, 요청 모델 두 개에도 같은 칸이 있다
  // 병아리 배경색(FE-17 U-01): 값 목록이 양쪽 같고, 요청 두 모델에도 같은 칸이 있다
  Expect<Extends<Gen["ProfileOut"]["avatar_color"], A.AvatarColor>>,
  Expect<Extends<A.AvatarColor, Gen["ProfileOut"]["avatar_color"]>>,
  Expect<Extends<A.AvatarColor, Gen["ProfileCreate"]["avatar_color"]>>,
  Expect<Extends<A.AvatarColor, NonNullable<Gen["ProfileUpdate"]["avatar_color"]>>>,
  Expect<Extends<NonNullable<Gen["ProfileOut"]["sex"]>, A.Sex>>,
  Expect<Extends<A.Sex, NonNullable<Gen["ProfileOut"]["sex"]>>>,
  Expect<Extends<A.Sex | null, Gen["ProfileCreate"]["sex"]>>,
  Expect<Extends<A.Sex | null, Gen["ProfileUpdate"]["sex"]>>,
  // 만 14세 확인(PRD-17-12 A)은 동의 대상 문서 목록에 있다
  Expect<Extends<"age_14", Gen["ConsentState"]["doc_type"]>>,
  Expect<Extends<A.ConsentDocType, Gen["ConsentItem"]["doc_type"]>>,
  // `/chat` 요청에는 성별 칸이 없다(S10: 성별을 외부 AI로 보내지 않는다). 칸이 생기면 여기서 걸린다
  Expect<Extends<"sex" extends keyof Gen["ConversationContext"] ? false : true, true>>,
  Expect<Extends<"sex" extends keyof Gen["ChatRequest"] ? false : true, true>>,
  // 프로필 약 검색(FE-04-13 A, `POST /drugs/search`)
  Expect<Conforms<typeof A.DrugCandidateSchema, Gen["DrugCandidateOut"]>>,
  Expect<Conforms<typeof A.DrugSearchResultSchema, Gen["DrugSearchOut"]>>,
  Expect<Extends<Gen["DrugCandidateOut"]["matched_by"], A.DrugMatchedBy>>,
  Expect<Extends<A.DrugMatchedBy, Gen["DrugCandidateOut"]["matched_by"]>>,
  Expect<SameKeys<A.DrugSearchBody, { q: string }>>,
  // 사진 약 이름 추출(BE-14 `POST /ingest/image`, FE-05): 응답 두 모델과 상태·이유 값 목록, 요청 칸(`image`·`question`)
  Expect<Conforms<typeof P.IngestDrugSchema, Gen["IngestDrugOut"]>>,
  Expect<Conforms<typeof P.IngestImageOutSchema, Gen["IngestImageOut"]>>,
  Expect<Extends<Gen["IngestImageOut"]["status"], P.IngestStatus>>,
  Expect<Extends<P.IngestStatus, Gen["IngestImageOut"]["status"]>>,
  Expect<Extends<NonNullable<Gen["IngestImageOut"]["reason"]>, z.infer<typeof P.IngestReasonSchema>>>,
  Expect<Extends<z.infer<typeof P.IngestReasonSchema>, NonNullable<Gen["IngestImageOut"]["reason"]>>>,
  Expect<SameKeys<Required<P.IngestImageIn>, { image: string; question: string | null }>>,
];
