import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";
import jsxA11y from "eslint-plugin-jsx-a11y";

const HEX_COLOR = "#[0-9a-fA-F]{3,8}\\b";
const hexMessage = "색은 src/styles/globals.css의 토큰(Tailwind 유틸리티)으로만 쓴다. hex 직접 사용 금지.";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // jsx-a11y 플러그인은 next 설정이 이미 등록했으므로 규칙만 더한다.
  { rules: { ...jsxA11y.flatConfigs.recommended.rules } },
  {
    rules: {
      "no-console": "warn",
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "zustand/middleware",
              importNames: ["persist"],
              message: "Zustand persist 금지(FE-01-08 A). 대화는 메모리에만 둔다.",
            },
          ],
        },
      ],
      // localStorage·sessionStorage는 src/lib/ui-settings.ts에서만 허용(아래 override)
      "no-restricted-globals": [
        "error",
        { name: "localStorage", message: "src/lib/ui-settings.ts에서만 쓴다." },
        { name: "sessionStorage", message: "sessionStorage는 쓰지 않는다." },
      ],
      "no-restricted-properties": [
        "error",
        ...["window", "globalThis", "self"].flatMap((object) =>
          ["localStorage", "sessionStorage"].map((property) => ({
            object,
            property,
            message: "브라우저 저장소는 src/lib/ui-settings.ts에서만 쓴다.",
          })),
        ),
      ],
    },
  },
  {
    files: ["src/lib/ui-settings.ts"],
    rules: { "no-restricted-globals": "off", "no-restricted-properties": "off" },
  },
  {
    // 컴포넌트에서 hex 색 직접 사용 금지(src/styles/는 대상 아님)
    files: ["src/features/**/*.{ts,tsx}", "src/components/**/*.{ts,tsx}", "src/app/(shell)/**/*.{ts,tsx}"],
    ignores: ["**/*.test.{ts,tsx}"],
    rules: {
      "no-restricted-syntax": [
        "error",
        { selector: `Literal[value=/${HEX_COLOR}/]`, message: hexMessage },
        { selector: `TemplateElement[value.raw=/${HEX_COLOR}/]`, message: hexMessage },
      ],
    },
  },
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts", "playwright-report/**", "test-results/**", "public/mockServiceWorker.js"]),
]);

export default eslintConfig;
