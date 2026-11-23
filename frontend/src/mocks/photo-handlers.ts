// MSW 핸들러: `POST /api/ingest/image`(BE-14 사진 변환). 개발·시험 전용이다.
// 응답 모양은 `features/photo/types.ts`(손으로 적은 계약)와 같다. 픽스처의 약 이름은 **가상**이고 실제 봉투 글자가 아니다.
// 시나리오 고르기(합성 규칙, 실제 서버와 무관): 사진 고르기 시트에는 질문칸이 없어 질문 글자로 고를 수 없으므로 **PNG의 가로 픽셀 수**로 고른다
// (`PHOTO_SCENARIO_PNG_WIDTH`). JPEG·그 밖의 폭은 `ok`다. 시험은 합성 PNG를 만들어 보낸다.
import { HttpResponse, delay, http } from "msw";
import { z } from "zod";
import { INGEST_QUESTION_MAX_CHARS } from "@/features/photo/types";
import type { IngestImageOut } from "@/features/photo/types";
import { MEDICATION_NAME_MAX_CHARS } from "@/lib/api/account";
import { MOCK_DRUG_DICT_VERSION, MOCK_DRUG_SEARCH_ERRORS, MOCK_DRUG_SEARCH_SLOW_MARK, MOCK_DRUG_SEARCH_SLOW_MS, searchMockDrugs } from "./fixtures/account";
import { PHRASES } from "./fixtures/phrases";

export type PhotoScenarioName = "ok" | "unreadable" | "unavailable" | "emergency";

/** 합성 PNG의 가로 픽셀 수 → 시나리오 */
export const PHOTO_SCENARIO_PNG_WIDTH: Readonly<Record<PhotoScenarioName, number>> = { ok: 64, unreadable: 65, unavailable: 66, emergency: 67 };

const EMERGENCY = { text: PHRASES.EMERGENCY_119, tel: PHRASES.EMERGENCY_119_TEL, wide_text: PHRASES.EMERGENCY_119_WIDE };

/** 읽은 약 2개: 하나는 사전 후보 2개(기본 선택 없음), 하나는 후보 없음(글자로만 찾는다) */
const OK_DRUGS: IngestImageOut["drugs"] = [
  {
    read_name: "가나다정",
    read_ingredient: "가나다성분",
    strength_or_form: "100mg",
    candidates: [
      { name: "가나다정 100밀리그램", item_seq: "200000001", entp_name: "합성제약(주)", prescription: "일반의약품", matched_by: "product_name", match_type: "prefix" },
      { name: "가나다정 500밀리그램", item_seq: "200000002", entp_name: "합성제약(주)", prescription: "전문의약품", matched_by: "product_name", match_type: "prefix" },
    ],
  },
  { read_name: "라마바캡슐", read_ingredient: null, strength_or_form: "캡슐", candidates: [] },
];

export const photoScenarios: Readonly<Record<PhotoScenarioName, IngestImageOut>> = {
  ok: { status: "OK", reason: null, drugs: OK_DRUGS, emergency: null, dict_version: MOCK_DRUG_DICT_VERSION, dict_unavailable: false },
  unreadable: { status: "UNREADABLE", reason: "NONE_READ", drugs: [], emergency: null, dict_version: MOCK_DRUG_DICT_VERSION, dict_unavailable: false },
  unavailable: { status: "UNAVAILABLE", reason: "CAP_REACHED", drugs: [], emergency: null, dict_version: MOCK_DRUG_DICT_VERSION, dict_unavailable: false },
  emergency: { status: "OK", reason: null, drugs: OK_DRUGS, emergency: EMERGENCY, dict_version: MOCK_DRUG_DICT_VERSION, dict_unavailable: false },
};

/** 요청 모양(백엔드 `_Strict`: 모르는 칸은 422). `image`는 JPEG·PNG data URL, `question`은 선택 500자 이하 */
const IngestImageInSchema = z.strictObject({
  image: z.string().regex(/^data:image\/(jpeg|png);base64,[A-Za-z0-9+/]+=*$/),
  question: z.string().max(INGEST_QUESTION_MAX_CHARS).optional(),
});

