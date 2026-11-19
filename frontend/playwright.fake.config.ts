import { defineConfig } from "@playwright/test";

// 가짜 서버 끝단 연결 e2e(R5, 2026-11-18). 기본 e2e(playwright.config.ts: MSW·페이지 안 fetch 대역)와 따로 돈다: `pnpm e2e:fake`.
// 브라우저 → Next rewrites 프록시(`/api/*`, MEDIAGENT_BACKEND_ORIGIN) → `backend/scripts/dev_fake_server.py`(127.0.0.1, LLM·원격 DB·공공 API 호출 0).
// 라우트·그래프·스트림 변환은 실제 백엔드 코드이고 자원만 가짜다. 실제 백엔드(`app.main`)는 띄우지 않는다(LLM 호출이 생긴다).
//
// - 파이썬: 백엔드 가상환경이 필요하다. 기본은 `../backend/.venv/bin/python`, 다른 곳에 있으면 `FAKE_SERVER_PYTHON`으로 준다(worktree에는 가상환경이 없다)
// - 포트: 가짜 서버 8011(`FAKE_SERVER_PORT`로 바꿈. 8000은 다른 개발 서버가 쓸 수 있어 피한다), 프런트 dev 3120
// - 같은 폴더의 `next dev`는 하나만 뜬다(Next lock). 기본 e2e와 동시에 돌리지 않는다
// - CI 기본 실행에는 넣지 않는다(백엔드 가상환경이 있어야 한다)
const FAKE_PORT = Number(process.env.FAKE_SERVER_PORT ?? 8011);
const APP_PORT = 3120;
const PYTHON = process.env.FAKE_SERVER_PYTHON ?? "../backend/.venv/bin/python";
/** 느린응답 시나리오의 첫 이벤트 전 침묵(초). 서버 하트비트 간격(15초)보다 길어야 빈 줄이 온다 */
const SLOW_SECONDS = 17;

export default defineConfig({
  testDir: "./e2e-fake",
  workers: 1, // 가짜 서버 하나에 순서대로 붙는다
  timeout: 60_000,
  use: { baseURL: `http://localhost:${APP_PORT}`, viewport: { width: 360, height: 800 } },
  webServer: [
    {
      command: `${PYTHON} ../backend/scripts/dev_fake_server.py --port ${FAKE_PORT} --slow-seconds ${SLOW_SECONDS}`,
      url: `http://127.0.0.1:${FAKE_PORT}/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `pnpm exec next dev -p ${APP_PORT}`,
      url: `http://localhost:${APP_PORT}`,
      // MSW는 끈다(빈 값). 프록시 대상만 준다. Supabase 로그인 설정도 비운다(가짜 서버에는 계정 API가 없고 실제 Supabase를 부르지 않는다)
      env: { MEDIAGENT_BACKEND_ORIGIN: `http://127.0.0.1:${FAKE_PORT}`, NEXT_PUBLIC_API_MOCKING: "", NEXT_PUBLIC_SUPABASE_URL: "", NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "" },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
