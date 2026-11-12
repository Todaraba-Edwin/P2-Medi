import Image from "next/image";
import { notFound } from "next/navigation";
import { BRAND_ASSETS } from "@/components/brand/assets.generated";
import { BrandLogo } from "@/components/BrandLogo";
import { BrandWordmark } from "@/components/BrandWordmark";
import { Mascot } from "@/components/Mascot";
import { MedIcon } from "@/components/MedIcon";
import { NoMascotZone } from "@/components/NoMascotZone";

// 개발 전용 미리보기(브랜드 이미지). 운영 빌드에서는 404.
// 투명 처리·테두리 할로·잘림을 배경 4종 위에서 눈으로 보려는 용도다.
const BACKGROUNDS = [
  { name: "흰 배경", className: "bg-bg text-ink" },
  { name: "옅은 노랑(bg-soft)", className: "bg-bg-soft text-ink" },
  { name: "강조 바탕(tint)", className: "bg-tint text-ink" },
  { name: "어두운 배경", className: "bg-ink text-bg" },
] as const;

const ICON_FILES = [
  { src: "/icon.png", size: 32, label: "favicon 32" },
  { src: "/apple-icon.png", size: 180, label: "apple 180" },
  { src: "/brand/icon-192.png", size: 192, label: "192" },
  { src: "/brand/icon-512.png", size: 512, label: "512(절반 크기로 표시)" },
] as const;

function Cell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <figure className="m-0 flex flex-col items-center gap-1">
      {children}
      <figcaption className="text-[11px] opacity-70">{label}</figcaption>
    </figure>
  );
}

export default function BrandPreviewPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return (
    <main className="flex flex-col gap-4 p-4">
      <h1 className="text-lg font-bold">브랜드 이미지</h1>

      {BACKGROUNDS.map((background) => (
        <section key={background.name} data-testid="brand-row" className={`flex flex-col gap-3 rounded-xl p-4 ${background.className}`}>
          <h2 className="m-0 text-sm font-bold">{background.name}</h2>
          <div className="flex flex-wrap items-end gap-5">
            <Cell label="Mascot question 150">
              <Mascot variant="question" size={150} />
            </Cell>
            <Cell label="Mascot search 150">
              <Mascot variant="search" size={150} />
            </Cell>
            <Cell label="Mascot search 72">
              <Mascot variant="search" size={72} />
            </Cell>
            <Cell label="Mascot face 72">
              <Mascot variant="face" size={72} />
            </Cell>
            <Cell label="Mascot face-square 72">
              <Mascot variant="face-square" size={72} />
            </Cell>
            <Cell label="Mascot question 32">
              <Mascot variant="question" size={32} />
            </Cell>
            <Cell label="MedIcon pill 72">
              <MedIcon variant="pill" size={72} />
            </Cell>
            <Cell label="MedIcon square 72">
              <MedIcon variant="square" size={72} />
            </Cell>
            <Cell label="MedIcon pill 24">
              <MedIcon variant="pill" size={24} />
            </Cell>
            <Cell label="MedIcon square 24">
              <MedIcon variant="square" size={24} />
            </Cell>
            <Cell label="BrandLogo 34">
              <span className="text-3xl font-extrabold">
                <BrandLogo size={34} />
              </span>
            </Cell>
            <Cell label="BrandLogo 20">
              <span className="text-base font-bold">
                <BrandLogo size={20} />
              </span>
            </Cell>
            <Cell label="BrandWordmark 100">
              <BrandWordmark size={100} />
            </Cell>
            <Cell label="BrandWordmark 50">
              <BrandWordmark size={50} />
            </Cell>
          </div>
        </section>
      ))}

      <section className="flex flex-col gap-3 rounded-xl border border-line p-4">
        <h2 className="m-0 text-sm font-bold">원본 크기(자른 그대로)</h2>
        <div className="flex flex-wrap items-end gap-5">
          {Object.entries(BRAND_ASSETS).map(([name, asset]) => (
            <Cell key={name} label={`${name} ${asset.width}×${asset.height}`}>
              <Image src={asset.src} alt="" width={asset.width} height={asset.height} unoptimized className="h-auto max-w-full" />
            </Cell>
          ))}
        </div>
      </section>

      <section className="flex flex-col gap-3 rounded-xl border border-line p-4">
        <h2 className="m-0 text-sm font-bold">favicon·앱 아이콘(로고 심볼만)</h2>
        {[{ name: "밝은 탭", className: "bg-bg-soft" }, { name: "어두운 탭", className: "bg-ink text-bg" }].map((tab) => (
          <div key={tab.name} className={`flex flex-wrap items-end gap-5 rounded-lg p-3 ${tab.className}`}>
            <span className="text-xs">{tab.name}</span>
            {ICON_FILES.map((icon) => {
              const shown = icon.size > 256 ? icon.size / 2 : icon.size;
              return (
                <Cell key={icon.src} label={icon.label}>
                  <Image src={icon.src} alt="" width={shown} height={shown} unoptimized />
                </Cell>
              );
            })}
          </div>
        ))}
      </section>

      <section className="flex flex-col gap-2 rounded-xl border border-line p-4">
        <h2 className="m-0 text-sm font-bold">마스코트 금지 영역(NoMascotZone)</h2>
        <p className="m-0 text-xs text-mute">아래 상자 안에는 마스코트가 그려지지 않고 의약품 아이콘만 보여야 한다.</p>
        <NoMascotZone>
          <div data-testid="no-mascot-demo" className="flex min-h-12 items-center gap-3 rounded-lg bg-fixed p-3">
            <Mascot variant="question" size={48} />
            <Mascot variant="search" size={48} />
            <Mascot variant="face" size={48} />
            <MedIcon variant="square" size={32} />
            <MedIcon variant="pill" size={32} />
          </div>
        </NoMascotZone>
      </section>
    </main>
  );
}
