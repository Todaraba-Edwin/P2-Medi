import { BrandLogo } from "@/components/BrandLogo";
import { Mascot } from "@/components/Mascot";
import { APP_NAME_KO, HERO_TAGLINE } from "./copy";

/** 시작 화면 머리. 마스코트 허용 자리다(PRD-06-02): 질문 병아리(컷 A) + 로고(심볼 + 이름 글자). */
export function HomeHero() {
  return (
    <div className="flex flex-col items-center gap-1.5 text-center">
      <Mascot variant="question" size={150} eager />
      <h1 className="m-0 text-3xl leading-tight font-extrabold">
        <BrandLogo size={34} /> <span className="text-xl font-bold text-ink-2">{APP_NAME_KO}</span>
      </h1>
      <p className="mt-1.5 mb-0 text-base text-mute">{HERO_TAGLINE}</p>
    </div>
  );
}
