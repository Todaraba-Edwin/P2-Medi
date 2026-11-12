import { Mascot } from "@/components/Mascot";
import { APP_NAME, APP_NAME_KO, HERO_TAGLINE } from "./copy";

/** 시작 화면 머리. 마스코트 허용 자리다(PRD-06-02). 로고·마스코트 이미지는 FE-06 확정 뒤 연결한다. */
export function HomeHero() {
  return (
    <div className="flex flex-col items-center gap-1.5 text-center">
      <Mascot className="block h-24 w-24" />
      <h1 className="m-0 text-3xl leading-tight font-extrabold">
        {APP_NAME} <span className="text-xl font-bold text-ink-2">{APP_NAME_KO}</span>
      </h1>
      <p className="mt-1.5 mb-0 text-base text-mute">{HERO_TAGLINE}</p>
    </div>
  );
}
