import type { Page } from "@playwright/test";

// 색 대비 측정기(FE-02 §2 RFP-24-04 "색 대비를 도구로 측정", 새 의존성 없이 시험 코드로 둔다).
// 브라우저가 실제로 그린 화면에서 글자 요소마다 계산된 글자색과 바탕색(조상 바탕을 흰 바탕 위에 차례로 겹친 색)을 읽어
// WCAG 2.x 대비비 (L1 + 0.05) / (L2 + 0.05)를 계산한다. 색 글자는 캔버스에 칠해 읽으므로 rgb()·oklch() 등 표기와 무관하다.
//
// 재는 것: 직접 글자를 가진 보이는 요소(첫 글자 줄의 가운데가 그 요소에 닿는 것만), 빈 입력창의 안내 글자(::placeholder).
// 재지 않는 것: 비활성 컨트롤(WCAG 예외), 다른 층(스크림·시트)에 덮인 글자, 화면 밖으로 스크롤된 글자, 아이콘·그림.
// 한계: 바탕은 조상 요소의 배경색만 본다(조상이 아닌 요소가 뒤에 깔린 경우·배경 그림은 `unmeasured`로 따로 알린다).

export const AA_NORMAL = 4.5;
export const AA_LARGE = 3;

export interface ContrastSample {
  /** 글자 앞부분(시험 실패 때 어느 글자인지 알아보는 용도) */
  text: string;
  testId: string | null;
  fg: string;
  bg: string;
  /** 대비비(소수 둘째 자리까지) */
  ratio: number;
  fontPx: number;
  bold: boolean;
  /** 큰 글자(24px 이상, 또는 굵은 18.66px 이상)면 기준이 3:1이다 */
  required: number;
  placeholder: boolean;
}

export interface ContrastReport {
  samples: ContrastSample[];
  /** 배경 그림 등으로 바탕색을 정할 수 없던 글자 */
  unmeasured: string[];
}

export async function measureContrast(page: Page, rootSelector = "body"): Promise<ContrastReport> {
  return page.evaluate(
    ({ rootSelector, normal, largeMin }) => {
      type Rgba = [number, number, number, number];
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 1;
      const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
      const parse = (color: string): Rgba => {
        ctx.clearRect(0, 0, 1, 1);
        ctx.fillStyle = color;
        ctx.fillRect(0, 0, 1, 1);
        const d = ctx.getImageData(0, 0, 1, 1).data;
        const a = d[3] / 255;
        // 캔버스는 알파를 곱해 저장하므로 불투명이 아니면 되돌린 값이 조금 어긋날 수 있다(불투명 색은 정확하다)
        return [d[0], d[1], d[2], a];
      };
      const over = (top: Rgba, bottom: Rgba): Rgba => {
        const a = top[3];
        return [top[0] * a + bottom[0] * (1 - a), top[1] * a + bottom[1] * (1 - a), top[2] * a + bottom[2] * (1 - a), 1];
      };
      const channel = (v: number) => {
        const s = v / 255;
        return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
      };
      const luminance = (c: Rgba) => 0.2126 * channel(c[0]) + 0.7152 * channel(c[1]) + 0.0722 * channel(c[2]);
      const ratioOf = (a: Rgba, b: Rgba) => {
        const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
        return (hi + 0.05) / (lo + 0.05);
      };
      const hex = (c: Rgba) => `#${[c[0], c[1], c[2]].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("")}`;

      /** 조상 바탕을 흰 바탕 위에 바깥부터 겹친다. 배경 그림이 끼면 null */
      const backdrop = (el: Element): Rgba | null => {
        const chain: Element[] = [];
        for (let node: Element | null = el; node; node = node.parentElement) chain.unshift(node);
        let color: Rgba = [255, 255, 255, 1];
        for (const node of chain) {
          const style = getComputedStyle(node);
          const layer = parse(style.backgroundColor);
          if (style.backgroundImage !== "none") {
            if (layer[3] < 1) return null;
          }
          if (layer[3] > 0) color = over(layer, color);
        }
        return color;
      };
      const opacityOf = (el: Element) => {
        let value = 1;
        for (let node: Element | null = el; node; node = node.parentElement) value *= Number(getComputedStyle(node).opacity);
        return value;
      };

      const root = document.querySelector(rootSelector) ?? document.body;
      const samples: ContrastSample[] = [];
      const unmeasured: string[] = [];
      const push = (el: Element, text: string, fgColor: string, placeholder: boolean) => {
        const style = getComputedStyle(el);
        const bg = backdrop(el);
        if (bg === null) {
          unmeasured.push(text.slice(0, 40));
          return;
        }
        const fgRaw = parse(fgColor);
        const fg = over([fgRaw[0], fgRaw[1], fgRaw[2], fgRaw[3] * opacityOf(el)], bg);
        const fontPx = parseFloat(style.fontSize);
        const bold = Number(style.fontWeight) >= 700;
        const large = fontPx >= 24 || (bold && fontPx >= 18.66);
        samples.push({
          text: text.slice(0, 40),
          testId: el.closest("[data-testid]")?.getAttribute("data-testid") ?? null,
          fg: hex(fg),
          bg: hex(bg),
          ratio: Math.floor(ratioOf(fg, bg) * 100) / 100,
          fontPx,
          bold,
          required: large ? largeMin : normal,
          placeholder,
        });
      };

      for (const el of root.querySelectorAll("*")) {
        if (el.closest("svg, script, style, noscript")) continue;
        if (el.closest(":disabled, [aria-disabled='true']")) continue;
        const style = getComputedStyle(el);
        if (style.display === "none" || style.visibility !== "visible") continue;
        // 빈 입력창의 안내 글자
        if ((el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement) && el.placeholder && el.value === "") {
          const rect = el.getBoundingClientRect();
          const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
          if (hit === el) push(el, el.placeholder, getComputedStyle(el, "::placeholder").color, true);
          continue;
        }
        const textNode = [...el.childNodes].find((node) => node.nodeType === Node.TEXT_NODE && (node.textContent ?? "").trim() !== "");
        if (!textNode) continue;
        const range = document.createRange();
        range.selectNodeContents(textNode);
        const rect = [...range.getClientRects()].find((r) => r.width > 1 && r.height > 1);
        if (!rect) continue; // 보이지 않는 글자(sr-only 등)
        const box = el.getBoundingClientRect();
        if (box.width <= 1 || box.height <= 1) continue;
        const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
        if (hit === null || !(hit === el || el.contains(hit))) continue; // 덮였거나 화면 밖
        push(el, (el.textContent ?? "").trim(), style.color, false);
      }
      return { samples, unmeasured };
    },
    { rootSelector, normal: AA_NORMAL, largeMin: AA_LARGE },
  );
}

/** 기준에 못 미치는 글자 */
export const failures = (report: ContrastReport) => report.samples.filter((sample) => sample.ratio < sample.required);

/** 색 쌍별 요약(같은 글자색·바탕색은 한 줄로): 보고용 */
export function summarize(report: ContrastReport) {
  const pairs = new Map<string, { fg: string; bg: string; ratio: number; required: number; count: number; example: string }>();
  for (const sample of report.samples) {
    const key = `${sample.fg}/${sample.bg}/${sample.required}`;
    const pair = pairs.get(key);
    if (pair) pair.count += 1;
    else pairs.set(key, { fg: sample.fg, bg: sample.bg, ratio: sample.ratio, required: sample.required, count: 1, example: `${sample.testId ?? "-"}: ${sample.text}` });
  }
  return [...pairs.values()].sort((a, b) => a.ratio - b.ratio);
}
