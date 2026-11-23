import type { Candidate, ChatResponse } from "@/lib/api";
import { NoMascotZone } from "@/components/NoMascotZone";
import { CandidateCard } from "./CandidateCard";
import type { CandidatePicks } from "./candidate-groups";
import { isApiFailNotice } from "./realtime-notice";
import { ResultCard } from "./ResultCard";
import { RetryActions } from "./RetryActions";

export interface ResultViewProps {
  response: ChatResponse;
  basis?: string | null;
  footer?: React.ReactNode;
  onPickCandidate?: (candidate: Candidate) => void;
  onOtherCandidate?: () => void;
  /** 되묻기에서 묶음(`input_name`)별로 지금 고른 후보(선택 상태 표시용). `CandidateCard`의 `selected`로 넘긴다 */
  selectedCandidates?: CandidatePicks;
  /** 주면 약을 찾지 못한 줄(`input_name`이 있는 줄)이 있는 결과 카드 아래에 `이름 다시 입력` 칩을 둔다(PRD-14-03) */
  onRetryName?: () => void;
  /** 되묻기 안내(`candidates_line`)를 조립하는 쪽이 다른 자리(여러 약 확인 줄의 첫 행, FE-10)에 그릴 때 `true`: 여기서는 그리지 않는다(두 번 보이지 않게) */
  hideCandidatesLine?: boolean;
  /**
   * 고른 제품으로 이미 다시 물은 지난 되묻기 차례의 선택(FE-17 U-05). 주면 후보 카드를 고른 줄 요약(고를 수 없음)으로 남기고 되묻기 안내 줄은 숨긴다.
   * 마지막 차례(지금 고르는 중)에는 주지 않는다
   */
  pastPicks?: CandidatePicks;
}

/** 결과 위 안내 띠(서버 상수 글자 그대로): 공공 API 실패 배너·용량 고지·재복용 고지가 같은 모양이다 */
function NoticeBand({ testId, text }: { testId: string; text: string }) {
  return (
    <p data-testid={testId} className="m-0 rounded-xl bg-warn-bg px-3 py-2 text-[13px] leading-[19px] font-semibold break-words text-warn-ink">
      {text}
    </p>
  );
}

/**
 * 결과 부품 묶음: 용량 고지(`dose_notice`, 119 다음 맨 위) → 상단 배너(`notice`, 단 공공 API 실패 배너는 본문 0회·근거 상세에만: FE-11-10 A)
 * → 보정 고지(`name_corrections`) → 쉬운 요약(`summary`) → 재복용 고지(`redose_notice`)
 * → 묶음 요약 한 줄(`result_summary.text`·`pair_only_notice`) → 결과 카드 → (약을 찾지 못했으면) 동작 칩 → 확인하지 못한 종류의 줄 → (되묻기면) 후보 카드와 안내.
 * 순서는 서버 `finalize.render_text`와 같다(보정 고지는 요약보다 먼저: 무엇을 확인했는지부터).
 * 배너·고지·요약은 받은 글자를 가공 없이 그린다(요약에 용량 숫자를 만들거나 표로 쪼개지 않고, 고지 문장을 다시 조립하지 않는다, S8).
 * 고정 안내·고지·119·근거 상세는 FE-IMPL-05, 화면 조립은 FE-IMPL-06이 한다.
 * GROUP-01 3단계의 새 칸 가운데 고지·요약 줄만 임시로 그린다(디자인 전). 구역별 접기(`section`·`rest_fold`)·짝 참조(`pair_ref`)·용량 되묻기 카드(`dose_check`)는 4단계 디자인 뒤 5단계 본 작업이다
 */
export function ResultView({ response, basis, footer, onPickCandidate, onOtherCandidate, selectedCandidates, onRetryName, hideCandidatesLine = false, pastPicks }: ResultViewProps) {
  const showCandidates = response.end_reason === "CLARIFY" && response.candidates.length > 0 && onPickCandidate;
  const showPastPicks = !showCandidates && pastPicks !== undefined && response.end_reason === "CLARIFY" && response.candidates.length > 0;
  // 약을 찾지 못한 줄: 서버가 사용자가 적은 이름(`input_name`)을 실어 보낸 줄(backend schemas.py의 미식별 판별과 같은 칸)
  const showRetry = onRetryName !== undefined && response.findings.some((finding) => finding.input_name !== null);
  return (
    <NoMascotZone>
      <div data-testid="result-view" data-end-reason={response.end_reason ?? undefined} className="flex flex-col gap-2.5">
        {response.dose_notice !== null && <NoticeBand testId="dose-notice" text={response.dose_notice} />}
        {/* 공공 API 실패 배너(`NOTICE_API_FAIL`)는 본문에 그리지 않는다(근거 상세 `EvidenceDetail`이 보인다). 상한 도달 등 다른 배너는 그대로 */}
        {response.notice !== null && !isApiFailNotice(response.notice) && <NoticeBand testId="result-notice" text={response.notice} />}
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
        {response.redose_notice !== null && <NoticeBand testId="redose-notice" text={response.redose_notice} />}
        {/* 약 2개 이상 결과의 묶음 요약 한 줄(코드 칸, 서버 상수 틀 그대로). 결과 카드 바로 위 */}
        {response.result_summary !== null && (
          <div data-testid="result-summary-line" className="m-0 flex flex-col gap-1 px-1 text-[13px] leading-[19px] break-words text-ink-2">
            <p className="m-0 font-semibold text-ink">{response.result_summary.text}</p>
            {response.result_summary.pair_only_notice !== null && (
              <p data-testid="pair-only-notice" className="m-0">
                {response.result_summary.pair_only_notice}
              </p>
            )}
          </div>
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
        {showCandidates ? <CandidateCard candidates={response.candidates} onPick={onPickCandidate} onOther={onOtherCandidate} selected={selectedCandidates} /> : null}
        {/* 이미 고른 제품으로 다시 물은 지난 차례: 고른 줄 요약만 남긴다(FE-17 U-05) */}
        {showPastPicks ? <CandidateCard candidates={response.candidates} onPick={() => {}} selected={pastPicks} readOnly /> : null}
        {/* 되묻기 카드 안내(서버 상수). 후보가 있을 때만 온다. 이미 다시 물은 지난 차례에서는 숨긴다(FE-17 U-05) */}
        {response.candidates_line !== null && !hideCandidatesLine && !showPastPicks && (
          <p data-testid="candidates-line" className="m-0 px-1 text-xs leading-[17px] break-words text-mute">
            {response.candidates_line}
          </p>
        )}
      </div>
    </NoMascotZone>
  );
}
