import { describe, expect, it, vi } from "vitest";
import { PHOTO_JPEG_QUALITY, PHOTO_MAX_EDGE_PX, PHOTO_MAX_UPLOAD_BYTES, PhotoImageError, dataUrlBytes, prepareImage } from "./image";
import type { ImageDeps } from "./image";

// 사진 준비(FE-05 `image.ts`)를 합성 canvas·디코더로 본다(jsdom에는 canvas가 없다). 실제 사진 파일은 쓰지 않는다.

const JPEG_URL = "data:image/jpeg;base64,/9j/4AAQ";
const PNG_URL = "data:image/png;base64,iVBORw0KGgo=";

function fakeDeps({ width, height, decodeFails = false, readUrl = PNG_URL }: { width: number; height: number; decodeFails?: boolean; readUrl?: string }) {
  const drawImage = vi.fn();
  const toDataURL = vi.fn(() => JPEG_URL);
  const createCanvas = vi.fn((w: number, h: number) => ({ width: w, height: h, getContext: () => ({ drawImage }), toDataURL }));
  const close = vi.fn();
  const readDataUrl = vi.fn(async () => readUrl);
  const deps: ImageDeps = {
    decode: decodeFails ? () => Promise.reject(new Error("no")) : async () => ({ width, height, source: {} as CanvasImageSource, close }),
    createCanvas,
    readDataUrl,
  };
  return { deps, drawImage, toDataURL, createCanvas, close, readDataUrl };
}

const file = (type: string) => new Blob([new Uint8Array([1, 2, 3])], { type });

describe("dataUrlBytes", () => {
  it("base64 payload를 푼 바이트 수를 센다(패딩 반영)", () => {
    expect(dataUrlBytes("data:image/png;base64,AAAA")).toBe(3);
    expect(dataUrlBytes("data:image/png;base64,AAA=")).toBe(2);
    expect(dataUrlBytes("data:image/png;base64,AA==")).toBe(1);
    expect(dataUrlBytes("nope")).toBe(0);
  });
});

describe("prepareImage", () => {
  it("긴 변이 2800px를 넘으면 canvas로 2800에 맞춰 줄이고 JPEG q0.9로 바꾼다", async () => {
    const fake = fakeDeps({ width: 4000, height: 3000 });
    const prepared = await prepareImage(file("image/jpeg"), fake.deps);
    expect(fake.createCanvas).toHaveBeenCalledWith(PHOTO_MAX_EDGE_PX, 2100);
    expect(fake.drawImage).toHaveBeenCalledWith(expect.anything(), 0, 0, PHOTO_MAX_EDGE_PX, 2100);
    expect(fake.toDataURL).toHaveBeenCalledWith("image/jpeg", PHOTO_JPEG_QUALITY);
    expect(prepared).toMatchObject({ dataUrl: JPEG_URL, width: PHOTO_MAX_EDGE_PX, height: 2100, resized: true });
    expect(fake.readDataUrl).not.toHaveBeenCalled();
    expect(fake.close).toHaveBeenCalledTimes(1); // 비트맵을 놓아준다
  });

  it("세로가 긴 사진도 긴 변 기준으로 줄인다", async () => {
    const fake = fakeDeps({ width: 1500, height: 5600 });
    const prepared = await prepareImage(file("image/png"), fake.deps);
    expect(fake.createCanvas).toHaveBeenCalledWith(750, PHOTO_MAX_EDGE_PX);
    expect(prepared.resized).toBe(true);
  });

  it("2800px 이하의 JPEG·PNG는 줄이지 않고 파일을 그대로 data URL로 읽는다", async () => {
    const fake = fakeDeps({ width: 2800, height: 1800 });
    const prepared = await prepareImage(file("image/png"), fake.deps);
    expect(fake.createCanvas).not.toHaveBeenCalled();
    expect(fake.readDataUrl).toHaveBeenCalledTimes(1);
    expect(prepared).toMatchObject({ dataUrl: PNG_URL, width: 2800, height: 1800, resized: false, bytes: dataUrlBytes(PNG_URL) });
  });

  it("JPEG·PNG가 아닌 파일(HEIC 등)은 브라우저가 디코드하면 canvas로 JPEG로 바꾼다", async () => {
    const fake = fakeDeps({ width: 800, height: 600 });
    const prepared = await prepareImage(file("image/heic"), fake.deps);
    expect(fake.createCanvas).toHaveBeenCalledWith(800, 600);
    expect(prepared).toMatchObject({ dataUrl: JPEG_URL, resized: false });
  });

  it("디코드하지 못하면 형식 오류(P7)다", async () => {
    const fake = fakeDeps({ width: 0, height: 0, decodeFails: true });
    await expect(prepareImage(file("image/heic"), fake.deps)).rejects.toMatchObject({ name: "PhotoImageError", kind: "format" });
    expect(fake.readDataUrl).not.toHaveBeenCalled();
  });

  it("8MB를 넘으면 보내지 않는다(too_large)", async () => {
    // 8MB + 3바이트를 담은 base64 payload(4자당 3바이트)
    const payload = "A".repeat(((PHOTO_MAX_UPLOAD_BYTES + 3) / 3) * 4);
    const fake = fakeDeps({ width: 1000, height: 1000, readUrl: `data:image/jpeg;base64,${payload}` });
    const error = await prepareImage(file("image/jpeg"), fake.deps).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(PhotoImageError);
    expect((error as PhotoImageError).kind).toBe("too_large");
  });

  it("읽은 결과가 JPEG·PNG data URL이 아니면 형식 오류다", async () => {
    const fake = fakeDeps({ width: 100, height: 100, readUrl: "data:image/gif;base64,R0lGOD" });
    await expect(prepareImage(file("image/png"), fake.deps)).rejects.toMatchObject({ kind: "format" });
  });
});
