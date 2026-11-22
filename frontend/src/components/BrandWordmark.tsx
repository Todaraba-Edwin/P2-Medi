import Image from "next/image";
import { cn } from "@/lib/utils";
import { BRAND_ASSETS } from "./brand/assets.generated";
import { BRAND_NAME } from "./brand/name";

export interface BrandWordmarkProps {
  /** 그림 높이(px) */
  size?: number;
  className?: string;
}

/**
 * 워드마크: 글자가 그림 안에 들어 있는 로고 이미지 전체.
 * **정적 브랜딩 자리에만** 쓴다(여는 화면·소개 등). 응급·금기 결과·고정 문구 화면과 화면 머리에는 쓰지 않는다
 * (그 자리의 이름은 `BrandLogo`의 글자다, FE-06 §3.1 글자 예외).
 * 다크 모드(FE-12-06 A)에서는 글자가 흰색인 `logo-dark`를 겹쳐 두고 투명도로 바꾼다. 두 그림 모두 레이아웃에 있어
 * 늦게 받는 그림 점검이 멈추지 않고, 보조기기에는 `BRAND_NAME` 글자 한 번만 읽힌다(다크 그림은 장식).
 */
export function BrandWordmark({ size = 50, className }: BrandWordmarkProps) {
  const light = BRAND_ASSETS.logo;
  const dark = BRAND_ASSETS["logo-dark"];
  const width = Math.round((size * light.width) / light.height);
  const frame = { width, height: size, draggable: false, style: { width, height: size } } as const;
  return (
    <span className={cn("relative inline-block flex-none align-middle", className)} style={{ width, height: size }}>
      <Image
        data-testid="brand-wordmark"
        src={light.src}
        alt={BRAND_NAME}
        {...frame}
        className="block h-full w-full select-none dark:opacity-0"
      />
      <Image
        data-testid="brand-wordmark-dark"
        src={dark.src}
        alt=""
        aria-hidden="true"
        // 숨겨진 동안에도 미리 받아 둔다(다크로 바뀔 때 깜빡이지 않게)
        loading="eager"
        {...frame}
        className="absolute inset-0 h-full w-full select-none opacity-0 dark:opacity-100"
      />
    </span>
  );
}
