"use client";

import Image from "next/image";
import { useEffect, useId, useRef } from "react";
import type { Candidate } from "@/lib/api";
import { BRAND_ASSETS } from "@/components/brand/assets.generated";
import { PRIMARY_BUTTON } from "@/components/button";
import { NoMascotZone } from "@/components/NoMascotZone";
import { ErrorState, MessageBubble, ProgressSteps } from "@/features/chat";
import { FixedNoticeBox } from "@/features/emergency";
import { EvidenceEntryButton } from "@/features/evidence";
import type { EvidenceMode } from "@/features/evidence";
import { PREGNANCY_PICK_HINT, PickCapsule, ResultView, groupCandidates } from "@/features/result";
import type { CandidatePicks } from "@/features/result";
import { cn } from "@/lib/utils";
import type { ChatTurn } from "@/stores/chat";
import { RESEND_WITH_PICKS_LABEL, RESEND_WITH_PICK_LABEL, remainingPicksHint } from "./copy";

export interface ConversationProps {
  turns: ChatTurn[];
  /** 대화에 119 안내가 떠 있는지(진행 표시·오류의 마스코트를 숨긴다) */
  hasEmergency: boolean;
  /** 근거 상세가 열려 있는 차례 */
  evidenceTurnId: string | null;
  /** 진입 버튼 글자 종류(폭으로 정한다) */
  entryLabelMode: EvidenceMode;
  /** 되묻기에서 고른 후보(차례별 → 묶음 `input_name`별). 고르기만 하고 보내지 않는다 */
  picked: Readonly<Record<string, CandidatePicks>>;
  onOpenEvidence: (turnId: string) => void;
  onRetry: (turnId: string) => void;
  onPick: (turnId: string, candidate: Candidate) => void;
  /** "목록에 없어요 · 직접 입력", "이름 다시 입력": 입력창으로 간다 */
  onOther: () => void;
  /** 고른 후보 전부를 붙여 같은 질문을 한 번 다시 보낸다(모든 묶음을 골랐을 때만 부른다) */
  onResend: (turnId: string) => void;
  /**
   * 내용 폭 열의 클래스(FE-17 U-27: 가운데 정렬·최대 폭·좌우 여백). 스크롤 컨테이너(`chat-thread`)는 본문 전체 폭이고 이 열은 그 안쪽 래퍼다.
   * 입력 영역과 같은 값을 받는다(앱 셸이 정한다)
   */
  columnClassName?: string;
}

const NO_PICKS: CandidatePicks = {};
/** 비활성(`aria-disabled`) 확인 버튼의 모양: 주 버튼의 `disabled:` 모양과 같고, 호버·누름에 반응하지 않는다 */
/** 확인 줄 첫 행의 앱 심볼(캡슐 말풍선, 병아리 없음) 높이(FE-10 디자인 `.sym` 18px) */
const SYMBOL_HEIGHT = 18;
const SYMBOL = BRAND_ASSETS.symbol;
const SYMBOL_WIDTH = Math.round((SYMBOL_HEIGHT * SYMBOL.width) / SYMBOL.height);
const RESEND_DISABLED = "aria-disabled:cursor-not-allowed aria-disabled:bg-line aria-disabled:text-faint aria-disabled:brightness-100!";

interface TurnProps extends Omit<ConversationProps, "turns" | "columnClassName"> {
  turn: ChatTurn;
  /** 뒤 차례의 답이 이미 보이는 고정 안내 줄(같은 글자). 이 차례에서는 그 줄을 다시 그리지 않는다(FE-17 U-26-1) */
  noticeShownLater: ReadonlySet<string>;
  isLast: boolean;
  /** 다음 차례가 이 차례에서 고른 제품으로 같은 질문을 다시 물은 것인가(FE-17 U-05) */
  resent: boolean;
}

