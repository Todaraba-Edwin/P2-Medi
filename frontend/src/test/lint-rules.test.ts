import path from "node:path";
import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

// 안전 lint 규칙이 실제로 위반을 잡는지 본다(위반 예시는 파일로 남기지 않고 글자로만 넣는다).
const ROOT = path.resolve(__dirname, "../..");
const eslint = new ESLint({ cwd: ROOT });

async function ruleIds(code: string, file: string): Promise<string[]> {
  const [result] = await eslint.lintText(code, { filePath: path.join(ROOT, file) });
  return result.messages.map((m) => m.ruleId ?? "parse-error");
}

describe("안전 lint 규칙", () => {
  it("zustand persist 가져오기를 막는다", async () => {
    const ids = await ruleIds('import { persist } from "zustand/middleware";\nexport const p = persist;\n', "src/stores/x.ts");
    expect(ids).toContain("no-restricted-imports");
  });

  it("ui-settings.ts 밖의 localStorage·sessionStorage를 막는다", async () => {
    const code = 'export function f() {\n  localStorage.setItem("a", "b");\n  return window.sessionStorage.getItem("a");\n}\n';
    const ids = await ruleIds(code, "src/features/chat/x.ts");
    expect(ids).toContain("no-restricted-globals");
    expect(ids).toContain("no-restricted-properties");
  });

  it("ui-settings.ts에서는 localStorage를 허용한다", async () => {
    const ids = await ruleIds('export const v = window.localStorage.getItem("a");\n', "src/lib/ui-settings.ts");
    expect(ids).toEqual([]);
  });

  it("console 사용을 잡는다", async () => {
    const ids = await ruleIds('export function f() {\n  console.log("x");\n}\n', "src/features/chat/x.ts");
    expect(ids).toContain("no-console");
  });

  it("컴포넌트의 hex 색 직접 사용을 막는다", async () => {
    const code = 'export function X() {\n  return <div className="bg-[#ff0000]">x</div>;\n}\n';
    expect(await ruleIds(code, "src/components/X.tsx")).toContain("no-restricted-syntax");
    expect(await ruleIds(code, "src/features/result/X.tsx")).toContain("no-restricted-syntax");
    expect(await ruleIds(code, "src/app/(shell)/X.tsx")).toContain("no-restricted-syntax");
  });

  it("jsx-a11y 규칙이 켜져 있다", async () => {
    const code = 'export function X() {\n  return <div onClick={() => {}}>x</div>;\n}\n';
    const ids = await ruleIds(code, "src/components/X.tsx");
    expect(ids.some((id) => id.startsWith("jsx-a11y/"))).toBe(true);
  });
});
