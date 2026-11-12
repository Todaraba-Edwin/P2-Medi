import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

// 금지어 원본은 백엔드 fixed_phrases.py. 읽기만 한다.
const PHRASES = path.resolve(__dirname, "../../../backend/app/agent/fixed_phrases.py");
const SRC = path.resolve(__dirname, "..");

function loadForbiddenTerms(): string[] {
  const text = readFileSync(PHRASES, "utf8");
  const block = /FORBIDDEN_SCREEN_TERMS\s*=\s*\(([\s\S]*?)\n\)/.exec(text);
  if (!block) return [];
  return [...block[1].matchAll(/"((?:[^"\\]|\\.)*)"/g)].map((m) => m[1]);
}

function listTsx(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) return name === "mocks" ? [] : listTsx(full);
    return full.endsWith(".tsx") && !/\.(test|spec)\./.test(name) && !name.includes(".generated.") ? [full] : [];
  });
}

/** JSX 글자와 문자열 리터럴(템플릿 포함)만 모은다. 주석·식별자는 제외. */
function screenTexts(file: string): string[] {
  const source = ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const out: string[] = [];
  const visit = (node: ts.Node) => {
    if (ts.isJsxText(node) || ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) out.push(node.text);
    else if (ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node)) out.push(node.text);
    ts.forEachChild(node, visit);
  };
  visit(source);
  return out;
}

describe("화면 금지어", () => {
  const terms = loadForbiddenTerms();

  it("fixed_phrases.py에서 금지어를 읽었다(파싱 깨짐 감지)", () => {
    expect(terms.length).toBeGreaterThan(0);
  });

  it("src/ .tsx의 JSX 글자·문자열에 금지어가 없다", () => {
    const hits: string[] = [];
    for (const file of listTsx(SRC)) {
      for (const text of screenTexts(file)) {
        for (const term of terms) if (text.includes(term)) hits.push(`${path.relative(SRC, file)}: "${term}"`);
      }
    }
    expect(hits).toEqual([]);
  });
});
