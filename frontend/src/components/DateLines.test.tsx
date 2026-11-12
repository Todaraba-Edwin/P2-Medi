import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { DateLine } from "@/lib/api";
import { DateLines } from "./DateLines";

const dates: DateLine[] = [
  { label: "고시일", value: "2026-01-15" },
  { label: "고시일", value: "2025-03-02" },
  { label: "발간일", value: "2026-06" },
  { label: "기준일", value: "2026-07-31" },
  { label: "조회", value: "2026-11-12" },
];

describe("DateLines", () => {
  it("한 항목이 한 줄이고 받은 순서 그대로다", () => {
    render(<DateLines dates={dates} />);
    const lines = screen.getAllByRole("listitem");
    expect(lines).toHaveLength(dates.length);
    expect(lines.map((li) => [...li.children].map((c) => c.textContent))).toEqual(dates.map((d) => [d.label, d.value]));
  });

  it("라벨과 값을 따로 그리고 글자를 조립하지 않는다(값은 받은 그대로, 월 단위도 그대로)", () => {
    render(<DateLines dates={dates} />);
    expect(screen.getByText("2026-06")).toBeInTheDocument();
    expect(screen.queryByText(/2026-06-/)).toBeNull();
    expect(screen.queryByText(/\d+\s*(년|월|일)/)).toBeNull(); // 날짜 형식을 바꿔 쓰지 않는다
    for (const li of screen.getAllByRole("listitem")) expect(li).toHaveClass("whitespace-nowrap");
  });

  it("'날짜 없음'은 라벨만 보인다", () => {
    render(<DateLines dates={[{ label: "날짜 없음", value: null }]} />);
    const line = screen.getByRole("listitem");
    expect(line.children).toHaveLength(1);
    expect(line).toHaveTextContent("날짜 없음");
  });

  it("줄이 없으면 아무것도 그리지 않는다", () => {
    const { container } = render(<DateLines dates={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
