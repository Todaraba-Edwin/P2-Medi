import type { DetailItem } from "@/lib/api";
import { permitHeading } from "./copy";
import { EvidenceBox, SourceTag } from "./EvidenceBox";
import { isPermitItem, rowTexts } from "./sections";

/**
 * 허가사항·쉬운 설명 인용 박스. 원문은 응답의 `rows[]` 원문 칸 글자 그대로 인용부호 안에 보인다.
 * 화면이 인용문을 짓거나 줄이지 않고, 용법용량도 표로 쪼개지 않는다(원문 인용만, BE-06-04 B·S8).
 * 머리: 허가정보 인용이면 `{약 이름} 허가사항 원문({항목})`(PRD-10-04), 그 밖(쉬운 설명 등)이면 약 이름과 항목만 받은 그대로 쓴다.
 */
export function PermitText({ item }: { item: DetailItem }) {
  const texts = rowTexts(item);
  const title = isPermitItem(item) ? (
    permitHeading(item.drug_name, item.section)
  ) : (
    <>
      {item.drug_name}
      {item.drug_name && item.section ? " · " : null}
      {item.section}
    </>
  );
  return (
    <EvidenceBox testId="permit-text" title={title} tag={<SourceTag item={item} />}>
      {texts.map((text, index) => (
        <p key={index} className="m-0 text-sm leading-[21px] break-words whitespace-pre-wrap">
          <q className="[quotes:'“'_'”']">{text}</q>
        </p>
      ))}
      {item.notes.map((note, index) => (
        <p key={`note-${index}`} data-slot="notes" className="m-0 text-xs leading-[17px] break-words text-mute">
          {note}
        </p>
      ))}
    </EvidenceBox>
  );
}
