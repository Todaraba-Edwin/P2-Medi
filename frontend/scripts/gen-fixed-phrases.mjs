// 응답이 없는 화면용 고정 문구 생성기(f5 A 2026-11-12, 시작 화면 안내까지 넓힘: FE-01-19 A·FE-01-24 A).
// backend/app/agent/fixed_phrases.py·backend/app/tools/provenance.py를 읽기만 해서 아래 값만 꺼낸다. 다른 상수는 더하지 않는다.
// - FIXED_NOTICE·DISCLAIMER: 응답 없는 오류 화면, 응답을 받기 전의 상시 고지
// - START_EMERGENCY_119·START_EXTERNAL_AI_NOTICE: 시작 화면 안내 2종(문구 승인 2026-11-16, tickets/agent/AG-08.md §5 승인 문구 표 1·2번)
// - NOTICE_API_FAIL·API_FLAG_NOTES: 실시간 확인 실패 배너·줄 노트의 **판별용** 원문(FE-11-10 A, 2026-11-20). 화면에 그리는 값이 아니라
//   응답의 `notice`·`findings[].notes[]`가 이 글자이면 본문에 두지 않고 근거 상세로 옮기기 위한 비교 기준이다(고지 배치는 화면 몫).
//   서버 조립: `finalize._notes` → `provenance.api_flag_note` = FLAG_NOTES[API_FAIL·API_PAIR_INCOMPLETE] 또는 API_REASON_NOTES[사유]
// 실행: node scripts/gen-fixed-phrases.mjs
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = path.resolve(here, "../../backend/app/agent/fixed_phrases.py");
const PROVENANCE = path.resolve(here, "../../backend/app/tools/provenance.py");
const TARGET = path.resolve(here, "../src/lib/fixed/phrases.generated.ts");

function constant(text, name) {
  const match = new RegExp(`^${name}\\s*=\\s*"((?:[^"\\\\]|\\\\.)*)"`, "m").exec(text);
  if (!match) throw new Error(`fixed_phrases.py에서 ${name}을 찾지 못했다`);
  return match[1];
}

function tuple(text, name) {
  const block = new RegExp(`^${name}\\s*=\\s*\\(([\\s\\S]*?)\\n\\)`, "m").exec(text);
  const items = block ? [...block[1].matchAll(/"((?:[^"\\]|\\.)*)"/g)].map((m) => m[1]) : [];
  if (items.length === 0) throw new Error(`fixed_phrases.py에서 ${name}을 찾지 못했다`);
  return items;
}

/** 파이썬 dict 블록(`NAME = {` … `\n}`) 안에서 `KEY: "..."` 한 줄의 글자. 키는 `"API_FAIL"`처럼 따옴표째 또는 식별자다 */
function dictValue(text, dictName, key, file) {
  const block = new RegExp(`^${dictName}\\s*=\\s*\\{([\\s\\S]*?)\\n\\}`, "m").exec(text);
  if (!block) throw new Error(`${file}에서 ${dictName}을 찾지 못했다`);
  const match = new RegExp(`^\\s*${key}\\s*:\\s*"((?:[^"\\\\]|\\\\.)*)"\\s*,`, "m").exec(block[1]);
  if (!match) throw new Error(`${file}의 ${dictName}에서 ${key}를 찾지 못했다(이어 붙인 문자열이면 생성하지 않는다)`);
  return match[1];
}

function requireLine(text, line) {
  if (!text.includes(line)) throw new Error(`조립 규칙이 바뀌었다: ${line}`);
}

const py = readFileSync(SOURCE, "utf8");
const prov = readFileSync(PROVENANCE, "utf8");
// 조립 규칙이 원본과 같은지 먼저 본다(바뀌면 생성하지 않고 멈춘다)
requireLine(py, 'FIXED_NOTICE = f"{NOT_SAFE_NOTICE} {PHARMACIST_CHECK_NOTICE}"');
requireLine(py, 'DISCLAIMER = " · ".join(DISCLAIMER_PARTS)');

