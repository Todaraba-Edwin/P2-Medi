import { cn } from "@/lib/utils";
import { groupLetter } from "./candidate-groups";
import { pickPendingLabel } from "./copy";

/**
 * 이어 붙인 캡슐(FE-10, 디자인 "FE-09 r2" `.tag`·`.caps`·`.cell`): 앱 아이콘 캡슐(흰·파랑 반쪽)을 약 수만큼 칸으로 이어 붙인다.
 * 칸 색은 흰/파랑을 번갈아 쓰고 칸마다 글자 A·B·C…를 함께 둔다(색만으로 구분하지 않는다). 약을 구분하는 표지일 뿐 판정 표시가 아니다.
 */
const TONES = ["white", "blue"] as const;
const TONE_CLASS = { white: "bg-bg text-ink-2", blue: "bg-capsule-blue text-capsule-blue-ink" } as const;
const toneOf = (index: number) => TONES[index % 2];

export interface GroupTagProps {
  /** 묶음 순번(0부터) */
  index: number;
  /** 묶음 수: 맨 앞 칸은 왼쪽만, 맨 뒤 칸은 오른쪽만 둥글고 가운데 칸은 직각이다 */
  count: number;
}

/** 묶음 머리·접힌 줄 앞의 캡슐 칸 하나(높이 24px) */
export function GroupTag({ index, count }: GroupTagProps) {
  const tone = toneOf(index);
  const shape = index === 0 ? "left" : index === count - 1 ? "right" : "middle";
  return (
    <span
      data-testid="group-tag"
      data-tone={tone}
      data-shape={shape}
      className={cn(
        "inline-grid h-6 min-w-7 flex-none place-items-center border-2 border-capsule-line px-2 text-[13px] leading-none font-extrabold",
        TONE_CLASS[tone],
        shape === "left" && "rounded-l-xl",
        shape === "right" && "rounded-r-xl",
      )}
    >
      {groupLetter(index)}
    </span>
  );
}

export interface PickCapsuleProps {
  /** 묶음 순서대로, 고른 제품 이름(응답 값 그대로). 아직 고르지 않은 묶음은 `null` */
  names: readonly (string | null)[];
}

/**
 * 확인 줄의 캡슐: 칸마다 고른 약 이름을 담는다. 칸 폭은 이름 길이를 따르고 긴 이름은 칸 안에서 줄바꿈한다(말줄임 없음).
 * 고르지 않은 칸은 점선 빈 칸이다. 놓인 칸(`@container`)이 640px 미만이면 세로로 쌓고 맨 위·맨 아래 칸만 둥글다(FE-10-04 A).
 * 감싸는 쪽이 `@container`를 준다.
 */
export function PickCapsule({ names }: PickCapsuleProps) {
  return (
    <ul
      data-testid="picked-capsule"
      className="m-0 flex w-full min-w-0 list-none flex-col overflow-hidden rounded-[22px] border-2 border-capsule-line p-0 @[640px]:inline-flex @[640px]:w-auto @[640px]:max-w-full @[640px]:flex-row @[640px]:rounded-full"
    >
      {names.map((name, index) => {
        const letter = groupLetter(index);
        const tone = toneOf(index);
        return (
          <li
            key={letter}
            data-testid="capsule-cell"
            data-state={name === null ? "empty" : "picked"}
            data-tone={name === null ? undefined : tone}
            className={cn(
              "flex min-w-0 items-center gap-2 border-capsule-line px-4 py-2 text-[15px] leading-5",
              index > 0 && "border-t-2 @[640px]:border-t-0 @[640px]:border-l-2",
              name === null ? "bg-bg font-medium text-mute outline-2 outline-offset-[-6px] outline-faint outline-dashed" : cn("font-semibold", TONE_CLASS[tone]),
            )}
          >
            {name !== null && <span className="flex-none text-[13px] font-extrabold">{letter}</span>}
            <span data-slot="cell-text" className="[overflow-wrap:anywhere] [word-break:keep-all]">
              {name ?? pickPendingLabel(letter)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
