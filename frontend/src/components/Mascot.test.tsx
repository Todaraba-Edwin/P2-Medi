import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Mascot } from "./Mascot";
import { NoMascotZone } from "./NoMascotZone";

describe("Mascot", () => {
  it("일반 영역에서는 그려진다", () => {
    render(<Mascot />);
    expect(screen.getByTestId("mascot")).toBeInTheDocument();
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
