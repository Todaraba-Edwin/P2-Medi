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

export function ProgressSteps({ stage, label, hideMascot = false }: ProgressStepsProps) {
  const current = stage ? ORDER.indexOf(stage) : -1;
  return (
    <div role="status" aria-label={PROGRESS_LABEL} className="flex flex-col items-start gap-2.5">
      {!hideMascot && <Mascot variant="search" size={72} />}
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
