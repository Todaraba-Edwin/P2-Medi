"use client";

import { useInNoMascotZone } from "./NoMascotZone";

/** 병아리 마스코트(보조 자리 전용). 이미지는 FE-06 변환 결과 확정 후 연결한다. */
export function Mascot({ className }: { className?: string }) {
  if (useInNoMascotZone()) return null;
  return <span data-testid="mascot" aria-hidden="true" className={className} />;
}
