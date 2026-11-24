import type { Finding } from "@/lib/api";
import { cn } from "@/lib/utils";
import { IngredientChips } from "./IngredientChips";
import { isLabelFinding, labelLines, splitItemCode } from "./label-merge";
import { notesWithoutApiFlag } from "./realtime-notice";
import { StatusBadge } from "./StatusBadge";

// 배지가 없는 줄의 상태 글자 모양(글자는 응답의 `text` 그대로). 종류는 `bucket` 값으로만 고른다.
const STATUS_CLASS: Record<Finding["bucket"], string> = {
  found: "bg-warn-bg text-warn-ink", // 배지 없는 발견 줄(금기가 아닌 주의 종류)
  not_listed: "bg-bg-soft text-ink-2",
  identified: "bg-bg-soft text-ink-2",
  unconfirmed: "border border-dashed border-faint bg-bg text-ink-2",
};

// 화면 라벨(사유 줄 머리, PRD-09 §7.4 `· 사유: {금기사유 원문}`). 판정·고정 문구가 아니다
const REASON_LABEL = "사유: ";

function SubLine({ children, slot, ...data }: { children: React.ReactNode; slot: string; [key: `data-${string}`]: string | undefined }) {
  return (
    <p data-slot={slot} {...data} className="m-0 text-xs leading-[17px] break-words text-mute">
      {children}
    </p>
  );
}

/**
 * 판정 줄 하나(제품 줄 또는 쌍 줄). 판정·문구·배지·성분은 모두 응답 값이고 화면이 조합·재정렬하지 않는다.
 *
 * 배치(PRD-15-01·02): 제목이 먼저 전체 폭을 갖고 띄어쓰기 단위로만 줄바꿈한다. 배지는 제목 옆에 다 들어가면 같은 줄에,
 * 아니면 아래 줄에 가로로 놓이고 넘치면 배지 단위로 줄바꿈한다. 폭별 분기 없이 `flex-wrap` 한 규칙이다.
 *
 * "목록에 없음" 줄의 "안전하다는 뜻이 아님"은 응답의 `text` 안에 있고, 이 줄은 펼침 요소 안에 두지 않는다(항상 보인다, S5).
 */
