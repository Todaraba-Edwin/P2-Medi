import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Mascot } from "@/components/Mascot";
import { PHRASES } from "@/mocks/fixtures/phrases";
import * as fixtures from "@/mocks/fixtures/responses";
import { EmergencySlot } from "../chat/EmergencySlot";
import * as copy from "./copy";
import { EmergencyBanner } from "./EmergencyBanner";
import { FixedNoticeBox } from "./FixedNoticeBox";
import { LegalFooter } from "./LegalFooter";
import { PharmacistAdviceBox } from "./PharmacistAdviceBox";

const COLLAPSIBLE = "details, [hidden], [aria-hidden='true'], [data-state='closed'], [role='dialog']";

describe("EmergencyBanner", () => {
  const emergency = fixtures.emergencyResponse.emergency!;

  it("role=alert, 글자는 응답 값 그대로, 전화 링크는 tel:119다", () => {
    render(<EmergencyBanner emergency={emergency} />);
    const alert = screen.getByRole("alert");
    expect(within(alert).getByText(PHRASES.EMERGENCY_119).textContent).toBe(emergency.text);
    const link = within(alert).getByRole("link", { name: copy.EMERGENCY_CALL_LABEL });
    expect(link).toHaveAttribute("href", "tel:119");
    expect(emergency.tel).toBe("tel:119"); // 응답의 값과 링크 주소가 같다
    expect(link).toHaveClass("min-h-11"); // 터치 44px
  });

  it("받은 문구가 달라도 그대로 그린다(프런트가 문구를 갖지 않는다)", () => {
    render(<EmergencyBanner emergency={{ text: "받은 응급 문구 그대로", tel: "tel:119", wide_text: "받은 보조 문장 그대로" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("받은 응급 문구 그대로");
    expect(JSON.stringify(copy)).not.toContain("응급");
  });

  it("마스코트·이미지·소리 요소가 없고, 안에 마스코트를 넣어도 그려지지 않는다", () => {
    const { container } = render(<EmergencyBanner emergency={emergency} />);
    expect(container.querySelector("img, audio")).toBeNull();
    expect(screen.queryByTestId("mascot")).toBeNull();
  });

  it("EmergencySlot과 같은 props라 그대로 바꿔 끼울 수 있다", () => {
    const props: Parameters<typeof EmergencySlot>[0] = { emergency };
    const { unmount } = render(<EmergencyBanner {...props} />);
    const banner = screen.getByRole("alert").textContent;
    unmount();
    render(<EmergencySlot {...props} />);
    expect(screen.getByRole("alert").textContent).toContain(emergency.text);
    expect(banner).toContain(emergency.text);
  });
});

describe("FixedNoticeBox", () => {
  it("줄을 받은 순서 그대로, 받은 글자 그대로 그린다(권고 → 고정)", () => {
    const lines = fixtures.adviceFirstResponse.fixed_notice;
    render(<FixedNoticeBox lines={lines} />);
    const box = screen.getByRole("note");
    expect([...box.querySelectorAll("p")].map((p) => p.textContent)).toEqual(lines);
    expect(lines).toHaveLength(2);
  });

  it("순서를 정하지 않는다: 뒤집어 줘도 뒤집힌 그대로 그린다", () => {
    const reversed = [...fixtures.adviceFirstResponse.fixed_notice].reverse();
    render(<FixedNoticeBox lines={reversed} />);
    expect([...screen.getByRole("note").querySelectorAll("p")].map((p) => p.textContent)).toEqual(reversed);
  });

  it("접히는 요소가 아니고 링크·마스코트가 없다(약국·약사는 글자만)", () => {
    const { container } = render(<FixedNoticeBox lines={fixtures.foundResponse.fixed_notice} />);
    const box = screen.getByTestId("fixed-notice");
    expect(box).toBeVisible();
    expect(box.closest(COLLAPSIBLE)).toBeNull();
    expect(container.querySelector("a, button, details, img")).toBeNull();
    expect(box.textContent).toContain("약국·약사");
  });

  it("FixedNoticeBox 안에서는 마스코트가 그려지지 않는다(NoMascotZone)", () => {
    // 부품이 자식을 받지 않으므로 같은 금지 영역 규칙을 쓰는지만 본다
    render(<FixedNoticeBox lines={["받은 줄"]} />);
    expect(screen.queryByTestId("mascot")).toBeNull();
    render(<Mascot />);
    expect(screen.getAllByTestId("mascot")).toHaveLength(1); // 밖에서는 그려진다
  });
});

describe("PharmacistAdviceBox", () => {
  const line = "복용 전에 꼭 약국·약사에게 가나다정을(를) 함께 먹어도 되는지 물어보세요. 비어 있다고 괜찮다는 뜻이 아니에요.";

  it("줄을 받은 글자 그대로 그리고 첫 문장만 굵게 쓴다", () => {
    render(<PharmacistAdviceBox lines={[line, PHRASES.PHARMACIST_ADVICE_FIXED]} />);
    const paragraphs = [...screen.getByTestId("pharmacist-advice").querySelectorAll("p")];
    expect(paragraphs.map((p) => p.textContent)).toEqual([line, PHRASES.PHARMACIST_ADVICE_FIXED]);
    expect(paragraphs[0].querySelector("b")?.textContent).toBe("복용 전에 꼭 약국·약사에게 가나다정을(를) 함께 먹어도 되는지 물어보세요.");
    expect(paragraphs[1].querySelector("b")?.textContent).toBe("확인하지 못한 항목이 있어요.");
  });

  it("마침표가 없는 줄은 통째로 굵게 쓰고 글자를 바꾸지 않는다", () => {
    render(<PharmacistAdviceBox lines={["받은 권고 줄 마침표 없음"]} />);
    const p = screen.getByTestId("pharmacist-advice").querySelector("p")!;
    expect(p.textContent).toBe("받은 권고 줄 마침표 없음");
    expect(p.querySelector("b")?.textContent).toBe("받은 권고 줄 마침표 없음");
  });

  it("접히는 요소가 아니고 마스코트·'삐!'·링크가 없으며, 줄이 없으면 그리지 않는다", () => {
    const { container, rerender } = render(<PharmacistAdviceBox lines={[line]} />);
    const box = screen.getByRole("note");
    expect(box.closest(COLLAPSIBLE)).toBeNull();
    expect(container.querySelector("a, button, details, img")).toBeNull();
    expect(container.textContent).not.toContain("삐!");
    rerender(<PharmacistAdviceBox lines={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("LegalFooter", () => {
  it("고지를 받은 그대로 그린다", () => {
    render(<LegalFooter disclaimer={fixtures.foundResponse.disclaimer} />);
    expect(screen.getByTestId("legal-footer").textContent).toBe(fixtures.foundResponse.disclaimer);
    render(<LegalFooter disclaimer="받은 고지 글자" />);
    expect(screen.getByText("받은 고지 글자")).toBeInTheDocument();
  });
});

describe("copy.ts", () => {
  it("안내 문장이 없다(주소와 동작 이름뿐)", () => {
    expect(copy.EMERGENCY_TEL_HREF).toBe("tel:119");
    expect(Object.keys(copy).sort()).toEqual(["EMERGENCY_CALL_LABEL", "EMERGENCY_TEL_HREF"]);
    expect(JSON.stringify(copy)).not.toMatch(/안전|약국|약사|금기|단계/);
  });
});

describe("EmergencyBanner 넓은 폭 보조 문장(FE-07-15)", () => {
  it("보조 문장은 받은 글자 그대로이고 넓은 폭에서만 보이게 표시한다(좁은 폭에서는 숨김)", () => {
    render(<EmergencyBanner emergency={{ text: "받은 응급 문구", tel: "tel:119", wide_text: "받은 보조 문장 그대로" }} />);
    const wide = screen.getByTestId("emergency-wide");
    expect(wide.textContent).toBe("받은 보조 문장 그대로");
    expect(wide.className).toContain("hidden");
    expect(wide.className).toContain("lg:block");
    expect(screen.getAllByRole("link")).toHaveLength(1); // 보조 문장은 연락처가 아니다: 전화 링크는 하나뿐
    expect(JSON.stringify(copy)).not.toContain("휴대폰");
  });
});
