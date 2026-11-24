import type { Finding } from "@/lib/api";
import { cn } from "@/lib/utils";
import { IngredientChips } from "./IngredientChips";
import { isLabelFinding, labelLines, splitItemCode } from "./label-merge";
import type { MergedFinding } from "./label-merge";
import { notesWithoutApiFlag } from "./realtime-notice";
import { mergeSourceBadges, shortStatusText, withoutApiSame } from "./row-merge";
import type { PairDoseLine } from "./row-merge";
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
/** 쌍 줄 안 약별 주의 줄의 약 이름과 글자 사이(FE-17 U-30 (d), 근거 상세 `약 이름 - 제형유형 N건`과 같은 ` - `) */
const PAIR_DOSE_JOIN = " - ";

function SubLine({ children, slot, ...data }: { children: React.ReactNode; slot: string; [key: `data-${string}`]: string | undefined }) {
  return (
    <p data-slot={slot} {...data} className="m-0 text-xs leading-[17px] break-words text-mute">
      {children}
    </p>
  );
}

interface LineOptions {
  omitLookupLines: boolean;
  omitApiFlagNotes: boolean;
}

/** 줄 하나의 상태 표지(배지 또는 상태 글자 칩). 출처 꼬리만 다른 같은 배지는 하나로(U-30 (a)), `NOT_LISTED`는 괄호 안내를 뗀다(U-30 (e)) */
function statusChips(finding: Finding, keyPrefix: string): { key: string; node: React.ReactNode }[] {
  if (finding.badges.length > 0) {
    return mergeSourceBadges(finding.badges).map((badge, index) => ({ key: `badge|${badge.text}`, node: <StatusBadge key={`${keyPrefix}-b${index}`} badge={badge} /> }));
  }
  // 허가사항 항목 줄은 문장 맨 앞의 품목 기준 코드를 화면에서만 숨긴다(FE-17 U-28 (c)). 숨긴 코드는 `data-item-code`에 남는다
  const status = isLabelFinding(finding) ? splitItemCode(finding.text) : { text: finding.text, code: null };
  const shown = shortStatusText(status.text);
  return [
    {
      key: `text|${finding.bucket}|${shown}`,
      node: (
        <span
          key={`${keyPrefix}-t`}
          data-testid="line-text"
          data-item-code={status.code ?? undefined}
          data-full-text={shown !== status.text ? status.text : undefined}
          className={cn(
            "inline-flex max-w-full items-center rounded-xl px-2.5 py-[3px] text-xs leading-[17px] font-bold [overflow-wrap:break-word] [word-break:keep-all]",
            STATUS_CLASS[finding.bucket],
          )}
        >
          {shown}
        </span>
      ),
    },
  ];
}

/**
 * 줄 하나의 아래 줄들(받은 값 그대로, 받은 순서). `seen`에 이미 있는 (칸, 글자)는 다시 그리지 않는다(같은 약 행으로 합친 줄 사이에서 같은 글자는 한 번, U-30 (b))
 */
