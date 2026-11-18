import type { ChatResponse } from "@/lib/api";
import { NoMascotZone } from "@/components/NoMascotZone";
import { cn } from "@/lib/utils";
import { ProductLine } from "@/features/result";
import { SECTION_TITLES } from "./copy";
import { EvidenceBox, SourceTag } from "./EvidenceBox";
import { GradeDefBlock } from "./GradeDefBlock";
import { LookupPairs } from "./LookupPairs";
import { MissingBox } from "./MissingBox";
import { PermitText } from "./PermitText";
import { buildSections, isLookupFinding, rowTexts } from "./sections";
import { SourceTable } from "./SourceTable";

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section data-testid="evidence-section" data-section={id} className="flex flex-col gap-2">
      <h3 className="m-0 text-[13px] font-semibold text-mute">{title}</h3>
      {children}
    </section>
  );
}

/**
 * 근거 상세 본문. 구역마다 소제목 1개 + 흰 박스이고 순서는 판정 → 사유 원문 → 허가사항 → 출처다(PRD-11-01).
 * 박스 하나 = 근거 하나. 판정 줄·배지·성분은 결과 카드와 같은 부품(같은 배지 규칙, PRD-15)으로 그린다.
 * 모든 글자는 응답 값이고 LLM 문장이 없다. 값이 없는 구역은 그리지 않는다. 마스코트 금지 영역이다.
 *
 * 고정 안내(`FixedNoticeBox`)·고지(`LegalFooter`)는 이 본문 밖, 접히지 않는 영역에 조립하는 쪽이 둔다.
 */
export function EvidenceDetail({ response }: { response: ChatResponse }) {
  const sections = buildSections(response);
  const advice = response.pharmacist_advice;
  const hasGradeDef = response.grade_def_missing.length > 0 || response.grade_defs.length > 0;
  // 허가사항 한 줄 설명(서버 상수, BE-06-15 A): 구역 맨 위에 한 번만. 같은 문장은 한 번만 보인다
  const labelHelp = [...new Set(sections.labels.map((item) => item.label_help).filter((text): text is string => !!text))];
  return (
    <NoMascotZone>
      <div data-testid="evidence-detail" className="flex flex-col gap-4">
        {(sections.judgments.length > 0 || hasGradeDef) && (
          <Section id="judgment" title={SECTION_TITLES.judgment}>
            {sections.judgments.map(({ finding, item }, index) => (
              <EvidenceBox key={index} testId="judgment-box" tag={item ? <SourceTag item={item} /> : null} className="gap-1">
                {/*
                  결과 카드와 같은 줄 부품. 근거 상세에서는 줄 여백을 박스에 맡기고 배지를 왼쪽에 붙인다(디자인 반영본).
                  박스 표지가 `{출처 종류} · {자료 이름}`을 이미 보이므로(같은 글자) 줄의 출처 표지는 박스 표지가 있을 때 한 번 더 그리지 않는다(PRD-12-04)
                */}
                <ul className={cn("m-0 list-none p-0 [&_[data-testid=line-status]]:ml-0 [&>li]:p-0", item?.dataset && "[&_[data-slot=source]]:hidden")}>
                  {/* 약을 찾지 못한 줄은 이유·재검색·다음 행동을 아래 표가 보이므로 줄에서는 한 번 더 그리지 않는다 */}
                  <ProductLine finding={finding} omitLookupLines={isLookupFinding(finding)} />
                </ul>
                {isLookupFinding(finding) && <LookupPairs finding={finding} />}
              </EvidenceBox>
            ))}
            <GradeDefBlock definitions={response.grade_defs} missing={response.grade_def_missing} advice={advice} />
          </Section>
        )}
        {(sections.reasons.length > 0 || sections.reasonsMissing.length > 0) && (
          <Section id="reason" title={SECTION_TITLES.reason}>
            {sections.reasons.map((item, index) => (
              <EvidenceBox
                key={index}
                testId="reason-box"
                title={item.drugs && item.drugs.length > 0 ? item.drugs.map((drug, i) => <span key={i}>{i > 0 ? " · " : ""}{drug}</span>) : item.drug_name}
                tag={<SourceTag item={item} />}
              >
                {rowTexts(item).map((text, i) => (
                  <p key={i} className="m-0 text-[13px] leading-[19px] break-words whitespace-pre-wrap">
                    {text}
                  </p>
                ))}
                {item.notes.map((note, i) => (
                  <p key={`note-${i}`} data-slot="notes" className="m-0 text-xs leading-[17px] break-words text-mute">
                    {note}
                  </p>
                ))}
              </EvidenceBox>
            ))}
            {sections.reasonsMissing.map((item, index) => (
              <MissingBox key={`missing-${index}`} item={item} advice={advice} />
            ))}
          </Section>
        )}
        {sections.labels.length > 0 && (
          <Section id="label" title={SECTION_TITLES.label}>
            {labelHelp.map((text, index) => (
              <p key={index} data-testid="label-help" className="m-0 rounded-[10px] bg-bg-soft px-2.5 py-2 text-[13px] leading-[19px] break-words text-mute">
                {text}
              </p>
            ))}
            {sections.labels.map((item, index) =>
              item.missing_text !== null ? <MissingBox key={index} item={item} advice={advice} /> : <PermitText key={index} item={item} />,
            )}
          </Section>
        )}
        {sections.citations.length > 0 && (
          <Section id="sources" title={SECTION_TITLES.sources}>
            <SourceTable citations={sections.citations} />
          </Section>
        )}
      </div>
    </NoMascotZone>
  );
}
