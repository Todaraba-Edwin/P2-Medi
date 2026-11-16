import { defineConfig } from "@playwright/test";

// 서버 두 개(FE-IMPL-06b): 화면 시험은 dev 서버(3100, MSW 꺼짐 + 페이지 안 fetch 대역),
// MSW 워커 시험은 `NEXT_PUBLIC_API_MOCKING=enabled`로 만든 운영 빌드(3110)에 붙는다.
// - 이 값은 빌드 때 번들에 박히므로 같은 서버에서 켜고 끌 수 없다
// - Next 16은 같은 폴더의 `next dev` 두 개를 lockfile(.next/dev/lock)로 막지만, dev(.next/dev)와 build(.next)는 동시에 돌 수 있다
// - Playwright는 webServer를 적힌 순서대로 하나씩 띄운다. build가 바꾼 next-env.d.ts를 dev가 다시 쓰도록 MSW 서버를 먼저 둔다
const APP_PORT = 3100;
const MSW_PORT = 3110;

export default defineConfig({
  testDir: "./e2e",
  projects: [
    { name: "app", testIgnore: /msw\.spec\.ts/, use: { baseURL: `http://localhost:${APP_PORT}` } },
    { name: "msw-worker", testMatch: /msw\.spec\.ts/, use: { baseURL: `http://localhost:${MSW_PORT}` } },
  ],
  webServer: [
    {
      command: `pnpm exec next build && pnpm exec next start -p ${MSW_PORT}`,
      url: `http://localhost:${MSW_PORT}`,
      env: { NEXT_PUBLIC_API_MOCKING: "enabled" },
      reuseExistingServer: !process.env.CI,
      timeout: 240_000,
    },
    {
      command: `pnpm exec next dev -p ${APP_PORT}`,
      url: `http://localhost:${APP_PORT}`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
    },
  ],
});
