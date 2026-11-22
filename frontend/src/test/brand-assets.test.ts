import { existsSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { BRAND_ASSETS } from "@/components/brand/assets.generated";

// 브랜드 이미지 파일 점검: PNG 머리만 읽는다(크롭 도구 frontend/scripts/crop-brand.py의 결과).
const FRONTEND = path.resolve(__dirname, "../..");
const PNG_SIGNATURE = "89504e470d0a1a0a";
const COLOR_TYPE_RGBA = 6;
const MAX_BYTES = 150 * 1024;
const MAX_SIDE = 512;

function png(file: string) {
  const full = path.join(FRONTEND, file);
  expect(existsSync(full), `${file} 없음`).toBe(true);
  const head = readFileSync(full).subarray(0, 26);
  expect(head.subarray(0, 8).toString("hex")).toBe(PNG_SIGNATURE);
  expect(head.subarray(12, 16).toString("latin1")).toBe("IHDR");
  return { width: head.readUInt32BE(16), height: head.readUInt32BE(20), colorType: head[25], bytes: statSync(full).size };
}

// logo-dark: 다크 모드용 워드마크(FE-12-06 A, 갈색 글자를 흰색으로 바꾼 같은 그림)
const EXPECTED = ["mascot-question", "mascot-search", "icon-pill", "icon-pill-square", "face", "face-square", "logo", "logo-dark", "symbol"];

describe("브랜드 이미지 파일", () => {
  it("배정된 그림 8개와 다크 워드마크 1개가 크기 표에 있다", () => {
    expect(Object.keys(BRAND_ASSETS).sort()).toEqual([...EXPECTED].sort());
  });

  it.each(Object.entries(BRAND_ASSETS))("%s: 투명 PNG이고 크기 표·한계와 맞는다", (name, asset) => {
    expect(asset.src).toBe(`/brand/${name}.png`);
    const info = png(`public${asset.src}`);
    expect(info.colorType).toBe(COLOR_TYPE_RGBA);
    expect({ width: info.width, height: info.height }).toEqual({ width: asset.width, height: asset.height });
    expect(Math.max(info.width, info.height)).toBeLessThanOrEqual(MAX_SIDE);
    expect(info.bytes).toBeLessThanOrEqual(MAX_BYTES);
  });

  it.each([
    ["src/app/icon.png", 32],
    ["src/app/apple-icon.png", 180],
    ["public/brand/icon-192.png", 192],
    ["public/brand/icon-512.png", 512],
  ] as const)("%s는 정확히 %i×%i 정사각이다", (file, side) => {
    const info = png(file);
    expect({ width: info.width, height: info.height }).toEqual({ width: side, height: side });
    expect(info.colorType).toBe(COLOR_TYPE_RGBA);
    expect(info.bytes).toBeLessThanOrEqual(MAX_BYTES);
  });

  it("심볼은 로고보다 작다(글자·밑줄을 뺀 부분)", () => {
    expect(BRAND_ASSETS.symbol.width).toBeLessThan(BRAND_ASSETS.logo.width);
    expect(BRAND_ASSETS.symbol.height).toBeLessThan(BRAND_ASSETS.logo.height);
  });
});
