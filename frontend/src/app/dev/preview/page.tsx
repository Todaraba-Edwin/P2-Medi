import Link from "next/link";
import { notFound } from "next/navigation";

// 개발 전용 미리보기 틀. 운영 빌드에서는 404.
export default function PreviewPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return (
    <main className="p-4">
      <h1 className="text-lg font-bold">미리보기</h1>
      <ul>
        <li>
          <Link href="/dev/preview/chat" className="underline">
            채팅
          </Link>
        </li>
        <li>
          <Link href="/dev/preview/brand" className="underline">
            브랜드 이미지
          </Link>
        </li>
      </ul>
    </main>
  );
}