function TurnAnswer({ turn, isLast, resent, hasEmergency, noticeShownLater, evidenceTurnId, entryLabelMode, picked, onOpenEvidence, onRetry, onPick, onOther, onResend }: TurnProps) {
  const { stream } = turn;
  const statusId = useId();
  // 검증을 통과한 응답이 있으면 어떤 상태로 끝났든 그 결과를 보인다(done 없이 끊겨도 유지)
  if (stream.response) {
    const response = stream.response;
    // 후보는 마지막 차례에서만 고를 수 있다. 묶음(되묻는 이름)마다 하나씩 고르고, 모두 골라야 다시 물을 수 있다(FE-09-01 A)
    const groups = isLast && response.end_reason === "CLARIFY" ? groupCandidates(response.candidates) : [];
    const picks = (isLast ? picked[turn.id] : undefined) ?? NO_PICKS;
    const chosen = groups.flatMap((group) => (picks[group.inputName] ? [picks[group.inputName]] : []));
    const remaining = groups.length - chosen.length;
    const multiple = groups.length > 1;
    // 묶음이 하나면 고른 뒤에, 둘 이상이면 처음부터 확인 줄을 둔다(남은 묶음 수를 보인다)
    const showResend = groups.length > 0 && (multiple || chosen.length > 0);
    // 일반인으로 보내 받은 판정 결과 아래의 작은 한 줄(FE-11-03 A): 임부금기를 확인하지 않았음을 알린다. 임부금기 줄이 실제로 있으면(질문 문장의
    // "임신 중"을 서버가 우선한 경우) 두지 않는다. 임산부(true)·값 없음(null, 토글 없는 조립)에는 두지 않는다
    const showPregnancyHint = turn.pregnant === false && response.findings.length > 0 && !response.findings.some((finding) => finding.kind === "pregnancy");
    const resendButton = (className: string) => (
      // 모든 묶음을 골라야 보낼 수 있다. 비활성일 때도 초점은 받고(`aria-disabled`) 남은 수 안내를 읽어 준다
      <button
        type="button"
        data-testid="resend-button"
        aria-disabled={remaining > 0 ? true : undefined}
        aria-describedby={remaining > 0 ? statusId : undefined}
        onClick={() => {
          if (remaining === 0) onResend(turn.id);
        }}
        className={cn(PRIMARY_BUTTON, "flex-none", className, RESEND_DISABLED)}
      >
        {multiple ? RESEND_WITH_PICKS_LABEL : RESEND_WITH_PICK_LABEL}
      </button>
    );
    return (
      <div data-testid="turn-answer" className="flex flex-col gap-2.5">
        <ResultView
          response={response}
          footer={
            // 판정 줄이 있는 결과만 근거 상세로 들어간다(카드가 없으면 버튼 자리도 없다)
            response.findings.length > 0 ? (
              <EvidenceEntryButton
                mode={entryLabelMode}
                expanded={evidenceTurnId === turn.id}
                onClick={() => onOpenEvidence(turn.id)}
                // 약을 찾지 못한 줄(서버가 입력한 이름을 실어 보낸 줄)이 있으면 `· 찾아본 곳`
                lookup={response.findings.some((finding) => finding.input_name !== null)}
              />
            ) : undefined
          }
          // 지난 되묻기로는 다시 보내지 않는다
          onPickCandidate={isLast ? (candidate) => onPick(turn.id, candidate) : undefined}
          onOtherCandidate={isLast ? onOther : undefined}
          selectedCandidates={isLast ? picks : undefined}
          // `이름 다시 입력`도 마지막 차례에서만 둔다(입력창으로 간다)
          onRetryName={isLast ? onOther : undefined}
          // 여러 약 되묻기의 안내 줄은 아래 확인 줄 첫 행에 그린다(FE-10)
          hideCandidatesLine={showResend && multiple}
          // 고른 제품으로 다시 물은 지난 차례(FE-17 U-05): 고른 줄 요약(A 입력 → 제품 · 바꾸기)은 남기고 안내 줄·확인 줄은 숨긴다
          pastPicks={!isLast && resent ? picked[turn.id] : undefined}
        />
        {showPregnancyHint && (
          <NoMascotZone>
            <p data-testid="pregnancy-pick-hint" className="m-0 px-1 text-xs leading-[17px] break-words text-mute">
              {PREGNANCY_PICK_HINT}
            </p>
          </NoMascotZone>
        )}
        {showResend && multiple && (
          <NoMascotZone>
            {/* 여러 약 확인 줄(FE-10, 디자인 "FE-09 r2" `.cf`). 캡슐을 가로로 둘지는 이 칸의 폭(640px)으로 정한다 */}
            <div className="@container">
              <div data-testid="resend-pick" className="flex flex-col gap-2.5 rounded-2xl border border-line bg-bg-softer px-3.5 py-3">
                {/* 첫 행: 앱 심볼 + 되묻기 안내(응답 값 그대로) */}
                {response.candidates_line !== null && (
                  <p data-testid="candidates-line" className="m-0 flex items-center gap-2 text-[15px] leading-5 break-words text-ink-2">
                    <Image
                      src={SYMBOL.src}
                      alt=""
                      aria-hidden="true"
                      width={SYMBOL_WIDTH}
                      height={SYMBOL_HEIGHT}
                      draggable={false}
                      className="block flex-none select-none"
                      style={{ width: SYMBOL_WIDTH, height: SYMBOL_HEIGHT }}
                    />
                    <span className="min-w-0">{response.candidates_line}</span>
                  </p>
                )}
                <div className="flex flex-col gap-2.5 @[640px]:flex-row @[640px]:items-center @[640px]:gap-3">
                  {/* 고른 약(응답 값 그대로)을 묶음 순서대로 캡슐 칸에 담는다. 바뀌면 보조기기가 읽는다 */}
                  <div role="status" className="min-w-0 @[640px]:flex-1">
                    <PickCapsule names={groups.map((group) => picks[group.inputName]?.name ?? null)} />
                  </div>
                  {/* 좁으면 버튼이 왼쪽·남은 수가 오른쪽, 넓으면 남은 수 다음에 버튼 */}
                  <div className="flex flex-row-reverse items-center justify-between gap-3 @[640px]:flex-none @[640px]:flex-row">
                    <span id={statusId} role="status" className="text-[13px] leading-[18px] text-mute [word-break:keep-all]">
                      {remaining > 0 && <span data-testid="picks-remaining">{remainingPicksHint(remaining)}</span>}
                    </span>
                    {resendButton("px-[18px] text-[15px]")}
                  </div>
                </div>
              </div>
            </div>
          </NoMascotZone>
        )}
        {showResend && !multiple && (
          <NoMascotZone>
            {/* 묶음이 하나면 기존 모양 그대로다(FE-09-07 A): 고른 이름 + 다시 묻기 버튼 */}
            <div data-testid="resend-pick" className="flex flex-wrap items-center gap-2 rounded-2xl border border-line bg-bg-softer px-3.5 py-2">
              {/* 고른 후보의 이름(응답 값 그대로). 바뀌면 보조기기가 읽는다 */}
              <div id={statusId} role="status" className="min-w-0 flex-1 basis-40 text-sm [overflow-wrap:break-word] [word-break:keep-all]">
                <b data-testid="picked-name" className="font-semibold">
                  {chosen.map((candidate) => candidate.name).join(", ")}
                </b>
              </div>
              {resendButton("")}
            </div>
          </NoMascotZone>
        )}
        {/* 고정 안내(서버 `fixed_notice`, 코드 고정 문구)는 그 답 아래, 근거 상세 틀 밖의 접히지 않는 자리에 둔다(FE-17 U-26-1, 2026-11-24:
            입력창 위 고정 영역에서 옮김). 같은 글자의 줄이 뒤 차례 답에 또 있으면 여기서는 빼고 가장 최근 답에서 한 번만 보인다.
            가장 최근 답은 받은 줄을 모두 그리므로 "금기 목록에 없다는 것이 안전하다는 뜻이 아니에요…"는 결과 화면에 늘 한 번 남는다 */}
        <FixedNoticeBox lines={response.fixed_notice.filter((line) => !noticeShownLater.has(line))} />
      </div>
    );
  }
  if (stream.status === "streaming") return <ProgressSteps stage={stream.stage} label={stream.label} hideMascot={hasEmergency} />;
  if (stream.status === "error" || stream.status === "interrupted") {
    return <ErrorState stream={stream} onRetry={() => onRetry(turn.id)} allowRetry={isLast} hideMascot={hasEmergency} />;
  }
  return null; // idle, 사용자가 끊은 차례(aborted)는 질문만 남긴다
}

