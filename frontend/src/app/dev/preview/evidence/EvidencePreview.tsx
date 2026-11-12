"use client";

import Link from "next/link";
import { useState } from "react";
import { EmergencyBanner, FixedNoticeBox, LegalFooter, PharmacistAdviceBox } from "@/features/emergency";
import { EvidenceDetail, EvidenceEntryButton, EvidencePanel } from "@/features/evidence";
import type { EvidenceMode } from "@/features/evidence";
import { ResultView } from "@/features/result";
import { EVIDENCE_SAMPLES, EVIDENCE_WITHOUT_SAMPLE } from "./samples";

/** 개발 전용: v1 합성 fixture의 시나리오별 근거 상세와 안전 영역 부품을 나열한다. 폭은 창 폭을 따른다(최대 720px). */
export function EvidencePreview() {
  const [open, setOpen] = useState<{ id: string; mode: EvidenceMode } | null>(null);
  const opened = open ? EVIDENCE_SAMPLES.find((sample) => sample.id === open.id) : undefined;
  return (
    <main className="mx-auto flex w-full max-w-[720px] flex-col gap-8 px-3 py-4">
      <h1 className="m-0 text-lg font-bold">근거 상세 · 안전 영역 부품</h1>
      <p className="m-0 text-xs text-mute">
        <Link href="/dev/preview/evidence/screen" className="underline">
          응급 화면 배치 보기(119·고정 안내가 첫 화면에 들어오는지)
        </Link>
      </p>

      {EVIDENCE_SAMPLES.map((sample) => (
        <section key={sample.id} data-testid="evidence-sample" data-sample={sample.id} className="flex flex-col gap-2.5">
          <h2 className="m-0 text-xs font-bold text-mute">
            {sample.title}
            {sample.board ? ` · ${sample.board}` : ""}
          </h2>
          {sample.response.emergency && <EmergencyBanner emergency={sample.response.emergency} />}
          <ResultView
            response={sample.response}
            footer={
              <div className="flex flex-col divide-y divide-line">
                <EvidenceEntryButton mode="sheet" onClick={() => setOpen({ id: sample.id, mode: "sheet" })} />
                <EvidenceEntryButton mode="panel" onClick={() => setOpen({ id: sample.id, mode: "panel" })} />
              </div>
            }
          />
          <div className="rounded-2xl bg-bg-softer p-3">
            <EvidenceDetail response={sample.response} />
          </div>
          <PharmacistAdviceBox lines={sample.response.pharmacist_advice} />
          <FixedNoticeBox lines={sample.response.fixed_notice} />
          <LegalFooter disclaimer={sample.response.disclaimer} />
        </section>
      ))}

      <section className="rounded-xl border border-line p-3 text-xs text-mute">
        <h2 className="m-0 mb-1 font-bold">표본이 없는 것</h2>
        <ul className="m-0 list-disc pl-4">
          {EVIDENCE_WITHOUT_SAMPLE.map((item) => (
            <li key={item.name}>
              {item.name}: {item.reason}
            </li>
          ))}
        </ul>
      </section>

      {/* 시트(좁은 폭 배치) */}
      <EvidencePanel mode="sheet" open={open?.mode === "sheet"} onOpenChange={(next) => !next && setOpen(null)}>
        {opened && <EvidenceDetail response={opened.response} />}
      </EvidencePanel>
      {/* 패널(넓은 폭 배치): 미리보기에서는 화면 오른쪽에 붙여 보인다 */}
      {open?.mode === "panel" && (
        <div data-testid="panel-host" className="fixed inset-y-0 right-0 z-40 w-[min(400px,100vw)] shadow-lg">
          <EvidencePanel mode="panel" open onOpenChange={() => setOpen(null)}>
            {opened && <EvidenceDetail response={opened.response} />}
          </EvidencePanel>
        </div>
      )}
    </main>
  );
}
