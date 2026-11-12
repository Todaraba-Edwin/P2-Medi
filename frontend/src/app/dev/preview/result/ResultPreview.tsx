"use client";

import { useState } from "react";
import { ResultView } from "@/features/result";
import { BOARDS_WITHOUT_SAMPLE, RESULT_SAMPLES } from "./samples";

/** 개발 전용: v1 합성 fixture의 시나리오별 결과 카드를 나열한다. 폭은 창 폭을 따른다(최대 720px). */
export function ResultPreview() {
  const [picked, setPicked] = useState<string | null>(null);
  return (
    <main className="mx-auto flex w-full max-w-[720px] flex-col gap-6 px-3 py-4">
      <h1 className="m-0 text-lg font-bold">결과 카드 부품</h1>
      {RESULT_SAMPLES.map((sample) => (
        <section key={sample.id} data-testid="result-sample" data-sample={sample.id} className="flex flex-col gap-2">
          <h2 className="m-0 text-xs font-bold text-mute">
            {sample.title}
            {sample.board ? ` · ${sample.board}` : ""}
          </h2>
          <ResultView
            response={sample.response}
            basis={sample.basis}
            onPickCandidate={(candidate) => setPicked(candidate.name)}
            onOtherCandidate={() => setPicked("직접 입력")}
          />
          {sample.id === "clarify" && (
            <p data-testid="picked" className="m-0 text-xs text-mute">
              고른 후보: {picked ?? "없음"}
            </p>
          )}
        </section>
      ))}
      <section className="rounded-xl border border-line p-3 text-xs text-mute">
        <h2 className="m-0 mb-1 font-bold">표본이 없는 보드</h2>
        <ul className="m-0 list-disc pl-4">
          {BOARDS_WITHOUT_SAMPLE.map((item) => (
            <li key={item.board}>
              {item.board}: {item.reason}
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
