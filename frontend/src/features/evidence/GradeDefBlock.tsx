"use client";

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { PharmacistAdviceBox } from "@/features/emergency";

export interface GradeDefinition {
  /** 블록 제목(예: 등급 이름을 묻는 한 줄). 응답 값이어야 한다 */
  title: string;
  /** 고시 원문 인용(코드가 원문에서 가져온 글자 그대로) */
  quote: string;
  /** 원문 출처 표기. 원문이 있을 때만 */
  source?: string | null;
}

export interface GradeDefBlockProps {
  /** 등급 정의 원문 블록(기본 접힘). **지금 응답 계약(v1)에는 제목·원문 칸이 없어 조립하는 쪽이 넘길 값이 없다.** */
  definitions?: readonly GradeDefinition[];
  /** 등급 정의 미확보 문구(`grade_def_missing[]`, 응답 값 그대로). 접힘 밖에 항상 보인다 */
  missing: readonly string[];
  /** 약사 확인 권고 줄(`pharmacist_advice[]`). 미확보가 있으면 접힘 밖에 함께 보인다 */
  advice: readonly string[];
}

/**
 * 등급 정의 블록(PRD-09-04, PRD-15-03). 원문 블록은 기본으로 접혀 있어도 된다.
 * 미확보 문구와 약사 권고는 접히는 부분 밖에 둔다(S5). 미확보 블록에는 조항 출처 줄을 그리지 않는다.
 */
export function GradeDefBlock({ definitions = [], missing, advice }: GradeDefBlockProps) {
  if (definitions.length === 0 && missing.length === 0) return null;
  return (
    <div data-testid="grade-def" className="flex flex-col gap-2">
      {definitions.length > 0 && (
        <Accordion type="multiple" className="rounded-[10px] border border-line bg-bg px-2.5 text-[13px] leading-[19px]">
          {definitions.map((definition, index) => (
            <AccordionItem key={index} value={`definition-${index}`} className="last:border-b-0">
              <AccordionTrigger className="min-h-11 py-2 font-semibold text-link">{definition.title}</AccordionTrigger>
              <AccordionContent>
                <blockquote className="m-0 rounded-r-lg border-l-[3px] border-preg bg-preg-bg px-2.5 py-1.5 break-words text-ink-2">
                  {definition.quote}
                </blockquote>
                {definition.source ? <p className="m-0 mt-1.5 text-xs break-words text-mute">{definition.source}</p> : null}
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      )}
      {missing.length > 0 && (
        <div data-testid="grade-def-missing" className="flex flex-col gap-2 rounded-[10px] border border-line bg-bg px-2.5 py-2">
          {missing.map((line, index) => (
            <p key={index} className="m-0 text-[13px] leading-[19px] break-words text-ink-2">
              {line}
            </p>
          ))}
          <PharmacistAdviceBox lines={advice} />
        </div>
      )}
    </div>
  );
}
