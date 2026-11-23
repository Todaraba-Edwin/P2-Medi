import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());

// jsdom에는 ResizeObserver가 없다. Radix 팝오버(계정 메뉴)의 위치 계산이 쓰므로 빈 구현을 둔다(크기 변화는 시험하지 않는다)
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
