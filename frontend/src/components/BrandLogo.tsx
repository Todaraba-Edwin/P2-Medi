import Image from "next/image";
import { cn } from "@/lib/utils";
import { BRAND_ASSETS } from "./brand/assets.generated";
import { BRAND_NAME } from "./brand/name";

export interface BrandLogoProps {
  /** 심볼 높이(px) */
  size?: number;
  className?: string;
}

/**
 * 로고: 캡슐 말풍선 심볼(병아리 없음, FE-06-01 A) + 서비스 이름 글자.
 * 이름은 이미지가 아니라 글자다(접근성·번역·깨짐 방지). 글자 크기·굵기는 감싸는 쪽이 정한다.
 * 화면 머리·시작 화면 상단에 쓴다.
 */
export function BrandLogo({ size = 28, className }: BrandLogoProps) {
  const asset = BRAND_ASSETS.symbol;
  const width = Math.round((size * asset.width) / asset.height);
  return (
    <span data-testid="brand-logo" className={cn("inline-flex items-center gap-2 align-middle", className)}>
      <Image
        src={asset.src}
        alt=""
        aria-hidden="true"
        width={width}
        height={size}
        draggable={false}
        className="block flex-none select-none"
        style={{ width, height: size }}
      />
      <span>{BRAND_NAME}</span>
    </span>
  );
}
