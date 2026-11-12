import type { Candidate, ChatResponse } from "@/lib/api";
import { NoMascotZone } from "@/components/NoMascotZone";
import { CandidateCard } from "./CandidateCard";
import { ResultCard } from "./ResultCard";

export interface ResultViewProps {
  response: ChatResponse;
  basis?: string | null;
  footer?: React.ReactNode;
  onPickCandidate?: (candidate: Candidate) => void;
  onOtherCandidate?: () => void;
}

/**
 * 결과 부품 묶음: 상단 배너(`notice`) → 쉬운 요약(`summary`) → 결과 카드 → (되묻기면) 후보 카드.
 * 배너와 요약은 받은 글자를 가공 없이 그린다(요약에 용량 숫자를 만들거나 표로 쪼개지 않는다, S8).
 * 고정 안내·고지·119·근거 상세는 FE-IMPL-05, 화면 조립은 FE-IMPL-06이 한다.
 */
export function ResultView({ response, basis, footer, onPickCandidate, onOtherCandidate }: ResultViewProps) {
  const showCandidates = response.end_reason === "CLARIFY" && response.candidates.length > 0 && onPickCandidate;
  return (
    <NoMascotZone>
      <div data-testid="result-view" data-end-reason={response.end_reason ?? undefined} className="flex flex-col gap-2.5">
        {response.notice !== null && (
          <p data-testid="result-notice" className="m-0 rounded-xl bg-warn-bg px-3 py-2 text-[13px] leading-[19px] font-semibold break-words text-warn-ink">
            {response.notice}
          </p>
        )}
        {response.summary !== null && (
          <p data-testid="result-summary" className="m-0 text-base leading-[25px] break-words whitespace-pre-wrap">
            {response.summary}
          </p>
        )}
        <ResultCard response={response} basis={basis} footer={footer} />
        {showCandidates ? <CandidateCard candidates={response.candidates} onPick={onPickCandidate} onOther={onOtherCandidate} /> : null}
      </div>
    </NoMascotZone>
  );
}
