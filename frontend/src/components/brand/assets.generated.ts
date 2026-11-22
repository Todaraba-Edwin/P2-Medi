// 생성 파일이다. 손으로 고치지 않는다.
// 원본: images/logo_can_i_ppiyak.png (배정: tickets/frontend/FE-06.md §3.1)
// 다시 만들기(저장소 루트): backend/.venv/bin/python frontend/scripts/crop-brand.py
export const BRAND_ASSETS = {
  "mascot-question": { src: "/brand/mascot-question.png", width: 402, height: 411 },
  "mascot-search": { src: "/brand/mascot-search.png", width: 347, height: 388 },
  "icon-pill": { src: "/brand/icon-pill.png", width: 396, height: 267 },
  "icon-pill-square": { src: "/brand/icon-pill-square.png", width: 311, height: 300 },
  "face": { src: "/brand/face.png", width: 295, height: 270 },
  "face-square": { src: "/brand/face-square.png", width: 301, height: 302 },
  "logo": { src: "/brand/logo.png", width: 428, height: 260 },
  "logo-dark": { src: "/brand/logo-dark.png", width: 428, height: 260 },
  "symbol": { src: "/brand/symbol.png", width: 160, height: 114 },
} as const;

export type BrandAssetName = keyof typeof BRAND_ASSETS;
