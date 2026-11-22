"use client";

import { useId, useRef } from "react";
import { CheckIcon, MonitorIcon, MoonIcon, SunIcon, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { THEME_MODES, type ThemeMode } from "@/lib/theme";
import { SCREEN_MODE_LABEL, SYSTEM_MODE_HINT, THEME_LABELS } from "./copy";

const ICONS: Readonly<Record<ThemeMode, LucideIcon>> = {
  light: SunIcon,
  dark: MoonIcon,
  system: MonitorIcon,
};

/**
 * 화면 모드 3칸 radiogroup(FE-12-03 B). 화살표 키(←/→/↑/↓)는 칸을 옮기면서 고르고, Tab은 고른 칸 하나에만 간다(roving tabindex).
 * 고른 칸은 바탕 노랑 + 굵게 + 체크로 보인다(색만으로 구분하지 않는다). 칸은 44px 이상이다.
 */
export function ThemeChoice({ value, onChange }: { value: ThemeMode; onChange: (mode: ThemeMode) => void }) {
  const id = useId();
  const refs = useRef<Record<ThemeMode, HTMLButtonElement | null>>({ light: null, dark: null, system: null });

  const choose = (mode: ThemeMode) => {
    onChange(mode);
    refs.current[mode]?.focus();
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, mode: ThemeMode) => {
    if (event.nativeEvent.isComposing) return;
    const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
    if (step === 0) return;
    event.preventDefault();
    const index = THEME_MODES.indexOf(mode);
    choose(THEME_MODES[(index + step + THEME_MODES.length) % THEME_MODES.length]);
  };

  return (
    <div role="radiogroup" aria-label={SCREEN_MODE_LABEL} data-testid="theme-choice" className="grid grid-cols-3 gap-2">
      {THEME_MODES.map((mode) => {
        const checked = value === mode;
        const Icon = ICONS[mode];
        const hintId = `${id}-${mode}-hint`;
        return (
          <div key={mode} className="flex min-w-0 flex-col gap-1.5">
            <button
              ref={(node) => {
                refs.current[mode] = node;
              }}
              type="button"
              role="radio"
              aria-checked={checked}
              aria-describedby={mode === "system" ? hintId : undefined}
              tabIndex={checked ? 0 : -1}
              data-testid={`theme-${mode}`}
              data-checked={checked ? "true" : "false"}
              onClick={() => onChange(mode)}
              onKeyDown={(event) => onKeyDown(event, mode)}
              className={cn(
                "relative flex min-h-[72px] flex-col items-center justify-center gap-1.5 rounded-2xl border px-2 text-sm transition-colors enabled:hover:border-faint",
                checked ? "border-yellow bg-yellow font-bold text-on-yellow" : "border-line-2 bg-bg text-ink-2 enabled:hover:bg-bg-soft",
              )}
            >
              {checked && <CheckIcon className="absolute top-1.5 left-1.5 size-3.5" aria-hidden="true" />}
              <Icon className="size-5" aria-hidden="true" />
              <span>{THEME_LABELS[mode]}</span>
            </button>
            {mode === "system" && (
              <p id={hintId} className="m-0 text-center text-xs text-mute">
                {SYSTEM_MODE_HINT}
              </p>
            )}
          </div>
        );
      })}
    </div>
  );
}
