// MSW 스위치. `NEXT_PUBLIC_API_MOCKING=enabled`일 때만 브라우저 워커를 켠다(배포에서는 끈다).
export function isApiMockingEnabled(): boolean {
  return process.env.NEXT_PUBLIC_API_MOCKING === "enabled";
}

/** 워커가 이 페이지를 넘겨받기를 기다리는 상한(개발 전용 값) */
const CONTROLLER_WAIT_MS = 3_000;

/**
 * 워커를 처음 설치한 페이지는 `start()`가 끝난 직후에도 아직 워커가 요청을 잡지 못한다
 * (2026-11-12 Chromium에서 확인: 첫 요청이 워커를 지나쳐 404). 페이지를 넘겨받을 때까지 기다린다.
 */
async function waitForController(): Promise<void> {
  const container = typeof navigator === "undefined" ? undefined : navigator.serviceWorker;
  if (!container || container.controller) return;
  await new Promise<void>((resolve) => {
    const finish = () => {
      clearTimeout(timer);
      container.removeEventListener("controllerchange", finish);
      resolve();
    };
    const timer = setTimeout(finish, CONTROLLER_WAIT_MS);
    container.addEventListener("controllerchange", finish);
  });
}

let starting: Promise<boolean> | null = null;

async function startWorker(): Promise<boolean> {
  // 이 분기는 import와 같은 함수 안에 있어야 한다: 서버 번들에서 import가 빠져야 빌드가 된다
  // (`msw/browser`는 Node 조건에서 풀리지 않는다. 분기를 밖으로 옮기면 "Can't resolve 'msw/browser'", 2026-11-12 확인).
  if (typeof window === "undefined") return false;
  const { worker } = await import("./browser");
  await worker.start({ onUnhandledFrame: "bypass", quiet: true });
  await waitForController();
  return true;
}

/**
 * 워커를 켰으면 true. 서버 렌더링·스위치 꺼짐이면 아무것도 불러오지 않는다.
 * 여러 번 불려도 워커는 한 번만 켠다(MSW는 두 번째 `start()`에서 오류를 던지고, React 개발 모드는 effect를 두 번 돌린다).
 */
export function enableApiMocking(): Promise<boolean> {
  if (!isApiMockingEnabled() || typeof window === "undefined") return Promise.resolve(false);
  starting ??= startWorker();
  return starting;
}