export function ProductLine({
  finding,
  omitLookupLines = false,
  omitApiFlagNotes = false,
  labels = [],
}: {
  finding: Finding;
  /** 찾아본 내용 표(근거 상세 `LookupPairs`)가 같은 글자를 바로 아래에 보일 때 true: 이유·재검색·다음 행동 줄을 한 번 더 그리지 않는다(PRD-12-04 같은 글자는 박스 안에서 한 번) */
  omitLookupLines?: boolean;
  /** 본문(결과 카드)에서 true: 실시간 확인 노트(`api_flag_note` 문구)를 그리지 않는다(근거 상세에만, FE-11-10 A). 그 밖의 노트는 그대로다 */
  omitApiFlagNotes?: boolean;
  /**
   * 이 줄 안으로 합친 같은 약의 허가사항 항목 줄(FE-17 U-28, `mergeLabelFindings`). 받은 글자를 이 줄의 덧붙임 줄(`notes`) 바로 다음에
   * 같은 모양의 줄로 보인다(줄 하나). 항목 줄의 근거 ID는 `data-evidence-ids`에 남는다
   */
  labels?: readonly Finding[];
}) {
  const hasBadges = finding.badges.length > 0;
  // 배지 덧붙임 글(예: M등급) 중 줄의 `note`와 겹치지 않는 것
  const badgeNotes = [...new Set(finding.badges.map((badge) => badge.note).filter((note): note is string => !!note && note !== finding.note))];
  const notes = omitApiFlagNotes ? notesWithoutApiFlag(finding) : finding.notes;
  // 허가사항 항목 줄은 문장 맨 앞의 품목 기준 코드를 화면에서만 숨긴다(FE-17 U-28 (c)). 숨긴 코드는 `data-item-code`에 남는다
  const label = isLabelFinding(finding);
  const status = label ? splitItemCode(finding.text) : { text: finding.text, code: null };
  const shownNotes = label ? notes.map(splitItemCode) : notes.map((text) => ({ text, code: null }));
  const merged = labels.flatMap((item) =>
    labelLines(item, [...notes, ...(finding.note ? [finding.note] : [])], omitApiFlagNotes ? notesWithoutApiFlag(item) : item.notes).map((line) => ({ ...line, evidenceId: item.evidence_id })),
  );
  return (
    <li
      data-testid="product-line"
      data-target={finding.target}
      data-bucket={finding.bucket}
      data-kind={finding.kind ?? undefined}
      data-merged-labels={labels.length > 0 ? labels.length : undefined}
      className="flex flex-col gap-1 border-t border-line px-3.5 py-[11px] first:border-t-0"
    >
      <div className="flex flex-wrap items-start gap-x-2.5 gap-y-1.5 text-[15px] leading-[21px]">
        <b data-testid="line-title" className="max-w-full flex-none font-semibold [overflow-wrap:break-word] [word-break:keep-all]">
          {finding.drug}
        </b>
        <span data-testid="line-status" className="ml-auto flex max-w-full flex-none flex-wrap justify-start gap-1">
          {hasBadges ? (
            finding.badges.map((badge, index) => <StatusBadge key={index} badge={badge} />)
          ) : (
            <span
              data-testid="line-text"
              data-item-code={status.code ?? undefined}
              className={cn(
                "inline-flex max-w-full items-center rounded-xl px-2.5 py-[3px] text-xs leading-[17px] font-bold [overflow-wrap:break-word] [word-break:keep-all]",
                STATUS_CLASS[finding.bucket],
              )}
            >
              {status.text}
            </span>
          )}
        </span>
      </div>
      {/* 표지 아래 보조줄(서버가 만든 값: 식별된 약의 성분 이름, 약을 찾지 못한 줄의 안내). 받은 그대로 */}
      {finding.sub_line && (
        <p data-slot="sub-line" className="m-0 text-[13px] leading-[19px] break-words text-ink-2">
          {finding.sub_line}
        </p>
      )}
      {/* 식별된 약 줄은 보조줄이 성분 이름을 이미 보이므로(서버가 이은 글자) 같은 이름의 칩을 한 번 더 그리지 않는다 */}
      {!(finding.bucket === "identified" && finding.sub_line) && <IngredientChips ingredients={finding.ingredients} />}
      {/* 보조줄: 받은 값을 한 값에 한 줄씩, 받은 그대로. 나이 안내 줄은 나이 기준 값 위에 둔다(판정이 아니라 원문 값이라는 안내) */}
      {finding.age_info_line && <SubLine slot="age-info">{finding.age_info_line}</SubLine>}
      {finding.age_criteria.map((value, index) => (
        <SubLine key={`age-${index}`} slot="age-criteria">
          {value}
        </SubLine>
      ))}
      {/* 병용금기 사유 원문(서버 `reasons`, FE-02-06 A): 받은 글자를 자르지 않고 CSS 2줄 말줄임만 쓴다(전체 글자는 DOM에 남는다). 전문은 근거 상세 "사유 원문" */}
      {finding.reasons.map((reason, index) => (
        <p key={`reason-${index}`} data-slot="reason" className="m-0 line-clamp-2 text-xs leading-[17px] break-words text-mute">
          {REASON_LABEL}
          {reason}
        </p>
      ))}
      {finding.note && <SubLine slot="note">{finding.note}</SubLine>}
      {badgeNotes.map((note, index) => (
        <SubLine key={`badge-note-${index}`} slot="badge-note">
          {note}
        </SubLine>
      ))}
      {shownNotes.map((note, index) => (
        <SubLine key={`notes-${index}`} slot="notes" data-item-code={note.code ?? undefined}>
          {note.text}
        </SubLine>
      ))}
      {/* 같은 약의 허가사항 항목 줄(FE-17 U-28): 덧붙임 줄 바로 다음, 같은 모양(받은 글자 그대로, 품목 기준 코드만 숨김) */}
      {merged.map((line, index) => (
        <SubLine key={`label-${index}`} slot="notes" data-merged="label" data-evidence-ids={line.evidenceId ?? undefined} data-item-code={line.code ?? undefined}>
          {line.text}
        </SubLine>
      ))}
      {!omitLookupLines && finding.why && <SubLine slot="why">{finding.why}</SubLine>}
      {!omitLookupLines && finding.retried_line && <SubLine slot="retried">{finding.retried_line}</SubLine>}
      {!omitLookupLines && finding.next && <SubLine slot="next">{finding.next}</SubLine>}
      {finding.reference_line && <SubLine slot="reference">{finding.reference_line}</SubLine>}
      {finding.source_label && <SubLine slot="source">{finding.source_label}</SubLine>}
    </li>
  );
}
