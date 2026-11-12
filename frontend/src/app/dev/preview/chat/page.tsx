import { notFound } from "next/navigation";
import { ChatPreview } from "./ChatPreview";

// 개발 전용 미리보기(채팅 부품). 운영 빌드에서는 404.
export default function ChatPreviewPage() {
  if (process.env.NODE_ENV === "production") notFound();
  return <ChatPreview />;
}
