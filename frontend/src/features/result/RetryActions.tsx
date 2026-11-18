import { CHIP_CLASS } from "@/components/chip";
import { RETRY_NAME_LABEL } from "./copy";

/**
 * 약을 찾지 못한 결과 카드 아래의 동작 줄(PRD-14-03 A, tickets/doc/PRD-14.md §5.4).
 * `이름 다시 입력`(1차)은 시작 화면 예시 질문 칩과 같은 크기·폰트이고 줄 전체를 채우지 않는다. 누르면 조립하는 쪽이 입력창으로 보낸다.
 * `약 사진 올리기`(2차)는 사진 입력(FE-05)이 없는 구성이라 그리지 않는다(§5.4 "사진 버튼 숨김", AG-10-01 A로 확장 축소).
 * 판정·안내 문장을 갖지 않는다(동작 이름뿐). 근거 상세 박스에는 두지 않는다.
 */
export function RetryActions({ onRetryName }: { onRetryName: () => void }) {
  return (
    <div data-testid="retry-actions" className="flex flex-wrap gap-1.5">
      <button type="button" data-testid="retry-name" onClick={onRetryName} className={CHIP_CLASS}>
        {RETRY_NAME_LABEL}
      </button>
    </div>
  );
}
