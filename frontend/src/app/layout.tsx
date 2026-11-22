import type { Metadata } from "next";
import "@/styles/globals.css";
import { THEME_BOOT_SCRIPT } from "@/lib/theme-boot";

export const metadata: Metadata = {
  title: "Can I PPiyak",
  description: "공공 보건·의약품 데이터 기반 약 정보·금기 확인",
};

// `suppressHydrationWarning`: 인라인 스크립트가 서버 HTML과 다른 `data-theme`를 먼저 걸 수 있다(FE-12-02 ④)
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </head>
      <body className="min-h-dvh">{children}</body>
    </html>
  );
}
