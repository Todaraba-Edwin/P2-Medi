import Image from "next/image";
import { cn } from "@/lib/utils";
import { BRAND_ASSETS } from "./brand/assets.generated";

const VARIANT_ASSET = {
  /** 캡슐 말풍선(큰 그림) */
  pill: "icon-pill",
  /** 파란 라운드 정사각형 안의 캡슐 말풍선(기본값) */
  square: "icon-pill-square",
} as const;

export type MedIconVariant = keyof typeof VARIANT_ASSET;

export interface MedIconProps {
  variant?: MedIconVariant;
  /** 그림 높이(px) */
  size?: number;
  className?: string;
}

/**
 * 의약품 아이콘(병아리가 아니다): 약 목록·약 항목·제품 정보 자리에 쓴다(FE-06 §3.1).
 * 마스코트가 아니므로 `NoMascotZone` 안에서도 그려진다. 장식이라 보조기기에는 읽히지 않는다.
 * 판정을 뜻하는 표지(체크·경고)처럼 보이지 않게, 배지·판정 글자 옆에 붙여 쓰지 않는다.
 */
export function MedIcon({ variant = "square", size = 24, className }: MedIconProps) {
  const asset = BRAND_ASSETS[VARIANT_ASSET[variant]];
  const width = Math.round((size * asset.width) / asset.height);
  return (
    <Image
      data-testid="med-icon"
      data-variant={variant}
      src={asset.src}
      alt=""
      aria-hidden="true"
      width={width}
      height={size}
      draggable={false}
      className={cn("block flex-none select-none", className)}
      style={{ width, height: size }}
    />
  );
}
