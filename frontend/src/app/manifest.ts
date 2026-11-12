import type { MetadataRoute } from "next";
import { BRAND_NAME } from "@/components/brand/name";

// 홈 화면 추가용 최소 정보만 둔다. 오프라인·서비스 워커는 만들지 않는다(PWA는 확장 범위).
// 색은 src/styles/globals.css 토큰 값이다: theme_color = --color-yellow, background_color = --color-bg.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: BRAND_NAME,
    short_name: "삐약",
    start_url: "/",
    display: "standalone",
    theme_color: "#ffcc00",
    background_color: "#ffffff",
    icons: [
      { src: "/brand/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/brand/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
  };
}
