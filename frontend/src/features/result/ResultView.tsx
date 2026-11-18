import type { Candidate, ChatResponse } from "@/lib/api";
import { NoMascotZone } from "@/components/NoMascotZone";
import { CandidateCard } from "./CandidateCard";
import { ResultCard } from "./ResultCard";
import { RetryActions } from "./RetryActions";

export interface ResultViewProps {
  response: ChatResponse;
  basis?: string | null;
  footer?: React.ReactNode;
  onPickCandidate?: (candidate: Candidate) => void;
  onOtherCandidate?: () => void;
  /** 되묻기에서 지금 고른 후보(선택 상태 표시용). `CandidateCard`의 `selected`로 넘긴다 */
  selectedCandidate?: Candidate | null;
  /** 주면 약을 찾지 못한 줄(`input_name`이 있는 줄)이 있는 결과 카드 아래에 `이름 다시 입력` 칩을 둔다(PRD-14-03) */
  onRetryName?: () => void;
}

/**
 * 결과 부품 묶음: 상단 배너(`notice`) → 보정 고지(`name_corrections`) → 쉬운 요약(`summary`) → 결과 카드 → (약을 찾지 못했으면) 동작 칩 → 확인하지 못한 종류의 줄
 * → (되묻기면) 후보 카드와 안내. 순서는 서버 `finalize.render_text`와 같다(보정 고지는 요약보다 먼저: 무엇을 확인했는지부터).
 * 배너·고지·요약은 받은 글자를 가공 없이 그린다(요약에 용량 숫자를 만들거나 표로 쪼개지 않고, 고지 문장을 다시 조립하지 않는다, S8).
 * 고정 안내·고지·119·근거 상세는 FE-IMPL-05, 화면 조립은 FE-IMPL-06이 한다.
 */
export function ResultView({ response, basis, footer, onPickCandidate, onOtherCandidate, selectedCandidate, onRetryName }: ResultViewProps) {
  const showCandidates = response.end_reason === "CLARIFY" && response.candidates.length > 0 && onPickCandidate;
  // 약을 찾지 못한 줄: 서버가 사용자가 적은 이름(`input_name`)을 실어 보낸 줄(backend schemas.py의 미식별 판별과 같은 칸)
  const showRetry = onRetryName !== undefined && response.findings.some((finding) => finding.input_name !== null);
  return (
    <NoMascotZone>
      <div data-testid="result-view" data-end-reason={response.end_reason ?? undefined} className="flex flex-col gap-2.5">
        {response.notice !== null && (
          <p data-testid="result-notice" className="m-0 rounded-xl bg-warn-bg px-3 py-2 text-[13px] leading-[19px] font-semibold break-words text-warn-ink">
            {response.notice}
          </p>
        )}
        {/* 오탈자 보정 고지(서버가 완성한 문장, FE-02). 요약보다 먼저·접히지 않는 자리에 받은 순서 그대로. "삐!" 표지·마스코트 없음 */}
        {response.name_corrections.length > 0 && (
          <ul data-testid="name-corrections" className="m-0 flex list-none flex-col gap-1 p-0">
            {response.name_corrections.map((correction, index) => (
              <li key={index} className="rounded-xl border border-line bg-bg-softer px-3 py-2 text-[13px] leading-[19px] break-words text-ink-2">
                {correction.text}
              </li>
            ))}
          </ul>
        )}
        {response.summary !== null && (
          <p data-testid="result-summary" className="m-0 text-base leading-[25px] break-words whitespace-pre-wrap">
            {response.summary}
          </p>
        )}
        <ResultCard response={response} basis={basis} footer={footer} />
        {/* 결과 카드 바로 아래 한 줄. 고정 안내·119를 밀어내지 않는다(그것들은 이 묶음 밖의 접히지 않는 영역이다) */}
        {showRetry ? <RetryActions onRetryName={onRetryName} /> : null}
        {/* 정보가 없어 확인하지 못한 종류의 줄(서버 상수, FE-07-16 B). 받은 순서·글자 그대로, 접히지 않는다 */}
        {response.not_checked_lines.length > 0 && (
          <ul data-testid="not-checked-lines" className="m-0 flex list-none flex-col gap-1 p-0">
            {response.not_checked_lines.map((line, index) => (
              <li key={index} className="rounded-xl border border-dashed border-faint bg-bg px-3 py-2 text-[13px] leading-[19px] font-semibold break-words text-ink-2">
                {line}
              </li>
            ))}
          </ul>
        )}
        {showCandidates ? <CandidateCard candidates={response.candidates} onPick={onPickCandidate} onOther={onOtherCandidate} selected={selectedCandidate} /> : null}
        {/* 되묻기 카드 안내(서버 상수). 후보가 있을 때만 온다 */}
        {response.candidates_line !== null && (
          <p data-testid="candidates-line" className="m-0 px-1 text-xs leading-[17px] break-words text-mute">
            {response.candidates_line}
          </p>
        )}
      </div>
    </NoMascotZone>
  );
}
