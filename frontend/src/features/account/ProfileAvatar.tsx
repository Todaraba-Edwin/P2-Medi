"use client";

import { Mascot } from "@/components/Mascot";
import type { AvatarColor } from "@/lib/api/account";
import { cn } from "@/lib/utils";

/** 색 키 → 배경 토큰 클래스(globals.css `--color-avatar-*`, 라이트·다크 값이 따로 있다). Tailwind가 찾도록 글자 그대로 둔다 */
const AVATAR_BG: Readonly<Record<AvatarColor, string>> = {
  yellow: "bg-avatar-yellow",
  coral: "bg-avatar-coral",
  pink: "bg-avatar-pink",
  purple: "bg-avatar-purple",
  blue: "bg-avatar-blue",
  teal: "bg-avatar-teal",
  green: "bg-avatar-green",
  gray: "bg-avatar-gray",
};

export interface ProfileAvatarProps {
  color: AvatarColor;
  /** 원 지름(px) */
  size?: number;
  /** false면 병아리 없이 색 원만(119 안내가 떠 있는 계정 모달처럼 마스코트를 숨기는 자리) */
  face?: boolean;
  className?: string;
}

/**
 * 프로필 아바타(2026-11-23): 프로필 색 원 + 병아리 얼굴(기존 자산 `public/brand/face.png`, `Mascot` variant `face`).
 * 마스코트 규칙(PRD-06-02·03)은 `Mascot`이 지킨다: 마스코트 금지 영역(`NoMascotZone`) 안에서는 병아리가 빠지고 색 원만 남는다.
 * 계정 버튼·입력창 프로필 칩·프로필 목록·프로필 폼 같은 보조 자리에만 둔다. 장식이라 보조기기에는 읽히지 않는다(이름은 옆 글자가 말한다)
 */
export function ProfileAvatar({ color, size = 28, face = true, className }: ProfileAvatarProps) {
  return (
    <span
      data-testid="profile-avatar"
      data-color={color}
      aria-hidden="true"
      className={cn("grid flex-none place-items-center overflow-hidden rounded-full", AVATAR_BG[color], className)}
      style={{ width: size, height: size }}
    >
      {face && <Mascot variant="face" size={Math.round(size * 0.6)} />}
    </span>
  );
}
