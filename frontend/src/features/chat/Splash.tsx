"use client";

import { useEffect } from "react";
import { BrandWordmark } from "@/components/BrandWordmark";
import { Mascot } from "@/components/Mascot";
import { SPLASH_LABEL } from "./copy";

/** 여는 화면(정적 브랜딩 자리). 마스코트와 워드마크를 쓴다. 잠깐 보였다가 닫히고, 누르면 바로 닫힌다. */
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
        <Mascot variant="question" size={150} eager className="motion-safe:animate-bounce" />
        <BrandWordmark size={50} />
      </span>
      <span aria-hidden="true" className="size-7 animate-spin rounded-full border-[3px] border-line border-t-yellow" />
    </button>
  );
}
