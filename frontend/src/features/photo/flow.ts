// 사진 입력 흐름의 상태(순수 reducer, 메모리). 화면 부품(`PhotoModal`)이 `useReducer`로 쓴다.
// 단계: 사진 고르기(pick) → 인식 중(reading) → 확인·수정 카드(confirm) / 인식 실패(failed). 사진 파일·data URL은 상태에 두지 않는다
// (미리보기 object URL만 인식 중 단계에 잠깐 둔다).
import type { DrugCandidate } from "@/lib/api/account";
import type { Emergency } from "@/lib/api";
import { emptyRow, rowsFromResponse } from "./build-chat-input";
import type { PhotoRow } from "./build-chat-input";
import type { IngestDrug } from "./types";

export type PhotoFailKind = "unreadable" | "unavailable";

export type PhotoFlowState =
  | { step: "pick"; formatNote: boolean }
  | { step: "reading"; previewUrl: string | null }
  | { step: "failed"; kind: PhotoFailKind }
  | { step: "confirm"; rows: PhotoRow[]; question: string; emergency: Emergency | null };

export type PhotoFlowAction =
  | { type: "reset" }
  | { type: "formatRejected" }
  | { type: "startReading"; previewUrl: string | null }
  | { type: "readFailed"; kind: PhotoFailKind }
  | { type: "readOk"; drugs: readonly IngestDrug[]; emergency: Emergency | null }
  | { type: "editName"; id: string; value: string }
  | { type: "pick"; id: string; candidate: DrugCandidate | null }
  | { type: "remove"; id: string }
  | { type: "add" }
  | { type: "setQuestion"; value: string };

export const initialPhotoFlow: PhotoFlowState = { step: "pick", formatNote: false };

const patchRow = (rows: PhotoRow[], id: string, patch: Partial<PhotoRow>) => rows.map((row) => (row.id === id ? { ...row, ...patch } : row));

export function photoFlowReducer(state: PhotoFlowState, action: PhotoFlowAction): PhotoFlowState {
  switch (action.type) {
    case "reset":
      return initialPhotoFlow;
    case "formatRejected":
      return { step: "pick", formatNote: true };
    case "startReading":
      return { step: "reading", previewUrl: action.previewUrl };
    case "readFailed":
      return { step: "failed", kind: action.kind };
    case "readOk": {
      const rows = rowsFromResponse(action.drugs);
      // 읽은 항목이 없으면(서버가 OK라도 목록이 비면) 빈 줄 하나로 시작해 "약 추가"·글자 입력으로 잇는다(PRD 15.3 S11 "봉투에 약 이름이 없을 수 있다")
      return { step: "confirm", rows: rows.length > 0 ? rows : [emptyRow()], question: "", emergency: action.emergency };
    }
    case "editName":
      // 글자를 고치면 고른 후보는 푼다(후보는 읽은 글자로 찾은 것이라 글자가 바뀌면 맞지 않을 수 있다)
      return state.step === "confirm" ? { ...state, rows: patchRow(state.rows, action.id, { readName: action.value, picked: null }) } : state;
    case "pick":
      return state.step === "confirm" ? { ...state, rows: patchRow(state.rows, action.id, { picked: action.candidate }) } : state;
    case "remove":
      return state.step === "confirm" ? { ...state, rows: state.rows.filter((row) => row.id !== action.id) } : state;
    case "add":
      return state.step === "confirm" ? { ...state, rows: [...state.rows, emptyRow()] } : state;
    case "setQuestion":
      return state.step === "confirm" ? { ...state, question: action.value } : state;
  }
}
