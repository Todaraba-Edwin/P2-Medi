import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BrandLogo } from "./BrandLogo";
import { BrandWordmark } from "./BrandWordmark";
import { MedIcon } from "./MedIcon";
import { NoMascotZone } from "./NoMascotZone";

const src = (el: Element) => decodeURIComponent(el.getAttribute("src") ?? "");

describe("BrandLogo", () => {
  it("심볼은 장식 이미지이고 서비스 이름은 글자다", () => {
    render(<BrandLogo />);
    const logo = screen.getByTestId("brand-logo");
    expect(logo).toHaveTextContent("Can I PPiyak");
    const img = logo.querySelector("img") as HTMLImageElement;
    expect(src(img)).toContain("/brand/symbol.png");
    expect(img).toHaveAttribute("alt", "");
    expect(img).toHaveAttribute("aria-hidden", "true");
    expect(screen.queryByRole("img")).toBeNull(); // 보조기기에는 글자만 읽힌다
  });
});

describe("BrandWordmark", () => {
  it("글자가 든 로고 이미지 전체이고 alt는 서비스 이름이다", () => {
    render(<BrandWordmark />);
    const img = screen.getByRole("img", { name: "Can I PPiyak" });
    expect(src(img)).toContain("/brand/logo.png");
  });
});

describe("MedIcon", () => {
  it.each([
    ["pill", "icon-pill"],
    ["square", "icon-pill-square"],
  ] as const)("%s 변형은 %s 이미지를 장식으로 그린다", (variant, file) => {
    render(<MedIcon variant={variant} />);
    const img = screen.getByTestId("med-icon");
    expect(src(img)).toContain(`/brand/${file}.png`);
    expect(img).toHaveAttribute("alt", "");
    expect(img).toHaveAttribute("aria-hidden", "true");
  });

  it("병아리가 아니므로 NoMascotZone 안에서도 그려진다", () => {
    render(
      <NoMascotZone>
        <MedIcon />
      </NoMascotZone>,
    );
    expect(screen.getByTestId("med-icon")).toBeInTheDocument();
    expect(src(screen.getByTestId("med-icon"))).not.toMatch(/mascot|face/);
  });
});
