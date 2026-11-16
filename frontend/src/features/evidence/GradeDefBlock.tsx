"use client";

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import type { GradeDef } from "@/lib/api";
import { PharmacistAdviceBox } from "@/features/emergency";

export interface GradeDefBlockProps {
  /**
   * 등급 정의 블록(`grade_defs[]`, BE-06-16 A). 제목·원문·출처 줄·미확보 문구 모두 응답 값 그대로다.
   * 원문(`text`)이 있는 블록은 접힘 블록(기본 접힘)으로, 미확보 블록은 접힘 밖에 문구만 그린다(조항 출처 줄 없음)
   */
  definitions?: readonly GradeDef[];
  /** 등급 정의 미확보 문구(`grade_def_missing[]`). 구조 칸(`definitions`)이 오지 않았을 때만 쓴다(같은 문장이 두 번 보이지 않게) */
  missing: readonly string[];
  /** 약사 확인 권고 줄(`pharmacist_advice[]`). 미확보가 있으면 접힘 밖에 함께 보인다 */
  advice: readonly string[];
}

/**
 * 등급 정의 블록(PRD-09-04, PRD-15-03). 원문 블록은 기본으로 접혀 있어도 된다.
 * 미확보 문구와 약사 권고는 접히는 부분 밖에 둔다(S5). 미확보 블록에는 조항 출처 줄을 그리지 않는다.
 */
export function GradeDefBlock({ definitions = [], missing, advice }: GradeDefBlockProps) {
  const quoted = definitions.filter((definition) => definition.text !== null);
  const missingLines =
    definitions.length > 0 ? definitions.map((definition) => definition.missing_text).filter((text): text is string => text !== null) : missing;
  if (quoted.length === 0 && missingLines.length === 0) return null;
  return (
    <div data-testid="grade-def" className="flex flex-col gap-2">
      {quoted.length > 0 && (
        <Accordion type="multiple" className="rounded-[10px] border border-line bg-bg px-2.5 text-[13px] leading-[19px]">
          {quoted.map((definition, index) => (
            <AccordionItem key={index} value={`definition-${index}`} data-testid="grade-def-item" data-grade={definition.grade} className="last:border-b-0">
              <AccordionTrigger className="min-h-11 py-2 font-semibold text-link">{definition.title}</AccordionTrigger>
              <AccordionContent>
                <blockquote className="m-0 rounded-r-lg border-l-[3px] border-preg bg-preg-bg px-2.5 py-1.5 break-words whitespace-pre-wrap text-ink-2">
                  {definition.text}
                </blockquote>
                {definition.source ? <p data-slot="grade-def-source" className="m-0 mt-1.5 text-xs break-words text-mute">{definition.source}</p> : null}
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      )}
      {missingLines.length > 0 && (
        <div data-testid="grade-def-missing" className="flex flex-col gap-2 rounded-[10px] border border-line bg-bg px-2.5 py-2">
          {missingLines.map((line, index) => (
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
