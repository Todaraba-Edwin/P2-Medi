"use client";

import { useState } from "react";
import { EmergencyBanner, FixedNoticeBox, LegalFooter } from "@/features/emergency";
import { EvidenceDetail, EvidenceEntryButton, EvidencePanel } from "@/features/evidence";
import { ResultView } from "@/features/result";
import { emergencyResponse, missingEvidenceResponse } from "@/mocks/fixtures/responses";

// 고정 안내 줄이 두 줄(약사 확인 권고 → 고정 문구)인 경우를 본다: 응급 응답에 미확보 표본의 줄 목록을 받은 순서 그대로 넣는다
const response = { ...emergencyResponse, fixed_notice: missingEvidenceResponse.fixed_notice };

/**
 * 화면 높이에 맞춘 임시 배치(조립은 FE-IMPL-06): 119 배너(맨 위) → 결과(가운데만 스크롤) → 고정 안내·고지(아래 고정).
 * 근거 상세가 닫혀 있어도 119·고정 안내·고지는 그대로 보인다.
 */
export function EmergencyScreenPreview() {
  const [open, setOpen] = useState(false);
  return (
    <div data-testid="emergency-screen" className="mx-auto flex h-dvh w-full max-w-[430px] flex-col gap-2 px-3 pt-2 pb-3">
      <EmergencyBanner emergency={response.emergency!} />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <ResultView response={response} footer={<EvidenceEntryButton mode="sheet" expanded={open} onClick={() => setOpen(true)} />} />
      </div>
      <div className="flex flex-none flex-col gap-1.5">
        <FixedNoticeBox lines={response.fixed_notice} />
        <LegalFooter disclaimer={response.disclaimer} />
      </div>
      <EvidencePanel mode="sheet" open={open} onOpenChange={setOpen}>
        <EvidenceDetail response={response} />
      </EvidencePanel>
    </div>
  );
}
