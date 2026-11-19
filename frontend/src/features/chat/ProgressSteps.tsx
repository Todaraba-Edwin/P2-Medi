import { CheckIcon } from "lucide-react";
import type { ProgressStage } from "@/lib/api";
import { Mascot } from "@/components/Mascot";
import { cn } from "@/lib/utils";
import { PROGRESS_LABEL, STAGE_LABELS } from "./copy";

const ORDER: readonly ProgressStage[] = ["drug_lookup", "contraindication_check", "evidence_search"];

export interface ProgressStepsProps {
  /** 서버가 보낸 `progress` 이벤트의 값. 이벤트가 없으면 null이고 어느 줄도 진행 중으로 그리지 않는다(가짜 진행 없음, S9) */
  stage: ProgressStage | null;
  /** 이벤트에 문구(label)가 실려 오면 지금 줄에 그 값을 쓴다. 없으면 copy.ts 문구 */
  label?: string | null;
  /** 119 안내나 금기 결과가 나오면 마스코트를 숨긴다(S3) */
  hideMascot?: boolean;
}

/**
 * 첫 `progress` 이벤트 전(`stage=null`)의 대기 표시(BE-17-04 A). 단계 줄 밖에 두고 글자·마스코트를 쓰지 않는다:
 * 어느 단계인지 주장하지 않고 "기다리는 중"만 보인다(FE-01-07 가짜 진행 없음). 보조기기에는 바깥 `role="status"`가 이미 알린다.
 * 움직임 줄이기(`prefers-reduced-motion: reduce`)에서는 스피너 대신 멈춘 점 3개를 보인다.
 */
function WaitingMark() {
  return (
    <span aria-hidden="true" data-testid="progress-waiting" className="mb-1 flex h-5 flex-none items-center">
      <span
        data-testid="progress-waiting-spinner"
        className="size-4 rounded-full border-2 border-line-2 border-t-link motion-safe:animate-spin motion-reduce:hidden"
      />
      <span data-testid="progress-waiting-still" className="hidden items-center gap-1 motion-reduce:flex">
        <span className="size-1.5 rounded-full bg-mute" />
        <span className="size-1.5 rounded-full bg-mute" />
        <span className="size-1.5 rounded-full bg-mute" />
      </span>
    </span>
  );
}

export function ProgressSteps({ stage, label, hideMascot = false }: ProgressStepsProps) {
  const current = stage ? ORDER.indexOf(stage) : -1;
  const waiting = stage === null;
  return (
    <div role="status" aria-label={PROGRESS_LABEL} className="flex flex-col items-start gap-2.5">
      {(!hideMascot || waiting) && (
        <div className="flex items-end gap-2">
          {!hideMascot && <Mascot variant="search" size={72} />}
          {waiting && <WaitingMark />}
        </div>
      )}
      <ol className="m-0 flex w-full max-w-xs list-none flex-col gap-2 rounded-[18px] bg-bg-soft px-4 py-3">
        {ORDER.map((item, index) => {
          const state = index < current ? "done" : index === current ? "now" : "todo";
          return (
            <li
              key={item}
              data-state={state}
              aria-current={state === "now" ? "step" : undefined}
              className={cn("flex items-center gap-2.5 text-[15px]", state === "now" && "font-bold", state === "todo" && "text-mute")}
            >
              {state === "done" && (
                <span aria-hidden="true" className="grid size-5 flex-none place-items-center rounded-full bg-yellow text-ink">
                  <CheckIcon className="size-3" strokeWidth={3} />
                </span>
              )}
              {state === "now" && (
                <span
                  aria-hidden="true"
                  className="size-5 flex-none animate-spin rounded-full border-[2.5px] border-line-2 border-t-link"
                />
              )}
              {state === "todo" && <span aria-hidden="true" className="size-5 flex-none rounded-full border-[1.5px] border-line-2" />}
              <span>{state === "now" && label ? label : STAGE_LABELS[item]}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
