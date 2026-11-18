import type { DetailItem } from "@/lib/api";
import { PharmacistAdviceBox } from "@/features/emergency";
import { EvidenceBox, SourceTag } from "./EvidenceBox";

/**
 * 원문 미확보 항목 하나(약 이름 · 항목 · 미확보 문구). 문구는 **응답이 준 `missing_text`만** 그린다(화면 상수 없음, PRD-11-03).
 * 약사 확인 권고는 항목마다 되풀이하지 않고 구역의 `MissingGroup`이 한 번만 그린다(FE-02-05 A). 마스코트·"삐!" 표지를 쓰지 않는다.
 */
export function MissingBox({ item }: { item: DetailItem }) {
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
    </EvidenceBox>
  );
}

export interface MissingGroupProps {
  /** 이 구역의 미확보 항목(받은 순서) */
  items: readonly DetailItem[];
  /** 응답의 약사 확인 권고 줄(`pharmacist_advice[]`). 받은 순서·글자 그대로 */
  advice: readonly string[];
}

/**
 * 구역의 미확보 묶음(FE-02-05 A, PRD-11 §6.7): 약사 확인 권고 박스 1개(접히지 않음) + 그 아래 미확보 항목 목록.
 * 서버는 조합 권고를 응답당 한 줄만 만들므로 구역마다 같은 문장을 되풀이하지 않고 묶음 맨 위에 한 번만 둔다.
 */
export function MissingGroup({ items, advice }: MissingGroupProps) {
  if (items.length === 0) return null;
  return (
    <div data-testid="missing-group" className="flex flex-col gap-2">
      <PharmacistAdviceBox lines={advice} />
      {items.map((item, index) => (
        <MissingBox key={index} item={item} />
      ))}
    </div>
  );
}
