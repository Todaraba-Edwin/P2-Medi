import { MockProvider } from "@/mocks/MockProvider";
import { AppShell } from "./(shell)/AppShell";

/**
 * 첫 화면: 채팅 → 진행 → 결과 → 근거 상세(FE-IMPL-06 조립).
 * `MockProvider`는 `NEXT_PUBLIC_API_MOCKING=enabled`일 때만 MSW 워커를 켜고, 아니면 그대로 그린다.
 */
export default function Home() {
  return (
    <MockProvider>
      <AppShell />
    </MockProvider>
  );
}