/** 대화 영역 위 여백(`pt-2`). 답변 블록을 위쪽에 맞출 때 이만큼 띄운다 */
const THREAD_PADDING_TOP = 8;

/**
 * 대화 스레드: 질문과 그 답(진행 표시 → 결과 또는 오류)을 받은 순서대로 그린다.
 *
 * 스크롤 규칙(FE-02 §3 "긴 결과 카드 윗부분이 첫 화면 밖", 2026-11-20 사용자 지시):
 * - 질문을 보내고 진행 표시가 바뀌는 동안은 맨 아래를 따라간다(기존 동작).
 * - 최종 답변(`stream.response`)이 오면 **그 답변 블록의 맨 위(요약 시작)**를 대화 영역 위쪽에 맞춘다. 맨 아래로 붙이면 393px에서
 *   결과 카드가 영역보다 커서 "삐! 병용금기" 판정 줄·요약이 첫 화면 밖으로 밀린다. 119 배너는 이 영역 밖(위 고정)이라 그대로다.
 * - 이 차례에서 사용자가 직접 스크롤했으면(프로그램이 맞춘 위치와 다르면) 억지로 옮기지 않는다. 다음 차례(또는 다시 시도)에서 푼다.
 */
export function Conversation({ turns, columnClassName, ...rest }: ConversationProps) {
  const thread = useRef<HTMLDivElement>(null);
  const end = useRef<HTMLDivElement>(null);
  /** 프로그램이 마지막으로 맞춘 위치와 그때의 크기. 크기가 그대로인데 `scrollTop`만 다르면 사용자가 움직인 것이다(크기가 바뀌어 브라우저가 자른 것은 아니다) */
  const placed = useRef<{ top: number; scrollHeight: number; clientHeight: number } | null>(null);
  const userScrolled = useRef(false);
  const last = turns[turns.length - 1];
  const lastId = last?.id;
  const streaming = last?.stream.status === "streaming";

  // 차례가 새로 시작되면(새 질문·다시 시도) 사용자 스크롤 표시를 지운다. 아래 맞춤 효과보다 먼저 둔다(선언 순서대로 실행)
  useEffect(() => {
    if (streaming) userScrolled.current = false;
  }, [lastId, streaming]);

  useEffect(() => {
    const box = thread.current;
    if (!box || userScrolled.current) return;
    if (last?.stream.response) {
      // 마지막 차례의 답변 블록(마지막 `turn-answer`)의 위를 영역 위쪽(여백만큼 아래)에 맞춘다. 브라우저가 범위 안으로 잘라 준다
      const answers = box.querySelectorAll<HTMLElement>('[data-testid="turn-answer"]');
      const answer = answers[answers.length - 1];
      if (answer) box.scrollTop = Math.max(0, box.scrollTop + answer.getBoundingClientRect().top - box.getBoundingClientRect().top - THREAD_PADDING_TOP);
    } else {
      end.current?.scrollIntoView?.({ block: "end" });
    }
    placed.current = { top: box.scrollTop, scrollHeight: box.scrollHeight, clientHeight: box.clientHeight };
  }, [turns.length, last?.stream.status, last?.stream.stage, last?.stream.response]);

  const onScroll = () => {
    const box = thread.current;
    const mark = placed.current;
    if (!box || !mark) return;
    if (mark.scrollHeight === box.scrollHeight && mark.clientHeight === box.clientHeight && Math.abs(box.scrollTop - mark.top) > 1) userScrolled.current = true;
  };

  return (
    // 스크롤 컨테이너는 본문 전체 폭(스크롤바가 본문 오른쪽 가장자리, FE-17 U-27), 내용은 안쪽 열(`chat-column`)이 가운데 정렬·최대 폭으로 잡는다.
    // 위아래 여백(`pt-2`·`pb-3`)은 스크롤 컨테이너에 둔다(`THREAD_PADDING_TOP` 맞춤의 기준이 이 상자의 위쪽이다)
    <div ref={thread} data-testid="chat-thread" onScroll={onScroll} className="flex min-h-0 flex-1 flex-col overflow-y-auto pt-2 pb-3">
      <div data-testid="chat-column" className={cn("flex flex-none flex-col", columnClassName)}>
        <div className="flex flex-col gap-3.5 px-0.5">
          {turns.map((turn, index) => {
            const next = turns[index + 1];
            const noticeShownLater = new Set(turns.slice(index + 1).flatMap((later) => later.stream.response?.fixed_notice ?? []));
            return (
              <div key={turn.id} data-turn={turn.id} data-status={turn.stream.status} className="flex flex-col gap-2.5">
                {/* 고른 약으로 다시 물은 차례(`display`가 있음)는 말풍선을 그리지 않는다(FE-17 U-17: 지난 답의 고른 줄 요약 바로 다음에 진행 표시·새 답이 이어진다).
                    서버로 간 것은 예전처럼 원 질문 + 고른 약이고(요청 계약 불변), `display`는 차례 표시(지난 답 읽기 전용 판정 `resent`)에만 쓴다 */}
                {turn.display == null && <MessageBubble side="me">{turn.question}</MessageBubble>}
                <TurnAnswer turn={turn} isLast={turn === last} noticeShownLater={noticeShownLater} resent={next !== undefined && next.display !== undefined && next.display !== null && next.question === turn.question} {...rest} />
              </div>
            );
          })}
          <div ref={end} />
        </div>
      </div>
    </div>
  );
}
