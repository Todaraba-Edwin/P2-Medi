"use client";

import { useSyncExternalStore } from "react";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("resize", onChange);
  return () => window.removeEventListener("resize", onChange);
}

/** 화면 폭(`window.innerWidth`). 서버 렌더링과 첫 하이드레이션에서는 null이다(폭을 모르는 채 배치를 정하지 않는다) */
export function useViewportWidth(): number | null {
  return useSyncExternalStore(
    subscribe,
    () => window.innerWidth,
    () => null,
  );
}
