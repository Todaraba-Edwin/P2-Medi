import type { DetailItem } from "@/lib/api";
import { PharmacistAdviceBox } from "@/features/emergency";
import { EvidenceBox, SourceTag } from "./EvidenceBox";

export interface MissingBoxProps {
  item: DetailItem;
  /** 응답의 약사 확인 권고 줄(`pharmacist_advice[]`). 미확보 박스 안에 항상 함께 보인다(PRD-11 §6.7) */
  advice: readonly string[];
}

/**
 * 원문 미확보 박스. 문구는 **응답이 준 `missing_text`만** 그린다(화면 상수 없음, PRD-11-03).
 * 박스 안에 약사 확인 권고가 있고 접히지 않는다. 마스코트·"삐!" 표지를 쓰지 않는다.
 */
export function MissingBox({ item, advice }: MissingBoxProps) {
  return (
    <EvidenceBox
      testId="missing-box"
      title={
        <>
          {item.drug_name}
          {item.drug_name && item.section ? " · " : null}
          {item.section}
        </>
      }
      tag={<SourceTag item={item} />}
    >
      {item.missing_text !== null && (
        <p data-testid="missing-text" className="m-0 text-sm leading-[21px] break-words text-ink-2">
          {item.missing_text}
        </p>
      )}
      <PharmacistAdviceBox lines={advice} />
    </EvidenceBox>
  );
}
