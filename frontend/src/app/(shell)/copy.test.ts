import { describe, expect, it } from "vitest";
import * as copy from "./copy";

describe("되묻기 다시 묻기 글자(FE-09)", () => {
  it("버튼 글자: 묶음 하나는 기존 글자, 둘 이상은 '이 약들로 확인하기'", () => {
    expect(copy.RESEND_WITH_PICK_LABEL).toBe("이 약으로 다시 묻기");
    expect(copy.RESEND_WITH_PICKS_LABEL).toBe("이 약들로 확인하기");
    expect(copy.remainingPicksHint(1)).toBe("1개 더 골라 주세요");
  });

  it.each([
    [["가나다정 100밀리그램", "가나다시럽"], "고른 약: 가나다정 100밀리그램, 가나다시럽으로 다시 확인"], // 받침 → 으로
    [["가나다시럽", "가나다연고"], "고른 약: 가나다시럽, 가나다연고로 다시 확인"], // 받침 없음 → 로
    [["가나다캡슐"], "고른 약: 가나다캡슐로 다시 확인"], // ㄹ 받침 → 로
    [["가나다정(성분)"], "고른 약: 가나다정(성분)으로 다시 확인"], // 끝의 기호는 건너뛰고 마지막 한글로 고른다
    [["ABC 500mg"], "고른 약: ABC 500mg로 다시 확인"], // 한글이 없으면 로
  ])("말풍선 표시 글자 %j", (names, expected) => {
    expect(copy.resendBubbleText(names)).toBe(expected);
  });

  it("판정·가부로 읽힐 글자가 없다", () => {
    const all = [copy.RESEND_WITH_PICKS_LABEL, copy.remainingPicksHint(2), copy.resendBubbleText(["가나다정"])].join(" ");
    expect(all).not.toMatch(/삐!|금기|안전|먹어도|드셔도/);
  });
});
