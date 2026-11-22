"use client";

import { useEffect, useReducer, useRef } from "react";
import { Dialog } from "radix-ui";
import { HOVER_TEXT, PRIMARY_BUTTON, SECONDARY_BUTTON } from "@/components/button";
import { Mascot } from "@/components/Mascot";
import { NoMascotZone } from "@/components/NoMascotZone";
import { cn } from "@/lib/utils";
import type { MedicationInput } from "@/lib/api/account";
import { postIngestImage } from "./api";
import { buildChatInput, buildProfileMedications } from "./build-chat-input";
import type { ChatInputFromPhoto } from "./build-chat-input";
import {
  PHOTO_CLOSE_LABEL,
  PHOTO_ENTRY_LABEL,
  PHOTO_EXTERNAL_AI_NOTICE,
  PHOTO_FAILED,
  PHOTO_FORMAT_NOTE,
  PHOTO_PREVIEW_ALT,
  PHOTO_PRIVACY_NOTICE,
  PHOTO_READING,
  PHOTO_RETAKE_LABEL,
  PHOTO_TYPE_INSTEAD_LABEL,
  PHOTO_UNAVAILABLE,
} from "./copy";
import { initialPhotoFlow, photoFlowReducer } from "./flow";
import { PHOTO_ACCEPT, PhotoImageError, prepareImage } from "./image";
import { PhotoConfirmCard } from "./PhotoConfirmCard";
import type { PhotoDestination } from "./PhotoConfirmCard";

export type { PhotoDestination };

/** 코너 버튼(PRD-13-01 A, 계정 모달과 같은 모양): 모달 상자 기준 `position: absolute`, 누르는 영역 44px 이상, 불투명 바탕 */
const CORNER_CLASS = `absolute top-2 z-10 grid min-h-11 min-w-11 place-items-center rounded-full border border-line bg-bg text-sm font-bold text-link ${HOVER_TEXT}`;
/** 모달 상자: 단계가 바뀌어도 같은 크기(계정 모달과 같은 규칙). 넘치는 내용은 본문 안에서만 스크롤한다. 층(z)은 `stacked`가 정한다 */
const MODAL_BOX_CLASS =
  "@container absolute top-1/2 left-1/2 flex h-[calc(100%-24px)] w-[calc(100%-24px)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-3xl bg-bg shadow-lg outline-none sm:h-[min(642px,calc(100%-24px))] sm:w-[min(560px,calc(100%-24px))]";

export interface PhotoModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /**
   * 확인 카드 결과의 도착지(FE-04-27 A). 기본 `chat`: `이대로 확인`이 `onConfirm`으로 질문·확인 약을 넘긴다.
   * `profile`: 질문칸 없이 약 이름만 받아 `onRegister`로 프로필 복용 약 항목을 넘긴다(`onConfirm`은 부르지 않는다). 두 길은 섞이지 않는다
   */
  destination?: PhotoDestination;
  /** `이대로 확인`(채팅 목적지): 승인한 목록과 질문으로 조립하는 쪽이 기존 `/chat` 전송을 한 번 부른다. 모달은 닫힌다 */
  onConfirm: (input: ChatInputFromPhoto) => void;
  /** `이대로 확인`(프로필 목적지): 확인된 약(`item_seq`)과 확인 안 된 글자(`item_seq` null)를 폼이 목록에 더한다. 모달은 닫힌다 */
  onRegister?: (items: MedicationInput[]) => void;
  /** `글자로 입력`: 모달을 닫고 입력창으로 간다(초점은 조립하는 쪽이 준다) */
  onTypeInstead: () => void;
  /** 다른 모달(계정 모달) 위에 겹쳐 열 때 true: 스크림·상자를 한 층 위(z-50)에 둔다(확인 모달 `ConfirmDialog`와 같은 층) */
  stacked?: boolean;
  /** 닫힌 뒤 초점을 돌려줄 곳(Radix는 `Dialog.Trigger`가 없으면 돌려주지 않는다). 없으면 그대로 둔다 */
  onCloseAutoFocus?: () => void;
  /** 층을 그릴 자리(119 배너 아래 영역). 배너는 덮지 않는다 */
  container?: HTMLElement | null;
  /** 119 안내가 떠 있으면 마스코트를 그리지 않는다(PRD-06-02) */
  hasEmergency?: boolean;
  /** 모달이 머리줄의 119 진입점을 덮는 동안 누를 수 있게 모달 안에 둘 진입점(배너가 있으면 넘기지 않는다) */
  emergencyEntry?: React.ReactNode;
  /** 시험에서 끼워 넣는다(jsdom에는 canvas가 없다) */
  prepare?: typeof prepareImage;
  post?: typeof postIngestImage;
}