const fixedNotice = `${constant(py, "NOT_SAFE_NOTICE")} ${constant(py, "PHARMACIST_CHECK_NOTICE")}`;
const disclaimer = tuple(py, "DISCLAIMER_PARTS").join(" · ");
// 시작 화면 안내 2종은 `^NAME = "..."` 한 줄 글자 그대로다(원본 주석: 이어 붙이기·f-string으로 바꾸지 않는다)
const startEmergency = constant(py, "START_EMERGENCY_119");
const startExternalAi = constant(py, "START_EXTERNAL_AI_NOTICE");
// 승인 전 초안(DRAFT_KEYS)에 이름이 있으면 화면에 내지 않는다(생성하지 않고 멈춘다)
const drafts = /^DRAFT_KEYS[^\n]*$/m.exec(py)?.[0] ?? "";
for (const name of ["START_EMERGENCY_119", "START_EXTERNAL_AI_NOTICE"]) {
  if (drafts.includes(`"${name}"`)) throw new Error(`${name}은 아직 승인 전 초안이다(DRAFT_KEYS)`);
}

// 실시간 확인 실패 배너·줄 노트(FE-11-10 A): 화면에 그리지 않고 **판별에만** 쓴다. 서버가 `notice`·`notes[]`에 넣는 글자와 같아야 한다
requireLine(py, "from app.tools.provenance import API_REASON_NOTES as _API_REASON_NOTES");
requireLine(py, "API_REASON_NOTES = dict(_API_REASON_NOTES)");
const noticeApiFail = constant(py, "NOTICE_API_FAIL");
const apiFlagNotes = [
  dictValue(prov, "FLAG_NOTES", '"API_FAIL"', "provenance.py"),
  dictValue(prov, "FLAG_NOTES", '"API_PAIR_INCOMPLETE"', "provenance.py"),
  dictValue(prov, "API_REASON_NOTES", "API_REASON_NO_CODE", "provenance.py"),
  dictValue(prov, "API_REASON_NOTES", "API_REASON_PARTIAL", "provenance.py"),
  dictValue(prov, "API_REASON_NOTES", "API_REASON_TRUNCATED", "provenance.py"),
];

const out = `// 생성 파일이다. 손으로 고치지 않는다.
// 원본: backend/app/agent/fixed_phrases.py (FIXED_NOTICE, DISCLAIMER, START_EMERGENCY_119, START_EXTERNAL_AI_NOTICE, NOTICE_API_FAIL),
//       backend/app/tools/provenance.py (FLAG_NOTES[API_FAIL·API_PAIR_INCOMPLETE], API_REASON_NOTES → API_FLAG_NOTES)
// 다시 만들기: node scripts/gen-fixed-phrases.mjs
// 쓰는 곳: 응답을 받지 못한 화면뿐이다(f5 A, FE-01-19 A). 응답이 있으면 응답 값을 쓴다.
// - FIXED_NOTICE·DISCLAIMER: 응답 없는 오류 화면, 응답을 받기 전의 상시 고지
// - START_EMERGENCY_119·START_EXTERNAL_AI_NOTICE: 시작 화면 안내(질문을 보내기 전)
// - NOTICE_API_FAIL·API_FLAG_NOTES: 화면에 그리지 않는다. 응답의 \`notice\`·\`findings[].notes[]\`가 이 글자이면 본문이 아니라 근거 상세에만
//   둔다(FE-11-10 A "고지 배치는 화면 몫", \`features/result/realtime-notice.ts\`). 응답 글자가 바뀌면 이 값도 다시 만든다
export const FIXED_NOTICE = ${JSON.stringify(fixedNotice)};
export const DISCLAIMER = ${JSON.stringify(disclaimer)};
export const START_EMERGENCY_119 = ${JSON.stringify(startEmergency)};
export const START_EXTERNAL_AI_NOTICE = ${JSON.stringify(startExternalAi)};
export const NOTICE_API_FAIL = ${JSON.stringify(noticeApiFail)};
export const API_FLAG_NOTES: readonly string[] = ${JSON.stringify(apiFlagNotes, null, 2)};
`;
writeFileSync(TARGET, out);
process.stdout.write(`wrote ${path.relative(process.cwd(), TARGET)}\n`);
