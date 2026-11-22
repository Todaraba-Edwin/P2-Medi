// Vitest(Node)용 MSW 서버
import { setupServer } from "msw/node";
import { createAccountHandlers } from "./account-handlers";
import { handlers } from "./handlers";
import { createPhotoHandlers } from "./photo-handlers";

export const server = setupServer(...handlers, ...createAccountHandlers(), ...createPhotoHandlers());
