import { CHIP_CLASS } from "@/components/chip";
import { EXAMPLES_HEADING, EXAMPLE_QUESTIONS } from "./copy";

/** 예시 질문 칩. 누르면 그 질문을 넘긴다. 내부 표기(시나리오·이슈 이름)는 싣지 않는다. */
export function ExampleChips({ onPick, questions = EXAMPLE_QUESTIONS }: { onPick: (question: string) => void; questions?: readonly string[] }) {
  return (
    <div className="flex flex-col gap-2">
      <h2 className="m-0 text-xs font-bold text-ink-2">{EXAMPLES_HEADING}</h2>
      <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
        {questions.map((question) => (
          <li key={question} className="max-w-full">
            <button type="button" data-testid="example-chip" onClick={() => onPick(question)} className={CHIP_CLASS}>
              {question}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