/**
 * 사진 입력 중앙 모달(FE-05 사진 부분, PRD-13-03 A 코너 규칙): 사진 고르기 → 인식 중 → 확인·수정 카드 / 인식 실패.
 * - header 띠 없음, `닫기`는 우상단 `position: absolute` 44×44 이상, 단계가 없으므로 `<`는 DOM에 없다. `닫기`·Esc는 승인 없이 버리며 `/chat`을 부르지 않는다(H19)
 * - 개인정보 가림 안내(P1)·외부 AI 전송 고지(P2)는 사진 고르기 버튼 **위**에 접히지 않게 둔다(PJ2-PRD.md 15.4). 형식·크기 안내(P7)는 버튼 아래 한 줄이고 거절되면 강조된다
 * - 사진은 브라우저 메모리에서만 준비해(`image.ts`) `POST /api/ingest/image`로 보내고, data URL은 보낸 뒤 참조를 버린다. 미리보기는 object URL이며 인식이 끝나면 놓아준다
 * - 응답 `status`로 분기: OK → 카드, UNAVAILABLE → P8, 그 밖(UNREADABLE·오류) → P4. 응답의 `emergency`는 카드 맨 위에 서버 값 그대로
 * - 미식별 결과 카드 아래의 두 번째 입구(`약 사진 올리기`)는 이번에 만들지 않는다(〔D5〕A)
 * - 프로필 등록 목적지(FE-04-27 A): 온보딩·프로필 폼의 `사진으로 등록`이 같은 모달을 `destination="profile"`로 연다. 사진 고르기·인식·실패·고지(P1·P2)는 그대로이고
 *   확인 카드에 질문칸이 없으며 `이대로 확인`은 `onRegister`로 이름만 넘긴다. 사진·data URL은 여기서도 상태에 두지 않는다
 */
