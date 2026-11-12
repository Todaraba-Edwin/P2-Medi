// 응답 없는 오류 화면용 고정 문구 생성기(f5 A, 2026-11-12).
// backend/app/agent/fixed_phrases.py를 읽기만 해서 FIXED_NOTICE·DISCLAIMER 두 값만 꺼낸다. 다른 상수는 더하지 않는다.
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

const out = `// 생성 파일이다. 손으로 고치지 않는다.
// 원본: backend/app/agent/fixed_phrases.py (FIXED_NOTICE, DISCLAIMER)
// 다시 만들기: node scripts/gen-fixed-phrases.mjs
// 쓰는 곳: 응답(fixed_notice)을 받지 못한 오류 화면 하나뿐이다(f5 A). 응답이 있으면 응답 값을 쓴다.
export const FIXED_NOTICE = ${JSON.stringify(fixedNotice)};
export const DISCLAIMER = ${JSON.stringify(disclaimer)};
`;
writeFileSync(TARGET, out);
process.stdout.write(`wrote ${path.relative(process.cwd(), TARGET)}\n`);
