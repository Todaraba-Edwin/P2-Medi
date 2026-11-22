// 브라우저용 MSW 워커. enableApiMocking()만 이 파일을 불러온다(운영 번들에 섞이지 않게 동적 import).
import { setupWorker } from "msw/browser";
import { createAccountHandlers } from "./account-handlers";
import { createChatHandler } from "./handlers";
import { createPhotoHandlers } from "./photo-handlers";

/** 진행 표시가 눈에 보이도록 이벤트 사이를 띄운다(개발 전용 값) */
const BROWSER_EVENT_DELAY_MS = 500;
/** 사진 "인식 중" 화면이 눈에 보이도록 변환 응답을 띄운다(개발 전용 값) */
const BROWSER_PHOTO_DELAY_MS = 800;

export const worker = setupWorker(
  createChatHandler({ delayMs: BROWSER_EVENT_DELAY_MS }),
  ...createAccountHandlers(),
  ...createPhotoHandlers({ delayMs: BROWSER_PHOTO_DELAY_MS }),
);
