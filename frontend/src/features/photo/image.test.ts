import { afterEach, describe, expect, it, vi } from "vitest";
import { HEIC_MIME_TYPES, PHOTO_ACCEPT, PHOTO_JPEG_QUALITY, PHOTO_MAX_EDGE_PX, PHOTO_MAX_UPLOAD_BYTES, PhotoImageError, browserImageDeps, dataUrlBytes, isHeicFile, prepareImage } from "./image";
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
const named = (name: string, type: string) => new File([new Uint8Array([1, 2, 3])], name, { type });

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

  // ---- HEIC → JPEG 변환(BE-14-08 A, 2026-11-22). 변환기는 `ImageDeps`로 끼워 넣는다(jsdom에는 canvas가 없다)
  it.each(HEIC_MIME_TYPES)("HEIC 타입 %s은 파일을 그대로 읽지 않고 디코드해 JPEG(q0.9) data URL로 바꾼다", async (type) => {
    const fake = fakeDeps({ width: 1200, height: 900 });
    const prepared = await prepareImage(named("IMG_0001.heic", type), fake.deps);
    expect(fake.readDataUrl).not.toHaveBeenCalled();
    expect(fake.createCanvas).toHaveBeenCalledWith(1200, 900);
    expect(fake.drawImage).toHaveBeenCalledTimes(1);
    expect(fake.toDataURL).toHaveBeenCalledWith("image/jpeg", PHOTO_JPEG_QUALITY);
    expect(prepared).toMatchObject({ dataUrl: JPEG_URL, width: 1200, height: 900, resized: false, bytes: dataUrlBytes(JPEG_URL) });
    expect(fake.close).toHaveBeenCalledTimes(1);
  });

  it("타입이 비어 있어도 이름이 .heic/.HEIF면 HEIC로 보고 JPEG로 바꾼다(일부 기기는 type을 비워 보낸다)", async () => {
    for (const name of ["IMG_0002.heic", "IMG_0003.HEIF"]) {
      const fake = fakeDeps({ width: 640, height: 480 });
      const prepared = await prepareImage(named(name, ""), fake.deps);
      expect(fake.readDataUrl).not.toHaveBeenCalled();
      expect(fake.toDataURL).toHaveBeenCalledWith("image/jpeg", PHOTO_JPEG_QUALITY);
      expect(prepared.dataUrl).toBe(JPEG_URL);
    }
  });

  it("타입이 image/jpeg라도 이름이 .heic면 변환 경로로 간다(타입·확장자 중 하나라도 HEIC면 변환)", async () => {
    const fake = fakeDeps({ width: 640, height: 480 });
    await prepareImage(named("IMG_0004.heic", "image/jpeg"), fake.deps);
    expect(fake.readDataUrl).not.toHaveBeenCalled();
    expect(fake.createCanvas).toHaveBeenCalledTimes(1);
  });

  it("2800px를 넘는 HEIC는 디코드 한 번으로 줄이기와 JPEG 변환을 같이 한다(두 번 그리지 않는다)", async () => {
    const fake = fakeDeps({ width: 4032, height: 3024 });
    const prepared = await prepareImage(named("IMG_0005.heic", "image/heic"), fake.deps);
    expect(fake.createCanvas).toHaveBeenCalledTimes(1);
    expect(fake.createCanvas).toHaveBeenCalledWith(PHOTO_MAX_EDGE_PX, 2100);
    expect(fake.drawImage).toHaveBeenCalledTimes(1);
    expect(prepared).toMatchObject({ width: PHOTO_MAX_EDGE_PX, height: 2100, resized: true, dataUrl: JPEG_URL });
  });

  it("JPEG·PNG(HEIC 아님)는 그대로 통과한다: 변환하지 않고 파일 바이트를 읽는다", async () => {
    for (const [name, type] of [
      ["IMG_0006.jpg", "image/jpeg"],
      ["IMG_0007.png", "image/png"],
    ] as const) {
      const fake = fakeDeps({ width: 1000, height: 800, readUrl: type === "image/png" ? PNG_URL : JPEG_URL });
      await prepareImage(named(name, type), fake.deps);
      expect(fake.createCanvas).not.toHaveBeenCalled();
      expect(fake.readDataUrl).toHaveBeenCalledTimes(1);
    }
  });

  it("디코드하지 못하면 형식 오류(P7)다", async () => {
    const fake = fakeDeps({ width: 0, height: 0, decodeFails: true });
    await expect(prepareImage(file("image/heic"), fake.deps)).rejects.toMatchObject({ name: "PhotoImageError", kind: "format" });
    expect(fake.readDataUrl).not.toHaveBeenCalled();
  });

  it("HEIC를 디코드하지 못하는 브라우저(데스크톱 Chrome 등)는 보내지 않고 형식 오류로 떨어진다(canvas를 만들지 않는다)", async () => {
    const fake = fakeDeps({ width: 0, height: 0, decodeFails: true });
    const error = await prepareImage(named("IMG_0008.heic", "image/heic"), fake.deps).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(PhotoImageError);
    expect((error as PhotoImageError).kind).toBe("format");
    expect(fake.createCanvas).not.toHaveBeenCalled();
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

describe("isHeicFile", () => {
  it.each(["image/heic", "image/heif", "IMAGE/HEIC"])("타입 %s이면 HEIC다", (type) => {
    expect(isHeicFile(file(type))).toBe(true);
  });

  it.each(["IMG.heic", "IMG.HEIF", "a.b.heic"])("타입이 비어도 이름이 %s면 HEIC다", (name) => {
    expect(isHeicFile(named(name, ""))).toBe(true);
  });

  it.each([
    ["IMG.jpg", "image/jpeg"],
    ["IMG.png", "image/png"],
    ["IMG.heic.jpg", "image/jpeg"], // 확장자는 끝만 본다
    ["heic", ""], // 점 없는 이름
    ["IMG.webp", "image/webp"],
  ])("%s(%s)는 HEIC가 아니다", (name, type) => {
    expect(isHeicFile(named(name, type))).toBe(false);
  });

  it("이름 없는 Blob은 타입으로만 본다", () => {
    expect(isHeicFile(file("image/heic"))).toBe(true);
    expect(isHeicFile(file("image/jpeg"))).toBe(false);
  });

  it("accept 값은 JPEG·PNG에 HEIC/HEIF 타입·확장자를 더한 것이다", () => {
    expect(PHOTO_ACCEPT).toBe("image/jpeg,image/png,image/heic,image/heif,.heic,.heif");
  });
});

// ---------------------------------------------------------------- 브라우저 디코더(합성 전역: jsdom에는 createImageBitmap·object URL이 없다)
describe("browserImageDeps.decode", () => {
  class FakeImage {
    static behavior: "load" | "error" = "load";
    naturalWidth = 320;
    naturalHeight = 240;
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    set src(_value: string) {
      queueMicrotask(() => (FakeImage.behavior === "load" ? this.onload?.() : this.onerror?.()));
    }
  }
  const createObjectURL = vi.fn(() => "blob:fake");
  const revokeObjectURL = vi.fn();

  afterEach(() => {
    vi.unstubAllGlobals();
    createObjectURL.mockClear();
    revokeObjectURL.mockClear();
    FakeImage.behavior = "load";
  });

  function stubBrowser(bitmap: "ok" | "reject" | "absent") {
    vi.stubGlobal("Image", FakeImage);
    vi.stubGlobal("URL", Object.assign(Object.create(URL), { createObjectURL, revokeObjectURL }));
    if (bitmap === "absent") {
      vi.stubGlobal("createImageBitmap", undefined);
      return null;
    }
    const close = vi.fn();
    const fn = vi.fn(async () => {
      if (bitmap === "reject") throw new Error("unsupported");
      return { width: 100, height: 50, close } as unknown as ImageBitmap;
    });
    vi.stubGlobal("createImageBitmap", fn);
    return { fn, close };
  }

  it("createImageBitmap이 되면 EXIF 방향을 적용(from-image)한 비트맵을 쓴다", async () => {
    const stub = stubBrowser("ok")!;
    const decoded = await browserImageDeps.decode(file("image/jpeg"));
    expect(stub.fn).toHaveBeenCalledWith(expect.any(Blob), { imageOrientation: "from-image" });
    expect(decoded).toMatchObject({ width: 100, height: 50 });
    decoded.close?.();
    expect(stub.close).toHaveBeenCalledTimes(1);
    expect(createObjectURL).not.toHaveBeenCalled();
  });

  it("비트맵 디코더가 거부하면 <img>로 한 번 더 본다(Safari의 HEIC 경로). object URL은 놓아준다", async () => {
    stubBrowser("reject");
    const decoded = await browserImageDeps.decode(file("image/heic"));
    expect(decoded).toMatchObject({ width: 320, height: 240 });
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:fake");
  });

  it("createImageBitmap이 없으면 바로 <img>로 본다", async () => {
    stubBrowser("absent");
    await expect(browserImageDeps.decode(file("image/png"))).resolves.toMatchObject({ width: 320, height: 240 });
  });

  it("두 길 다 거부하면 거부한다(prepareImage가 format으로 바꾼다)", async () => {
    stubBrowser("reject");
    FakeImage.behavior = "error";
    await expect(browserImageDeps.decode(file("image/heic"))).rejects.toThrow();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:fake");
    await expect(prepareImage(named("IMG.heic", "image/heic"))).rejects.toMatchObject({ kind: "format" });
  });
});
