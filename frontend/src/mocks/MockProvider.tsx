"use client";

import { useEffect, useState } from "react";
import { enableApiMocking, isApiMockingEnabled } from "./index";

/**
 * 스위치가 켜져 있으면 워커가 준비된 뒤에 자식을 그린다(첫 요청이 워커보다 먼저 나가지 않게).
 * 꺼져 있으면 그대로 그린다. 연결(layout 또는 page에서 감싸기)은 FE-IMPL-06 몫이다.
 */
export function MockProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(() => !isApiMockingEnabled());

  useEffect(() => {
    if (ready) return;
    let cancelled = false;
    enableApiMocking().finally(() => {
      if (!cancelled) setReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, [ready]);

  return ready ? <>{children}</> : null;
}
