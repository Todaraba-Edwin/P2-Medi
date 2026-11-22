// 사진 준비(FE-05): 브라우저 메모리에서만 한다. 파일·data URL을 `localStorage`·IndexedDB·쿠키에 넣지 않고, 서버로 보낸 뒤에는 부르는 쪽이 참조를 버린다.
// - 긴 변이 2800px를 넘으면 canvas로 2800에 맞춰 줄이고 JPEG(q0.9)로 바꾼다(업로드 크기를 줄인다. 서버는 다시 1400px로 맞춘다, 〔D2〕A)
// - HEIC/HEIF(BE-14-08 A, 2026-11-22)와 그 밖의 JPEG·PNG가 아닌 파일은 브라우저가 디코드할 수 있으면 canvas로 JPEG로 바꿔 보내고(서버는 JPEG·PNG만 받고
//   HEIC는 422다. 서버에 `pillow-heif`를 더하지 않는다), 못 하면(데스크톱 Chrome 등) 형식 안내(P7)로 떨어진다. 변환은 브라우저 안에서만 하고 저장·로그는 없다
// - 서버 상한 8MB보다 크면 보내지 않는다(P7)
// 디코드·canvas·파일 읽기는 끼워 넣을 수 있게 둔다(`ImageDeps`): jsdom에는 canvas가 없어 시험은 합성 구현으로 돈다.

export const PHOTO_MAX_EDGE_PX = 2800;
export const PHOTO_JPEG_QUALITY = 0.9;
/** 서버 상한(BE 지시서 §3 2번 "디코드 뒤 8MB 이하")과 같은 값 */
export const PHOTO_MAX_UPLOAD_BYTES = 8 * 1024 * 1024;
/** HEIC/HEIF로 보는 MIME 타입(소문자 비교). 확장자는 `HEIC_EXTENSION`으로 따로 본다(일부 기기는 `type`을 비워 보낸다) */
export const HEIC_MIME_TYPES = ["image/heic", "image/heif"] as const;
const HEIC_EXTENSION = /\.(heic|heif)$/i;
/**
 * `<input type="file" accept>` 값. 카메라·앨범은 브라우저가 고른다.
 * HEIC/HEIF도 고를 수 있게 둔다(BE-14-08 A): 고르면 `prepareImage`가 브라우저 안에서 JPEG로 바꾸고, 디코드 못 하는 브라우저에서는 P7로 떨어진다.
 * 타입과 확장자를 둘 다 적는다(파일 선택 창이 타입을 모르는 `.heic`도 보이게)
 */
export const PHOTO_ACCEPT = ["image/jpeg", "image/png", ...HEIC_MIME_TYPES, ".heic", ".heif"].join(",");
const DATA_URL_HEAD = /^data:image\/(jpeg|png);base64,/;

/** HEIC/HEIF 파일인가: MIME 타입(`image/heic`·`image/heif`) 또는 파일 이름 확장자(`.heic`·`.heif`, 대소문자 무관)로 본다 */
export function isHeicFile(file: Blob): boolean {
  const type = file.type.toLowerCase();
  if ((HEIC_MIME_TYPES as readonly string[]).includes(type)) return true;
  const name = "name" in file && typeof (file as File).name === "string" ? (file as File).name : "";
  return HEIC_EXTENSION.test(name);
}

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

/** `<img>`로 디코드한다(object URL은 디코드가 끝나면 바로 놓아준다). 브라우저가 그 형식을 모르면 거부된다 */
const decodeWithImageElement = async (file: Blob): Promise<DecodedImage> => {
  const url = URL.createObjectURL(file);
  try {
    const image = await new Promise<HTMLImageElement>((resolve, reject) => {
      const element = new Image();
      element.onload = () => resolve(element);
      element.onerror = () => reject(new Error("decode"));
      element.src = url;
    });
    if (typeof image.decode === "function") await image.decode().catch(() => undefined);
    return { width: image.naturalWidth, height: image.naturalHeight, source: image };
  } finally {
    URL.revokeObjectURL(url);
  }
};

/**
 * 브라우저 디코드: `createImageBitmap`(EXIF 방향을 적용한 비트맵, `from-image`는 표준 기본값이지만 명시한다) → 안 되면 `<img>`로 한 번 더 본다.
 * HEIC는 플랫폼 디코더가 있는 브라우저(Safari)만 성공하고, 없는 브라우저(데스크톱 Chrome 등)는 두 길 다 거부해 `format`으로 떨어진다.
 */
const decodeInBrowser = async (file: Blob): Promise<DecodedImage> => {
  if (typeof createImageBitmap === "function") {
    try {
      const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
      return { width: bitmap.width, height: bitmap.height, source: bitmap, close: () => bitmap.close() };
    } catch {
      // 비트맵 디코더가 모르는 형식(또는 옵션 미지원): `<img>` 디코더로 넘어간다
    }
  }
  return decodeWithImageElement(file);
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
 * - JPEG·PNG가 2800px 이하면 파일 바이트를 그대로 data URL로 읽는다(변환 없음, EXIF 그대로. 서버가 방향을 처리한다)
 * - HEIC/HEIF(`isHeicFile`)·그 밖의 형식·2800px 초과는 디코드한 비트맵을 canvas에 그려 JPEG(q0.9)로 바꾼다(방향은 디코더가 적용한 그대로)
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
    const nativeType = !isHeicFile(file) && (file.type === "image/jpeg" || file.type === "image/png");
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
