"use client";

import Image from "next/image";
import { cn } from "@/lib/utils";
import { BRAND_ASSETS } from "./brand/assets.generated";
import { useInNoMascotZone } from "./NoMascotZone";

const VARIANT_ASSET = {
  /** 약을 든 채 갸웃하는 병아리: 시작 화면, 되묻기(작게) */
  question: "mascot-question",
  /** 돋보기를 든 병아리: 진행 표시, 빈 상태·오류 */
  search: "mascot-search",
  /** 병아리 얼굴: 프로필 기본 이미지(FE-04) */
  face: "face",
  "face-square": "face-square",
} as const;

export type MascotVariant = keyof typeof VARIANT_ASSET;

export interface MascotProps {
  variant?: MascotVariant;
  /** 그림 높이(px). 너비는 그림 비율로 정한다 */
  size?: number;
  /** 첫 화면에 바로 보이는 큰 그림이면 true(늦게 불러오지 않는다) */
  eager?: boolean;
  className?: string;
}

/**
 * 병아리 마스코트(보조 자리 전용, PRD-06-02). 장식이라 보조기기에는 읽히지 않는다.
 * 응급·금기 결과·"목록에 없음"·고정 문구 영역(`NoMascotZone`) 안에서는 그리지 않는다.
 * 크기를 고정해 이미지를 불러오지 못해도 배치가 흔들리지 않는다.
 */
export function Mascot({ variant = "question", size = 96, eager = false, className }: MascotProps) {
  if (useInNoMascotZone()) return null;
  const asset = BRAND_ASSETS[VARIANT_ASSET[variant]];
  const width = Math.round((size * asset.width) / asset.height);
  return (
    <Image
      data-testid="mascot"
      data-variant={variant}
      src={asset.src}
      alt=""
      aria-hidden="true"
      width={width}
      height={size}
      loading={eager ? "eager" : "lazy"}
      draggable={false}
      className={cn("block flex-none select-none", className)}
      style={{ width, height: size }}
    />
  );
}
