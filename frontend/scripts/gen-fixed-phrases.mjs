// 응답이 없는 화면용 고정 문구 생성기(f5 A 2026-11-12, 시작 화면 안내까지 넓힘: FE-01-19 A·FE-01-24 A).
// backend/app/agent/fixed_phrases.py를 읽기만 해서 아래 네 값만 꺼낸다. 다른 상수는 더하지 않는다.
// - FIXED_NOTICE·DISCLAIMER: 응답 없는 오류 화면, 응답을 받기 전의 상시 고지
// - START_EMERGENCY_119·START_EXTERNAL_AI_NOTICE: 시작 화면 안내 2종(문구 승인 2026-11-16, tickets/agent/AG-08.md §5 승인 문구 표 1·2번)
// 실행: node scripts/gen-fixed-phrases.mjs
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const SOURCE = path.resolve(here, "../../backend/app/agent/fixed_phrases.py");
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

function requireLine(text, line) {
  if (!text.includes(line)) throw new Error(`조립 규칙이 바뀌었다: ${line}`);
}

const py = readFileSync(SOURCE, "utf8");
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

const out = `// 생성 파일이다. 손으로 고치지 않는다.
// 원본: backend/app/agent/fixed_phrases.py (FIXED_NOTICE, DISCLAIMER, START_EMERGENCY_119, START_EXTERNAL_AI_NOTICE)
// 다시 만들기: node scripts/gen-fixed-phrases.mjs
// 쓰는 곳: 응답을 받지 못한 화면뿐이다(f5 A, FE-01-19 A). 응답이 있으면 응답 값을 쓴다.
// - FIXED_NOTICE·DISCLAIMER: 응답 없는 오류 화면, 응답을 받기 전의 상시 고지
// - START_EMERGENCY_119·START_EXTERNAL_AI_NOTICE: 시작 화면 안내(질문을 보내기 전)
export const FIXED_NOTICE = ${JSON.stringify(fixedNotice)};
export const DISCLAIMER = ${JSON.stringify(disclaimer)};
export const START_EMERGENCY_119 = ${JSON.stringify(startEmergency)};
export const START_EXTERNAL_AI_NOTICE = ${JSON.stringify(startExternalAi)};
`;
writeFileSync(TARGET, out);
process.stdout.write(`wrote ${path.relative(process.cwd(), TARGET)}\n`);
