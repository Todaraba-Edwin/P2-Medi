import type { ChatResponse } from "@/lib/api";
import { NoMascotZone } from "@/components/NoMascotZone";
import { cn } from "@/lib/utils";
import { ProductLine, isApiFailNotice } from "@/features/result";
import { COUNT_JOIN, DRUG_JOIN, SECTION_TITLES, formTypeCount, sameContentCount } from "./copy";
import { EvidenceBox, SourceTag } from "./EvidenceBox";
import { GradeDefBlock } from "./GradeDefBlock";
import { LookupPairs } from "./LookupPairs";
import { MissingGroup } from "./MissingBox";
import { PermitText } from "./PermitText";
import { adviceOf, buildSections, drugNamesOf, isLookupFinding, rowTexts } from "./sections";
import type { ReasonEntry } from "./sections";
import { SourceTable } from "./SourceTable";

function Section({ id, title, children }: { id: string; title: string; children: React.ReactNode }) {
  return (
    <section data-testid="evidence-section" data-section={id} className="flex flex-col gap-2">
      <h3 className="m-0 text-[13px] font-semibold text-mute">{title}</h3>
      {children}
    </section>
  );
}

/** 사유 원문 구역의 한 줄 글자 모양(FE-17 U-25 스타일 통일): 사유 원문·약 이름·고정 문구·덧붙임 줄이 모두 같은 크기·줄 간격이다 */
const REASON_LINE = "m-0 text-[13px] leading-[19px] break-words whitespace-pre-wrap";

/** 약 이름 줄(받은 글자 그대로, 여럿이면 ` · `로 잇는다) */
function DrugNames({ names }: { names: readonly string[] }) {
  return (
    <>
      {names.map((name, i) => (
        <span key={i}>
          {i > 0 ? DRUG_JOIN : ""}
          {name}
        </span>
      ))}
    </>
  );
}

/** 하위 묶음 하나. 묶음의 첫 줄(용량주의는 사유 원문, 그 밖은 약 이름)만 굵게 해 묶음의 머리임을 보인다(크기는 같다) */
function ReasonEntryView({ entry }: { entry: ReasonEntry }) {
  if (entry.type === "text") {
    return (
      <div data-testid="reason-group" data-type="text" data-evidence-ids={entry.evidenceIds.join(" ") || undefined} className="flex flex-col gap-0.5">
        {entry.texts.map((text, i) => (
          <p key={i} data-testid="reason-text" className={cn(REASON_LINE, "font-semibold")}>
            {text}
          </p>
        ))}
        {entry.notes.map((note, i) => (
          <p key={`note-${i}`} data-slot="notes" className={cn(REASON_LINE, "text-mute")}>
            {note}
          </p>
        ))}
        {entry.drugs.map((line, i) => (
          <p key={`drug-${i}`} data-testid="reason-drug" data-evidence-ids={line.evidenceIds.join(" ") || undefined} data-count={line.items.length} className={REASON_LINE}>
            <DrugNames names={line.names} />
            {COUNT_JOIN}
            <span data-testid="reason-form-count">{formTypeCount(line.items.length)}</span>
          </p>
        ))}
      </div>
    );
  }
  if (entry.type === "notListed") {
    return (
      <div data-testid="reason-group" data-type="not-listed" data-evidence-ids={entry.evidenceIds.join(" ") || undefined} className="flex flex-col gap-0.5">
        <p data-testid="reason-drug" className={cn(REASON_LINE, "font-semibold")}>
          <DrugNames names={entry.names} />
        </p>
        <p data-testid="reason-not-listed" className={REASON_LINE}>
          {entry.text}
        </p>
      </div>
    );
  }
  const { item, items, evidenceIds } = entry.group;
  return (
    <div data-testid="reason-group" data-type="pair" data-evidence-ids={evidenceIds.join(" ") || undefined} data-count={items.length} className="flex flex-col gap-0.5">
      <p data-testid="reason-drug" className={cn(REASON_LINE, "font-semibold")}>
        <DrugNames names={drugNamesOf(item)} />
        {items.length > 1 && (
          <>
            {COUNT_JOIN}
            <span data-testid="reason-same-count" className="font-normal text-mute">
              {sameContentCount(items.length)}
            </span>
          </>
        )}
      </p>
      {rowTexts(item).map((text, i) => (
        <p key={i} data-testid="reason-text" className={REASON_LINE}>
          {text}
        </p>
      ))}
      {item.notes.map((note, i) => (
        <p key={`note-${i}`} data-slot="notes" className={cn(REASON_LINE, "text-mute")}>
          {note}
        </p>
      ))}
    </div>
  );
}

/**
 * 근거 상세 본문. 구역마다 소제목 1개 + 흰 박스이고 순서는 판정 → 사유 원문 → 허가사항 → 출처다(PRD-11-01).
 * 박스 하나 = 근거 하나. 단 사유 원문 구역은 판정 종류(종류·자료·출처 종류)마다 박스 하나로 묶고, 그 안을 용량주의는 사유 원문 → 약 이름 + "제형유형 N건",
 * 그 밖은 약 이름(쌍) → 사유 원문으로 나눈다(FE-17 U-25, U-19 후속 "같은 내용 N건" 통합). 판정 줄·배지·성분은 결과 카드와 같은 부품(같은 배지 규칙, PRD-15)으로 그린다.
 * 모든 글자는 응답 값이고 LLM 문장이 없다. 값이 없는 구역은 그리지 않는다. 마스코트 금지 영역이다.
 *
 * 고정 안내(`FixedNoticeBox`)·고지(`LegalFooter`)는 이 본문 밖, 접히지 않는 영역에 조립하는 쪽이 둔다.
 * 공공 API 실패 배너(`notice` = `NOTICE_API_FAIL`)는 본문(`ResultView`)이 아니라 여기 맨 위에 한 번 보인다(FE-11-10 A, FE-11 §7.2).
 * 줄의 실시간 확인 노트(`api_flag_note` 문구)도 본문 카드에서는 빠지고 여기 판정 줄 부품에 그대로 남는다.
 */
