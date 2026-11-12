import { notFound } from "next/navigation";
import { EmergencyScreenPreview } from "./EmergencyScreenPreview";

// 개발 전용: 응급 화면에서 119 배너와 고정 안내가 스크롤 없이 첫 화면에 들어오는지 보는 배치. 운영 빌드에서는 404.
export default function EmergencyScreenPreviewPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <EmergencyScreenPreview />;
}