/** `POST /api/ingest/drugs/search` 요청 모양: 로그인 전용 `/drugs/search`의 `DrugSearchIn`과 같다(`q` 앞뒤 공백 제거 뒤 1~100자) */
const IngestDrugSearchInSchema = z.strictObject({ q: z.string().trim().min(1).max(MEDICATION_NAME_MAX_CHARS) });

const PNG_SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];

/** data URL이 PNG면 IHDR의 가로 픽셀 수, 아니면 null(머리 24바이트만 푼다) */
export function pngWidth(dataUrl: string): number | null {
  const at = dataUrl.indexOf(",");
  if (at < 0) return null;
  let bytes: string;
  try {
    bytes = atob(dataUrl.slice(at + 1, at + 1 + 32));
  } catch {
    return null;
  }
  if (bytes.length < 24 || PNG_SIGNATURE.some((value, index) => bytes.charCodeAt(index) !== value)) return null;
  return ((bytes.charCodeAt(16) << 24) | (bytes.charCodeAt(17) << 16) | (bytes.charCodeAt(18) << 8) | bytes.charCodeAt(19)) >>> 0;
}

export function pickPhotoScenario(dataUrl: string): PhotoScenarioName {
  const width = pngWidth(dataUrl);
  return (Object.keys(PHOTO_SCENARIO_PNG_WIDTH) as PhotoScenarioName[]).find((name) => PHOTO_SCENARIO_PNG_WIDTH[name] === width) ?? "ok";
}

export interface PhotoHandlerOptions {
  delayMs?: number;
  /** 시험에서 시나리오를 고정할 때 쓴다 */
  scenario?: PhotoScenarioName;
}

export function createPhotoHandlers({ delayMs = 0, scenario }: PhotoHandlerOptions = {}) {
  return [
    http.post("*/api/ingest/image", async ({ request }) => {
      const parsed = IngestImageInSchema.safeParse(await request.json().catch(() => null));
      if (!parsed.success) {
        const fields = [...new Set(parsed.error.issues.map((issue) => (issue.path[0] ? String(issue.path[0]) : "body")))];
        return HttpResponse.json({ code: "INVALID_REQUEST", fields }, { status: 422, headers: { "Cache-Control": "no-store" } });
      }
      if (delayMs > 0) await delay(delayMs);
      const name = scenario ?? pickPhotoScenario(parsed.data.image);
      // 질문·사진은 되돌려 주지 않는다
      return HttpResponse.json(photoScenarios[name], { headers: { "Cache-Control": "no-store" } });
    }),
    // ---- 확인 카드 행의 사전 후보 검색(2026-11-23 "아스피린 A"): 게스트 허용(토큰을 보지 않는다). 요청·응답은 `POST /api/drugs/search`와 같은 모양(계약 가정)이고
    //      같은 합성 사전(`searchMockDrugs`)을 쓴다. 검색어는 되돌려 주지 않는다. 오류·느림 표식도 로그인 전용 목과 같다
    http.post("*/api/ingest/drugs/search", async ({ request }) => {
      const body = IngestDrugSearchInSchema.safeParse(await request.json().catch(() => null));
      if (!body.success) return HttpResponse.json({ code: "INVALID_REQUEST", fields: ["q"] }, { status: 422, headers: { "Cache-Control": "no-store" } });
      const forced = MOCK_DRUG_SEARCH_ERRORS.find(([mark]) => body.data.q.includes(mark));
      if (forced && forced[1] !== 401) return HttpResponse.json({ code: forced[2], fields: forced[2] === "INVALID_REQUEST" ? ["q"] : [] }, { status: forced[1], headers: { "Cache-Control": "no-store" } });
      if (body.data.q.includes(MOCK_DRUG_SEARCH_SLOW_MARK)) await delay(MOCK_DRUG_SEARCH_SLOW_MS);
      return HttpResponse.json(searchMockDrugs(body.data.q), { headers: { "Cache-Control": "no-store" } });
    }),
    http.get("*/api/ingest/drugs/search", () => new HttpResponse(null, { status: 405, headers: { "Cache-Control": "no-store" } })),
  ];
}
