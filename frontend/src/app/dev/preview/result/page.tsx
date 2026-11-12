import { notFound } from "next/navigation";
import { ResultPreview } from "./ResultPreview";

// 개발 전용 미리보기(결과 카드 부품). 운영 빌드에서는 404.
export default function ResultPreviewPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <ResultPreview />;
}