function lineBody(
  finding: Finding,
  labels: readonly Finding[],
  { omitLookupLines, omitApiFlagNotes }: LineOptions,
  seen: Set<string>,
  keyPrefix: string,
  pairDose: readonly PairDoseLine[] = [],
): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let n = 0;
  const once = (slot: string, text: string) => {
    const key = `${slot}|${text}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  };
  const sub = (slot: string, text: string, data: Record<`data-${string}`, string | undefined> = {}) => {
    if (!once(slot, text)) return;
    out.push(
      <SubLine key={`${keyPrefix}-${n++}`} slot={slot} {...data}>
        {text}
      </SubLine>,
    );
  };
  // 배지 덧붙임 글(예: M등급) 중 줄의 `note`와 겹치지 않는 것
  const badgeNotes = [...new Set(finding.badges.map((badge) => badge.note).filter((note): note is string => !!note && note !== finding.note))];
  // `파일과 실시간 조회 결과가 같아요`는 본문·근거 상세 모두 뺀다(U-30 (f)). 본문은 실시간 확인 노트도 뺀다(FE-11-10 A)
  const notes = withoutApiSame(omitApiFlagNotes ? notesWithoutApiFlag(finding) : finding.notes);
  const label = isLabelFinding(finding);
  const merged = labels.flatMap((item) =>
    labelLines(item, [...notes, ...(finding.note ? [finding.note] : [])], withoutApiSame(omitApiFlagNotes ? notesWithoutApiFlag(item) : item.notes)).map((line) => ({ ...line, evidenceId: item.evidence_id })),
  );

  // 표지 아래 보조줄(서버가 만든 값: 식별된 약의 성분 이름, 약을 찾지 못한 줄의 안내). 받은 그대로
  if (finding.sub_line && once("sub-line", finding.sub_line)) {
    out.push(
      <p key={`${keyPrefix}-${n++}`} data-slot="sub-line" className="m-0 text-[13px] leading-[19px] break-words text-ink-2">
        {finding.sub_line}
      </p>,
    );
  }
  // 식별된 약 줄은 보조줄이 성분 이름을 이미 보이므로(서버가 이은 글자) 같은 이름의 칩을 한 번 더 그리지 않는다
  if (!(finding.bucket === "identified" && finding.sub_line) && finding.ingredients.length > 0 && once("ingredients", JSON.stringify(finding.ingredients))) {
    out.push(<IngredientChips key={`${keyPrefix}-${n++}`} ingredients={finding.ingredients} />);
  }
  // 보조줄: 받은 값을 한 값에 한 줄씩, 받은 그대로. 나이 안내 줄은 나이 기준 값 위에 둔다(판정이 아니라 원문 값이라는 안내)
  if (finding.age_info_line) sub("age-info", finding.age_info_line);
  for (const value of finding.age_criteria) sub("age-criteria", value);
  // 병용금기 사유 원문(서버 `reasons`, FE-02-06 A): 받은 글자를 자르지 않고 CSS 2줄 말줄임만 쓴다(전체 글자는 DOM에 남는다). 전문은 근거 상세
  for (const reason of finding.reasons) {
    if (!once("reason", reason)) continue;
    out.push(
      <p key={`${keyPrefix}-${n++}`} data-slot="reason" className="m-0 line-clamp-2 text-xs leading-[17px] break-words text-mute">
        {REASON_LABEL}
        {reason}
      </p>,
    );
  }
  if (finding.note) sub("note", finding.note);
  for (const note of badgeNotes) sub("badge-note", note);
  for (const raw of notes) {
    const note = label ? splitItemCode(raw) : { text: raw, code: null };
    sub("notes", note.text, { "data-item-code": note.code ?? undefined });
  }
  // 같은 약의 허가사항 항목 줄(FE-17 U-28): 덧붙임 줄 바로 다음, 같은 모양(받은 글자 그대로, 품목 기준 코드만 숨김)
  for (const line of merged) sub("notes", line.text, { "data-merged": "label", "data-evidence-ids": line.evidenceId ?? undefined, "data-item-code": line.code ?? undefined });
  // 쌍 줄: 두 약 모두 하루 최대량 주의 성분이 있으면 약 이름별로 같은 글자(FE-17 U-30 (d)). 병용금기 목록 여부와 별개의 주의라 경고 색이다
  for (const line of pairDose) {
    if (!once("pair-dose", `${line.drug}|${line.text}`)) continue;
    out.push(
      <p key={`${keyPrefix}-${n++}`} data-slot="pair-dose" data-drug={line.drug} className="m-0 flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs leading-[17px] break-words text-ink-2">
        <span className="[overflow-wrap:break-word] [word-break:keep-all]">
          {line.drug}
          {PAIR_DOSE_JOIN}
        </span>
        <span data-testid="pair-dose-text" className="rounded-xl bg-warn-bg px-2 py-px font-bold text-warn-ink">
          {line.text}
        </span>
      </p>,
    );
  }
  if (!omitLookupLines && finding.why) sub("why", finding.why);
  if (!omitLookupLines && finding.retried_line) sub("retried", finding.retried_line);
  if (!omitLookupLines && finding.next) sub("next", finding.next);
  if (finding.reference_line) sub("reference", finding.reference_line);
  if (finding.source_label) sub("source", finding.source_label);
  return out;
}

/**
 * 판정 줄 하나(제품 줄 또는 쌍 줄). 판정·문구·배지·성분은 모두 응답 값이고 화면은 값을 짓지 않는다.
 *
 * 배치(PRD-15-01·02): 제목이 먼저 전체 폭을 갖고 띄어쓰기 단위로만 줄바꿈한다. 배지는 제목 옆에 다 들어가면 같은 줄에,
 * 아니면 아래 줄에 가로로 놓이고 넘치면 배지 단위로 줄바꿈한다. 폭별 분기 없이 `flex-wrap` 한 규칙이다.
 *
 * 표시 가공(FE-17 U-30, 2026-11-24 사용자 지시, `row-merge.ts`): 출처 꼬리만 다른 같은 배지 하나로, 같은 약의 다른 줄(`siblings`)은 이 행 안으로
 * (표지는 제목 옆에 이어서, 아래 줄은 줄마다 받은 순서로, 같은 글자는 한 번), `금기 목록에 없음(안전하다는 뜻이 아님)`은 `금기 목록에 없음`으로
 * (전체 글자는 `data-full-text`), `파일과 실시간 조회 결과가 같아요` 노트는 뺀다. "안전하다는 뜻이 아니에요" 안내는 결과 화면의 고정 안내가 보인다.
 */
export function ProductLine({
  finding,
  omitLookupLines = false,
  omitApiFlagNotes = false,
  labels = [],
  siblings = [],
  pairDose = [],
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
  /** 같은 약(줄 머리 약 이름이 같음)이라 이 행으로 합친 다른 줄(FE-17 U-30 (b), 본문). 받은 순서 */
  siblings?: readonly MergedFinding[];
  /** 쌍 줄 안 약별 하루 최대량 주의 줄(FE-17 U-30 (d), `pairDoseLines`) */
  pairDose?: readonly PairDoseLine[];
}) {
  const options = { omitLookupLines, omitApiFlagNotes };
  const chipKeys = new Set<string>();
  const chips: React.ReactNode[] = [];
  for (const [index, member] of [finding, ...siblings.map((sibling) => sibling.finding)].entries()) {
    for (const chip of statusChips(member, `m${index}`)) {
      if (chipKeys.has(chip.key)) continue;
      chipKeys.add(chip.key);
      chips.push(chip.node);
    }
  }
  const seen = new Set<string>();
  const body = [
    ...lineBody(finding, labels, options, seen, "m0", pairDose),
    ...siblings.flatMap((sibling, index) => lineBody(sibling.finding, sibling.labels, options, seen, `m${index + 1}`)),
  ];
  const mergedLabels = labels.length + siblings.reduce((sum, sibling) => sum + sibling.labels.length, 0);
  return (
    <li
      data-testid="product-line"
      data-target={finding.target}
      data-bucket={finding.bucket}
      data-kind={finding.kind ?? undefined}
      data-merged-labels={mergedLabels > 0 ? mergedLabels : undefined}
      data-merged-rows={siblings.length > 0 ? siblings.length + 1 : undefined}
      data-kinds={siblings.length > 0 ? [finding, ...siblings.map((sibling) => sibling.finding)].map((member) => member.kind ?? "").join(" ") : undefined}
      className="flex flex-col gap-1 border-t border-line px-3.5 py-[11px] first:border-t-0"
    >
      <div className="flex flex-wrap items-start gap-x-2.5 gap-y-1.5 text-[15px] leading-[21px]">
        <b data-testid="line-title" className="max-w-full flex-none font-semibold [overflow-wrap:break-word] [word-break:keep-all]">
          {finding.drug}
        </b>
        <span data-testid="line-status" className="ml-auto flex max-w-full flex-none flex-wrap justify-start gap-1">
          {chips}
        </span>
      </div>
      {body}
    </li>
  );
}
