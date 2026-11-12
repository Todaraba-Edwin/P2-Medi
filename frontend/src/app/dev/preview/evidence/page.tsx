import { notFound } from "next/navigation";
import { EvidencePreview } from "./EvidencePreview";

// 개발 전용 미리보기(근거 상세·안전 영역 부품). 운영 빌드에서는 404.
export default function EvidencePreviewPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <EvidencePreview />;
}
