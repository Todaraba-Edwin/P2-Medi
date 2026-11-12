import type { NextConfig } from "next";

// 백엔드 주소는 서버 전용 환경변수. 없으면(개발은 MSW) rewrites를 비워 빌드가 죽지 않게 한다.
const backendOrigin = process.env.MEDIAGENT_BACKEND_ORIGIN?.replace(/\/+$/, "");

const nextConfig: NextConfig = {
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