export function EvidenceDetail({ response }: { response: ChatResponse }) {
  const sections = buildSections(response);
  // 권고 줄은 서버가 준 종류로 구역에 나눈다: 등급 정의 블록에는 등급 정의 권고만, 미확보 묶음에는 미확보 권고만(AG-08-28 A)
  const advice = adviceOf(response);
  const hasGradeDef = response.grade_def_missing.length > 0 || response.grade_defs.length > 0;
  // 허가사항 한 줄 설명(서버 상수, BE-06-15 A): 구역 맨 위에 한 번만. 같은 문장은 한 번만 보인다
  const labelHelp = [...new Set(sections.labels.map((item) => item.label_help).filter((text): text is string => !!text))];
  return (
    <NoMascotZone>
      <div data-testid="evidence-detail" className="flex flex-col gap-4">
        {/* 실시간 확인 실패 배너(서버 상수 글자 그대로): 본문에는 없고 근거 상세 맨 위에만 */}
        {response.notice !== null && isApiFailNotice(response.notice) && (
          <p role="note" data-testid="evidence-api-fail-notice" className="m-0 rounded-xl bg-warn-bg px-3 py-2 text-[13px] leading-[19px] font-semibold break-words text-warn-ink">
            {response.notice}
          </p>
        )}
        {(sections.judgments.length > 0 || hasGradeDef) && (
          <Section id="judgment" title={SECTION_TITLES.judgment}>
            {/* 같은 약의 판정 박스는 붙여서 한 묶음(테두리를 이은 카드)으로, 보이는 것이 같은 박스는 하나로 묶고 "같은 내용 N건"(FE-17 U-26-5·6) */}
            {sections.judgmentGroups.map((group, groupIndex) => (
              <div
                key={groupIndex}
                data-testid="judgment-drug-group"
                data-count={group.boxes.length}
                className="flex flex-col [&>*:not(:first-child)]:-mt-px [&>*:not(:first-child)]:rounded-t-none [&>*:not(:last-child)]:rounded-b-none"
              >
                {group.boxes.map(({ finding, item, count, evidenceIds }, index) => (
                  <EvidenceBox
                    key={index}
                    testId="judgment-box"
                    data-count={count}
                    data-evidence-ids={evidenceIds.join(" ") || undefined}
                    tag={
                      item || count > 1 ? (
                        <>
                          {item ? <SourceTag item={item} /> : null}
                          {count > 1 && (
                            <span data-testid="judgment-same-count" className="flex-none text-[13px] leading-[19px] text-mute">
                              {sameContentCount(count)}
                            </span>
                          )}
                        </>
                      ) : null
                    }
                    className="gap-1"
                  >
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
              </div>
            ))}
            <GradeDefBlock definitions={response.grade_defs} missing={response.grade_def_missing} advice={advice.gradeDef} />
          </Section>
        )}
        {(sections.reasonKinds.length > 0 || sections.reasonsMissing.length > 0) && (
          <Section id="reason" title={SECTION_TITLES.reason}>
            {/* 판정 종류 묶음(FE-17 U-25): 종류·자료·출처 종류가 같은 근거는 박스 하나(표지 = 지금 문구 `{출처 종류} · {자료 이름}`).
                박스 안: 용량주의는 사유 원문 → 약 이름 + `제형유형 N건`, 그 밖은 약 이름(쌍) → 사유 원문(같은 내용은 "같은 내용 N건"),
                금기 목록에 없는 병용금기 쌍은 약 이름 쌍 → 판정 줄 고정 문구. 줄 글자 크기·줄 간격은 모두 13px/19px로 맞춘다.
                글자는 받은 값 그대로이고 묶인 근거 ID는 `data-evidence-ids`에 받은 순서대로 남긴다 */}
            {sections.reasonKinds.map((kind, index) => (
              <EvidenceBox
                key={index}
                testId="reason-box"
                data-kind={kind.item.kind ?? undefined}
                data-evidence-ids={kind.evidenceIds.join(" ") || undefined}
                data-count={kind.count}
                tag={<SourceTag item={kind.item} />}
                className="gap-3"
              >
                {kind.entries.map((entry, i) => (
                  <ReasonEntryView key={i} entry={entry} />
                ))}
              </EvidenceBox>
            ))}
            <MissingGroup items={sections.reasonsMissing} advice={advice.missing} />
          </Section>
        )}
        {sections.labels.length > 0 && (
          <Section id="label" title={SECTION_TITLES.label}>
            {labelHelp.map((text, index) => (
              <p key={index} data-testid="label-help" className="m-0 rounded-[10px] bg-bg-soft px-2.5 py-2 text-[13px] leading-[19px] break-words text-mute">
                {text}
              </p>
            ))}
            {sections.labels.map((item, index) => (item.missing_text === null ? <PermitText key={index} item={item} /> : null))}
            {/* 미확보는 인용 뒤에 구역 묶음 하나로: 권고 1개 + 항목 목록(FE-02-05 A) */}
            <MissingGroup items={sections.labels.filter((item) => item.missing_text !== null)} advice={advice.missing} />
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
