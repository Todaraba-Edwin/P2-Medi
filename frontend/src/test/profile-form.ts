// 프로필 폼 시험 도우미(FE-17 U-07, 2026-11-23): 관계·연령대·성별이 select가 아니라 버튼 선택(radiogroup)이고 필수 4칸을 채워야 `저장`이 눌린다.
// 시험이 보려는 값은 그대로 두고(이미 고른 칸은 건드리지 않는다) 비어 있는 필수 칸만 기본값으로 채운다.
import { screen, within } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";

/** 칸 이름(관계·연령대·성별)의 버튼 묶음 */
export const choiceGroup = (name: string) => screen.getByRole("radiogroup", { name });

/** 칸 이름의 묶음에서 보이는 글자로 고른다(예: `pickChoice(user, "성별", "여성")`) */
export async function pickChoice(user: UserEvent, group: string, option: string) {
  await user.click(within(choiceGroup(group)).getByRole("radio", { name: option }));
}

/** 묶음에서 고른 칸의 글자(아직 안 골랐으면 null) */
export function checkedChoice(group: string): string | null {
  const checked = within(choiceGroup(group)).queryAllByRole("radio").find((radio) => radio.getAttribute("aria-checked") === "true");
  return checked?.textContent ?? null;
}

/**
 * 비어 있는 필수 칸만 채운다: 관계(가족 = `자녀`), 연령대(`만 19~64세`), 성별(`남성`: 예전 미입력과 같이 임신 여부가 아니오로 저장된다). 이름은 시험이 직접 적는다(값을 보려는 시험이 많다).
 * 이미 고른 칸은 그대로 둔다
 */
export async function completeRequired(user: UserEvent, { relation = "자녀", age = "만 19~64세", sex = "남성" }: { relation?: string; age?: string; sex?: string } = {}) {
  if (checkedChoice("관계") === null) await pickChoice(user, "관계", relation);
  if (checkedChoice("연령대") === null) await pickChoice(user, "연령대", age);
  if (checkedChoice("성별") === null) await pickChoice(user, "성별", sex);
}
