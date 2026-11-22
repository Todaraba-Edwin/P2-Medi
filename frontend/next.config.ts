import type { NextConfig } from "next";

// 백엔드 주소는 서버 전용 환경변수. 없으면(개발은 MSW) rewrites를 비워 빌드가 죽지 않게 한다.
const backendOrigin = process.env.MEDIAGENT_BACKEND_ORIGIN?.replace(/\/+$/, "");

/**
 * 개발 서버를 같은 와이파이의 다른 기기(아이패드 등)에서 열 때 허용할 호스트(2026-11-22 사용자 지시).
 * Next 16.4.6 `allowedDevOrigins: string[]`(`node_modules/next/dist/server/config-shared.d.ts:1391`)는 **호스트 이름**(예: `192.168.0.10`, `*.local`) 목록이고
 * `next dev`의 `/_next/*`·HMR 요청에만 쓰인다(`server/lib/router-utils/block-cross-site-dev.js`, `localhost`는 기본 허용).
 * 값은 환경변수 `NEXT_DEV_ALLOWED_ORIGINS`(쉼표 구분, 비밀값 아님)에서만 읽고 특정 IP를 하드코딩하지 않는다. 없으면 빈 배열이며
 * 개발 서버가 아니면(`next build`·`next start`·Vercel) 읽지 않아 프로덕션 빌드에 영향이 없다.
 */
const allowedDevOrigins =
  process.env.NODE_ENV === "development"
    ? (process.env.NEXT_DEV_ALLOWED_ORIGINS ?? "")
        .split(",")
        .map((host) => host.trim())
        .filter((host) => host.length > 0)
    : [];

const nextConfig: NextConfig = {
  allowedDevOrigins,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    if (!backendOrigin) return [];
    return [{ source: "/api/:path*", destination: `${backendOrigin}/:path*` }];
  },
};

export default nextConfig;
