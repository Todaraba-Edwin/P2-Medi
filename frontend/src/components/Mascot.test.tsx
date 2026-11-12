import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Mascot } from "./Mascot";
import { NoMascotZone } from "./NoMascotZone";

describe("Mascot", () => {
  it("일반 영역에서는 그려진다", () => {
    render(<Mascot />);
    expect(screen.getByTestId("mascot")).toBeInTheDocument();
  });

  it.each([
    ["question", "mascot-question"],
    ["search", "mascot-search"],
    ["face", "face"],
    ["face-square", "face-square"],
  ] as const)("%s 변형은 %s 이미지를 장식으로 그린다", (variant, file) => {
    render(<Mascot variant={variant} size={80} />);
    const img = screen.getByTestId("mascot");
    expect(img.tagName).toBe("IMG");
    expect(decodeURIComponent(img.getAttribute("src") ?? "")).toContain(`/brand/${file}.png`);
    expect(img).toHaveAttribute("alt", "");
    expect(img).toHaveAttribute("aria-hidden", "true");
    expect(img).toHaveAttribute("data-variant", variant);
    expect(img.style.height).toBe("80px"); // 크기 고정
    expect(img.style.width).toMatch(/^\d+px$/);
  });

  it.each(["question", "search", "face", "face-square"] as const)("NoMascotZone 안에서는 %s 변형도 그리지 않는다", (variant) => {
    const { container } = render(
      <NoMascotZone>
        <Mascot variant={variant} />
      </NoMascotZone>,
    );
    expect(container.querySelector("img")).toBeNull();
  });

  it("NoMascotZone 안에서는 그리지 않는다", () => {
    render(
      <NoMascotZone>
        <Mascot />
      </NoMascotZone>,
    );
    expect(screen.queryByTestId("mascot")).toBeNull();
  });
});
