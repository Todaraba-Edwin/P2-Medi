"use client";

import { useEffect } from "react";
import { Mascot } from "@/components/Mascot";
import { APP_NAME, SPLASH_LABEL } from "./copy";

/** 여는 화면. 마스코트 허용 자리다. 잠깐 보였다가 닫히고, 누르면 바로 닫힌다. */
export function Splash({ onDone, durationMs = 1300 }: { onDone: () => void; durationMs?: number }) {
  useEffect(() => {
    const timer = setTimeout(onDone, durationMs);
    return () => clearTimeout(timer);
  }, [onDone, durationMs]);

  return (
    <button
      type="button"
      aria-label={SPLASH_LABEL}
      onClick={onDone}
      className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-7 border-0 bg-bg-soft text-ink"
    >
      <span className="flex flex-col items-center gap-1.5">
        <Mascot className="block h-36 w-36 motion-safe:animate-bounce" />
        <span className="text-3xl font-extrabold">{APP_NAME}</span>
      </span>
      <span aria-hidden="true" className="size-7 animate-spin rounded-full border-[3px] border-line border-t-yellow" />
    </button>
  );
}
