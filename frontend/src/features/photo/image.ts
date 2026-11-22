// 사진 준비(FE-05): 브라우저 메모리에서만 한다. 파일·data URL을 `localStorage`·IndexedDB·쿠키에 넣지 않고, 서버로 보낸 뒤에는 부르는 쪽이 참조를 버린다.
// - 긴 변이 2800px를 넘으면 canvas로 2800에 맞춰 줄이고 JPEG(q0.9)로 바꾼다(업로드 크기를 줄인다. 서버는 다시 1400px로 맞춘다, 〔D2〕A)
// - JPEG·PNG가 아닌 파일(HEIC 등)은 브라우저가 디코드할 수 있으면 JPEG로 바꾸고, 못 하면 형식 안내(P7)
// - 서버 상한 8MB보다 크면 보내지 않는다(P7)
// 디코드·canvas·파일 읽기는 끼워 넣을 수 있게 둔다(`ImageDeps`): jsdom에는 canvas가 없어 시험은 합성 구현으로 돈다.

export const PHOTO_MAX_EDGE_PX = 2800;
export const PHOTO_JPEG_QUALITY = 0.9;
/** 서버 상한(BE 지시서 §3 2번 "디코드 뒤 8MB 이하")과 같은 값 */
export const PHOTO_MAX_UPLOAD_BYTES = 8 * 1024 * 1024;
/** `<input type="file" accept>` 값. 카메라·앨범은 브라우저가 고른다 */
export const PHOTO_ACCEPT = "image/jpeg,image/png";
const DATA_URL_HEAD = /^data:image\/(jpeg|png);base64,/;

export type PhotoImageErrorKind = "format" | "too_large";

/** 사진을 보낼 수 없는 이유. 파일 이름·내용은 싣지 않는다 */
export class PhotoImageError extends Error {
  constructor(readonly kind: PhotoImageErrorKind) {
    super(`photo image ${kind}`);
    this.name = "PhotoImageError";
  }
}

export interface DecodedImage {
  width: number;
  height: number;
  /** canvas에 그릴 원본 */
  source: CanvasImageSource;
  /** 디코드한 비트맵을 놓아줄 때 */
  close?: () => void;
}

export interface CanvasLike {
  getContext(type: "2d"): { drawImage(source: CanvasImageSource, dx: number, dy: number, dw: number, dh: number): void } | null;
  toDataURL(type: string, quality?: number): string;
}

export interface ImageDeps {
  decode: (file: Blob) => Promise<DecodedImage>;
  createCanvas: (width: number, height: number) => CanvasLike;
  readDataUrl: (file: Blob) => Promise<string>;
}

export interface PreparedImage {
  /** `data:image/jpeg;base64,…` 또는 `data:image/png;base64,…` */
  dataUrl: string;
  width: number;
  height: number;
  /** 2800px 초과라 줄였는가 */
  resized: boolean;
  /** 보낼 바이트 수(base64를 푼 크기) */
  bytes: number;
}

/** base64 data URL이 담은 바이트 수 */
export function dataUrlBytes(dataUrl: string): number {
  const at = dataUrl.indexOf(",");
  const payload = at < 0 ? "" : dataUrl.slice(at + 1);
  const padding = payload.endsWith("==") ? 2 : payload.endsWith("=") ? 1 : 0;
  return Math.max(0, Math.floor((payload.length * 3) / 4) - padding);
}

const decodeInBrowser = async (file: Blob): Promise<DecodedImage> => {
  if (typeof createImageBitmap === "function") {
    const bitmap = await createImageBitmap(file);
    return { width: bitmap.width, height: bitmap.height, source: bitmap, close: () => bitmap.close() };
  }
  const url = URL.createObjectURL(file);
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const element = new Image();
      element.onload = () => resolve(element);
      element.onerror = () => reject(new Error("decode"));
      element.src = url;
    });
    return { width: image.naturalWidth, height: image.naturalHeight, source: image };
  } finally {
    URL.revokeObjectURL(url);
  }
};

const readDataUrlInBrowser = (file: Blob) =>
  new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(typeof reader.result === "string" ? reader.result : "");
    reader.onerror = () => reject(new Error("read"));
    reader.readAsDataURL(file);
  });

export const browserImageDeps: ImageDeps = {
  decode: decodeInBrowser,
  createCanvas: (width, height) => {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    return canvas;
  },
  readDataUrl: readDataUrlInBrowser,
};

/**
 * 파일을 보낼 모양(data URL)으로 만든다. 디코드할 수 없으면 `format`, 상한을 넘으면 `too_large`를 던진다.
 * 돌려준 data URL은 요청에 쓰고 바로 버린다(상태·저장소에 두지 않는다).
 */
export async function prepareImage(file: Blob, deps: ImageDeps = browserImageDeps): Promise<PreparedImage> {
  let decoded: DecodedImage;
  try {
    decoded = await deps.decode(file);
  } catch {
    throw new PhotoImageError("format");
  }
  try {
    const longest = Math.max(decoded.width, decoded.height);
    if (!(longest > 0)) throw new PhotoImageError("format");
    const nativeType = file.type === "image/jpeg" || file.type === "image/png";
    const resized = longest > PHOTO_MAX_EDGE_PX;
    let dataUrl: string;
    let width = decoded.width;
    let height = decoded.height;
    if (resized || !nativeType) {
      const scale = resized ? PHOTO_MAX_EDGE_PX / longest : 1;
      width = Math.max(1, Math.round(decoded.width * scale));
      height = Math.max(1, Math.round(decoded.height * scale));
      const canvas = deps.createCanvas(width, height);
      const context = canvas.getContext("2d");
      if (!context) throw new PhotoImageError("format");
      context.drawImage(decoded.source, 0, 0, width, height);
      dataUrl = canvas.toDataURL("image/jpeg", PHOTO_JPEG_QUALITY);
    } else {
      dataUrl = await deps.readDataUrl(file);
    }
    if (!DATA_URL_HEAD.test(dataUrl)) throw new PhotoImageError("format");
    const bytes = dataUrlBytes(dataUrl);
    if (bytes > PHOTO_MAX_UPLOAD_BYTES) throw new PhotoImageError("too_large");
    return { dataUrl, width, height, resized, bytes };
  } finally {
    decoded.close?.();
  }
}
