// 브라우저용 MSW 워커. enableApiMocking()만 이 파일을 불러온다(운영 번들에 섞이지 않게 동적 import).
import { setupWorker } from "msw/browser";
import { createAccountHandlers, initialMockAccountState } from "./account-handlers";
import { createChatHandler } from "./handlers";
import { createPhotoHandlers } from "./photo-handlers";

/** 진행 표시가 눈에 보이도록 이벤트 사이를 띄운다(개발 전용 값) */
const BROWSER_EVENT_DELAY_MS = 500;
/** 사진 "인식 중" 화면이 눈에 보이도록 변환 응답을 띄운다(개발 전용 값) */
const BROWSER_PHOTO_DELAY_MS = 800;

export const worker = setupWorker(
  createChatHandler({ delayMs: BROWSER_EVENT_DELAY_MS }),
  // 목 세션은 페이지 메모리에만 있어 페이지를 새로 열면 사라진다. 로그인 콜백 복귀(실제는 페이지 이동 뒤 세션 쿠키가 있는 상태)를
  // 흉내 내는 e2e가 `?mock_session=new|onboarded`로 시작 세션을 미리 만든다(개발·시험 전용)
  ...createAccountHandlers(initialMockAccountState(window.location.search)),
  ...createPhotoHandlers({ delayMs: BROWSER_PHOTO_DELAY_MS }),
);
