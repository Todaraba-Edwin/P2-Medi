import { Fragment } from "react";

// 법적 문서 본문(`body_md`)을 그리는 작은 마크다운 부품. 서버 값을 그대로 보이되 HTML로 넣지 않는다(React 요소로만 만든다).
// 지원: 제목(#~###), 목록(-, *, 1.), 문단, 굵게(**). 그 밖의 문법은 글자 그대로 보인다(새 의존성을 더하지 않으려고 작게 둔다).

type Block = { kind: "heading"; level: number; text: string } | { kind: "list"; ordered: boolean; items: string[] } | { kind: "paragraph"; text: string };

const HEADING = /^(#{1,3})\s+(.*)$/;
const BULLET = /^\s*[-*]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;

export function parseMarkdown(source: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  const flush = () => {
    if (paragraph.length > 0) blocks.push({ kind: "paragraph", text: paragraph.join(" ") });
    paragraph = [];
  };
  for (const raw of source.replace(/\r\n?/g, "\n").split("\n")) {
    const line = raw.trimEnd();
    const heading = HEADING.exec(line);
    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    if (line.trim() === "") {
      flush();
    } else if (heading) {
      flush();
      blocks.push({ kind: "heading", level: heading[1].length, text: heading[2] });
    } else if (bullet || numbered) {
      flush();
      const ordered = !bullet;
      const text = (bullet ?? numbered)![1];
      const last = blocks[blocks.length - 1];
      if (last?.kind === "list" && last.ordered === ordered) last.items.push(text);
      else blocks.push({ kind: "list", ordered, items: [text] });
    } else {
      paragraph.push(line.trim());
    }
  }
  flush();
  return blocks;
}

/** `**굵게**`만 바꾼다 */
function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((part, index) =>
        part.length > 4 && part.startsWith("**") && part.endsWith("**") ? <strong key={index}>{part.slice(2, -2)}</strong> : <Fragment key={index}>{part}</Fragment>,
      )}
    </>
  );
}

export function Markdown({ source }: { source: string }) {
  return (
    <div data-testid="legal-body" className="flex flex-col gap-1.5 text-[13px] leading-5 [overflow-wrap:anywhere] text-ink-2">
      {parseMarkdown(source).map((block, index) => {
        if (block.kind === "heading") {
          // 모달 제목(h2)·문서 제목(h3) 아래에 놓이므로 h4부터 쓴다
          return (
            <h4 key={index} className="m-0 mt-1 text-[13px] font-bold text-ink">
              <Inline text={block.text} />
            </h4>
          );
        }
        if (block.kind === "list") {
          const List = block.ordered ? "ol" : "ul";
          return (
            <List key={index} className={block.ordered ? "m-0 list-decimal pl-5" : "m-0 list-disc pl-5"}>
              {block.items.map((item, itemIndex) => (
                <li key={itemIndex}>
                  <Inline text={item} />
                </li>
              ))}
            </List>
          );
        }
        return (
          <p key={index} className="m-0">
            <Inline text={block.text} />
          </p>
        );
      })}
    </div>
  );
}