export function PhotoModal({
  open,
  onOpenChange,
  destination = "chat",
  onConfirm,
  onRegister,
  onTypeInstead,
  onCloseAutoFocus,
  stacked = false,
  container = null,
  hasEmergency = false,
  emergencyEntry = null,
  prepare = prepareImage,
  post = postIngestImage,
}: PhotoModalProps) {
  const [flow, dispatch] = useReducer(photoFlowReducer, initialPhotoFlow);
  const content = useRef<HTMLDivElement>(null);
  const body = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const controller = useRef<AbortController | null>(null);
  const focusTitle = () => content.current?.querySelector<HTMLElement>("[data-photo-title]")?.focus();

  // 닫히면 진행 중인 요청을 끊고 처음 단계로 돌린다(사진·목록은 메모리에서 사라진다)
  useEffect(() => {
    if (open) return;
    controller.current?.abort();
    controller.current = null;
    dispatch({ type: "reset" });
  }, [open]);

  // 단계가 바뀌면 본문을 맨 위로 올리고 제목을 읽게 한다
  useEffect(() => {
    if (!open) return;
    body.current?.scrollTo?.({ top: 0 });
    focusTitle();
  }, [open, flow.step]);

  const read = async (file: File) => {
    controller.current?.abort();
    const own = new AbortController();
    controller.current = own;
    const previewUrl = typeof URL.createObjectURL === "function" ? URL.createObjectURL(file) : null;
    dispatch({ type: "startReading", previewUrl });
    try {
      const prepared = await prepare(file);
      if (own.signal.aborted) return;
      // data URL은 요청에만 쓰고 상태에 두지 않는다(이 블록을 벗어나면 참조가 사라진다)
      const result = await post({ image: prepared.dataUrl }, own.signal);
      if (own.signal.aborted) return;
      if (result.status === "OK") dispatch({ type: "readOk", drugs: result.drugs, emergency: result.emergency });
      else dispatch({ type: "readFailed", kind: result.status === "UNAVAILABLE" ? "unavailable" : "unreadable" });
    } catch (error) {
      if (own.signal.aborted) return;
      if (error instanceof PhotoImageError) dispatch({ type: "formatRejected" }); // 형식·크기: 보내지 않고 P7
      else dispatch({ type: "readFailed", kind: "unreadable" }); // 연결·서버 오류: P4(다시 찍기·글자로 입력)
    } finally {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      if (controller.current === own) controller.current = null;
    }
  };

  const openChooser = () => fileInput.current?.click();

  const confirm = () => {
    if (flow.step !== "confirm") return;
    if (destination === "profile") {
      // 프로필 목적지: 약 이름만 넘긴다(질문 없음). 채팅 전송(`onConfirm`)은 부르지 않는다
      const items = buildProfileMedications(flow.rows);
      onOpenChange(false);
      onRegister?.(items);
      return;
    }
    const input = buildChatInput(flow.rows, flow.question);
    onOpenChange(false);
    onConfirm(input);
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal container={container}>
        <Dialog.Overlay data-testid="photo-scrim" className={cn("absolute inset-0 bg-ink/50", stacked ? "z-50" : "z-40")} />
        <Dialog.Content
          ref={content}
          aria-describedby={undefined}
          data-testid="photo-modal"
          data-step={flow.step}
          data-destination={destination}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            focusTitle();
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            onCloseAutoFocus?.();
          }}
          // 바깥을 눌러도 닫지 않는다: 고치던 목록이 실수로 사라지지 않게 닫기·Esc로만 닫는다
          onPointerDownOutside={(event) => event.preventDefault()}
          className={cn(MODAL_BOX_CLASS, stacked ? "z-50" : "z-40")}
        >
          <Dialog.Close data-testid="photo-close" className={cn(CORNER_CLASS, "right-2 px-3")}>
            {PHOTO_CLOSE_LABEL}
          </Dialog.Close>
          {/* 파일 선택은 늘 DOM에 있다(`다시 찍기`가 바로 열 수 있게). 카메라·앨범은 브라우저가 고른다. 보이는 버튼이 누른다 */}
          <input
            ref={fileInput}
            type="file"
            accept={PHOTO_ACCEPT}
            tabIndex={-1}
            aria-hidden="true"
            data-testid="photo-file"
            className="sr-only"
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = ""; // 같은 파일을 다시 골라도 change가 나게
              if (file) void read(file);
            }}
          />
          <div ref={body} data-testid="photo-body" className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto">
            <div className="mx-auto flex w-full max-w-[520px] flex-col gap-3.5 px-5 pt-14 pb-5">
              <Dialog.Title data-photo-title tabIndex={-1} className="m-0 text-xl leading-7 font-extrabold outline-none [word-break:keep-all]">
                {PHOTO_ENTRY_LABEL}
              </Dialog.Title>
              {emergencyEntry && <div className="flex">{emergencyEntry}</div>}

              {flow.step === "pick" && (
                <>
                  {!hasEmergency && <Mascot variant="question" size={72} />}
                  {/* 가림 안내·전송 고지: 버튼 위, 접히지 않음, 마스코트 금지 영역 */}
                  <NoMascotZone>
                    <p role="note" data-testid="photo-privacy-notice" className="m-0 rounded-xl bg-fixed px-3 py-2 text-sm leading-5 text-ink-2 [word-break:keep-all]">
                      {PHOTO_PRIVACY_NOTICE}
                    </p>
                    <p role="note" data-testid="photo-external-ai-notice" className="m-0 mt-2 px-1 text-xs leading-[17px] text-mute [word-break:keep-all]">
                      {PHOTO_EXTERNAL_AI_NOTICE}
                    </p>
                  </NoMascotZone>
                  <button type="button" data-testid="photo-pick" onClick={openChooser} className={cn(PRIMARY_BUTTON, "w-full")}>
                    {PHOTO_ENTRY_LABEL}
                  </button>
                  <NoMascotZone>
                    <p
                      role={flow.formatNote ? "alert" : "note"}
                      data-testid="photo-format-note"
                      data-rejected={flow.formatNote ? "true" : undefined}
                      className={cn("m-0 px-1 text-xs leading-[17px] [word-break:keep-all]", flow.formatNote ? "font-semibold text-red-ink" : "text-mute")}
                    >
                      {PHOTO_FORMAT_NOTE}
                    </p>
                  </NoMascotZone>
                </>
              )}

              {flow.step === "reading" && (
                <>
                  {flow.previewUrl && (
                    // 미리보기는 메모리의 object URL이라 next/image 최적화 대상이 아니다(인식이 끝나면 놓아준다)
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={flow.previewUrl} alt={PHOTO_PREVIEW_ALT} data-testid="photo-preview" className="max-h-60 w-auto max-w-full self-start rounded-2xl object-contain" />
                  )}
                  {/* 진행 표시는 사진 아래(PJ2-PRD.md 15.4 "인식 중" 행). 돋보기 병아리는 119가 없을 때만(FE-06-01) */}
                  <div role="status" data-testid="photo-reading" className="flex items-end gap-2">
                    {!hasEmergency && <Mascot variant="search" size={72} />}
                    <div className="flex items-center gap-2 pb-2">
                      <span aria-hidden="true" className="size-5 flex-none rounded-full border-[2.5px] border-line-2 border-t-link motion-safe:animate-spin" />
                      <p className="m-0 text-[15px] font-bold">{PHOTO_READING}</p>
                    </div>
                  </div>
                </>
              )}

              {flow.step === "failed" && (
                <>
                  <NoMascotZone>
                    <p role="alert" data-testid="photo-failed" data-kind={flow.kind} className="m-0 rounded-xl bg-fixed px-3 py-2 text-sm leading-5 text-ink-2 [word-break:keep-all]">
                      {flow.kind === "unavailable" ? PHOTO_UNAVAILABLE : PHOTO_FAILED}
                    </p>
                  </NoMascotZone>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" data-testid="photo-retake" onClick={openChooser} className={cn(PRIMARY_BUTTON, "min-w-0 flex-1")}>
                      {PHOTO_RETAKE_LABEL}
                    </button>
                    <button type="button" data-testid="photo-type-instead" onClick={onTypeInstead} className={cn(SECONDARY_BUTTON, "min-w-0 flex-1")}>
                      {PHOTO_TYPE_INSTEAD_LABEL}
                    </button>
                  </div>
                </>
              )}

              {flow.step === "confirm" && (
                <PhotoConfirmCard
                  rows={flow.rows}
                  question={flow.question}
                  destination={destination}
                  emergency={flow.emergency}
                  onEditName={(id, value) => dispatch({ type: "editName", id, value })}
                  onPick={(id, candidate) => dispatch({ type: "pick", id, candidate })}
                  onRemove={(id) => dispatch({ type: "remove", id })}
                  onAdd={() => dispatch({ type: "add" })}
                  onQuestion={(value) => dispatch({ type: "setQuestion", value })}
                  onConfirm={confirm}
                />
              )}
            </div>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
