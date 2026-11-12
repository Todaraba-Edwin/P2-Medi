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
 */
export function BrandWordmark({ size = 50, className }: BrandWordmarkProps) {
  const asset = BRAND_ASSETS.logo;
  const width = Math.round((size * asset.width) / asset.height);
  return (
    <Image
      data-testid="brand-wordmark"
      src={asset.src}
      alt={BRAND_NAME}
      width={width}
      height={size}
      draggable={false}
      className={cn("block flex-none select-none", className)}
      style={{ width, height: size }}
    />
  );
}
