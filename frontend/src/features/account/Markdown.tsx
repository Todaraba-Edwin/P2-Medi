import { Fragment } from "react";

// 법적 문서 본문(`body_md`)을 그리는 작은 마크다운 부품. 서버 값을 그대로 보이되 HTML로 넣지 않는다(React 요소로만 만든다).
// 지원: 제목(#~###), 목록(-, *, 1.), 문단, 굵게(**), 인용(> …, 시드 머리의 "초안·법률 검토 전" 안내),
// GFM 파이프 표(머리 줄 + `|---|` 구분 줄 + 본문 줄. 칸 안 굵게 유지). 구분 줄이 없는 `|` 줄은 표가 아니라 문단(글자 그대로)이다.
// GFM 강제 줄바꿈(줄 끝 두 칸 이상 공백 또는 `\`)은 문단·인용 안에서 `<br>`로 그린다. 그냥 이어지는 줄은 GFM대로 한 문단(공백으로 잇는다).
// 그 밖의 문법은 글자 그대로 보인다(새 의존성을 더하지 않으려고 작게 둔다).
// 접힘 규칙: 긴 글자는 칸·상자 안에서 접히되(overflow-wrap), 이메일 주소는 한 덩어리로 두어 중간에서 끊기지 않는다(연락처 줄 가독성).

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "paragraph"; text: string }
  | { kind: "quote"; text: string }
  | { kind: "table"; header: string[]; rows: string[][] };

const HEADING = /^(#{1,3})\s+(.*)$/;
const BULLET = /^\s*[-*]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const QUOTE = /^\s*>\s?(.*)$/;
/** GFM 강제 줄바꿈: 줄 끝 두 칸 이상 공백 또는 백슬래시 */
const HARD_BREAK = /( {2,}|\\)$/;
/** 문단 안 강제 줄바꿈 표식(블록 text에 넣고 그릴 때 `<br>`로 바꾼다) */
const BREAK = "\n";
/** 이메일 주소 모양(한 덩어리로 둔다) */
const EMAIL = /([^\s@<>()|]+@[^\s@<>()|]+\.[A-Za-z0-9-]+)/g;
/** 표 줄: 앞뒤 공백을 뺀 줄이 `|`로 시작한다 */
const TABLE_ROW = /^\s*\|/;
/** 표 구분 줄: `|---|:--:|` 꼴(정렬 콜론 허용, 바깥 `|`는 선택) */
const TABLE_DELIMITER = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

/** `| 가 | 나 |` 한 줄을 칸으로 나눈다(바깥 `|`를 떼고 `|`로 가른다. 칸 안 `\|`는 지원하지 않는다) */
function splitCells(line: string): string[] {
  let body = line.trim();
  if (body.startsWith("|")) body = body.slice(1);
  if (body.endsWith("|")) body = body.slice(0, -1);
  return body.split("|").map((cell) => cell.trim());
}

export function parseMarkdown(source: string): Block[] {
  const blocks: Block[] = [];
  const lines = source.replace(/\r\n?/g, "\n").split("\n");
  let paragraph: string[] = [];
  /** 줄 끝 강제 줄바꿈이면 표식을 붙여 돌려준다(다음 줄과 공백 대신 `<br>`로 잇는다) */
  const withBreak = (raw: string, text: string) => {
    if (!HARD_BREAK.test(raw) || !text) return text;
    const body = text.endsWith("\\") ? text.slice(0, -1).trimEnd() : text; // 백슬래시 자체는 글자로 남기지 않는다
    return body ? `${body}${BREAK}` : body;
  };
  /** 모인 줄을 한 문단 글자로 잇는다: 강제 줄바꿈 뒤에는 공백을 넣지 않는다 */
  const joinLines = (parts: string[]) => parts.reduce((acc, part) => (acc === "" ? part : acc.endsWith(BREAK) ? `${acc}${part}` : `${acc} ${part}`), "");
  /** 블록 끝의 강제 줄바꿈 표식은 뗀다(GFM: 문단 끝 줄바꿈은 무시) */
  const trimBreak = (text: string) => (text.endsWith(BREAK) ? text.slice(0, -BREAK.length) : text);
  const flush = () => {
    if (paragraph.length > 0) blocks.push({ kind: "paragraph", text: trimBreak(joinLines(paragraph)) });
    paragraph = [];
  };
  for (let index = 0; index < lines.length; index += 1) {
    const raw = lines[index];
    const line = raw.trimEnd();
    const heading = HEADING.exec(line);
    const bullet = BULLET.exec(line);
    const numbered = NUMBERED.exec(line);
    const quote = QUOTE.exec(line);
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
    } else if (quote) {
      // 이어지는 `>` 줄은 한 인용 안의 한 문단으로 잇는다(문단과 같은 규칙)
      flush();
      const text = withBreak(raw, quote[1].trim());
      const last = blocks[blocks.length - 1];
      if (last?.kind === "quote") last.text = text ? joinLines([last.text, text]) : last.text;
      else blocks.push({ kind: "quote", text });
    } else if (TABLE_ROW.test(line) && index + 1 < lines.length && TABLE_DELIMITER.test(lines[index + 1])) {
      // 머리 줄 + 구분 줄이 있어야 표다. 본문 줄은 `|`로 시작하는 줄이 이어지는 동안이다
      flush();
      const header = splitCells(line);
      const rows: string[][] = [];
      index += 1; // 구분 줄은 그리지 않는다
      while (index + 1 < lines.length && TABLE_ROW.test(lines[index + 1]) && lines[index + 1].trim() !== "") {
        index += 1;
        const cells = splitCells(lines[index]);
        // 칸 수를 머리 줄에 맞춘다(모자라면 빈 칸, 넘치면 버리지 않고 마지막 칸에 잇는다: 글자를 잃지 않는다)
        if (cells.length > header.length) cells.splice(header.length - 1, cells.length - header.length + 1, cells.slice(header.length - 1).join(" | "));
        while (cells.length < header.length) cells.push("");
        rows.push(cells);
      }
      blocks.push({ kind: "table", header, rows });
    } else {
      paragraph.push(withBreak(raw, line.trim()));
    }
  }
  flush();
  for (const block of blocks) if (block.kind === "quote") block.text = trimBreak(block.text);
  return blocks;
}

/** 굵게 안·밖의 보통 글자: 강제 줄바꿈은 `<br>`, 이메일은 끊기지 않는 덩어리 */
function Plain({ text }: { text: string }) {
  return (
    <>
      {text.split(BREAK).map((line, lineIndex) => (
        <Fragment key={lineIndex}>
          {lineIndex > 0 && <br />}
          {line.split(EMAIL).map((piece, pieceIndex) =>
            pieceIndex % 2 === 1 ? (
              <span key={pieceIndex} data-testid="legal-email" className="whitespace-nowrap [overflow-wrap:normal]">
                {piece}
              </span>
            ) : (
              <Fragment key={pieceIndex}>{piece}</Fragment>
            ),
          )}
        </Fragment>
      ))}
    </>
  );
}

/** `**굵게**`만 바꾼다(나머지는 Plain) */
function Inline({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((part, index) =>
        part.length > 4 && part.startsWith("**") && part.endsWith("**") ? (
          <strong key={index}>
            <Plain text={part.slice(2, -2)} />
          </strong>
        ) : (
          <Plain key={index} text={part} />
        ),
      )}
    </>
  );
}

/** 표 칸의 공통 모양: 선·여백·줄 바꿈 허용(긴 글자는 칸 안에서 접힌다). 칸 최소 폭을 둬 좁은 폭에서는 상자 안에서만 가로로 민다 */
const CELL = "min-w-[6rem] border border-line-2 px-2 py-1 align-top whitespace-normal [overflow-wrap:anywhere]";

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
        if (block.kind === "quote") {
          return (
            <blockquote key={index} className="m-0 border-l-4 border-line-2 pl-2.5 text-mute">
              <Inline text={block.text} />
            </blockquote>
          );
        }
        if (block.kind === "table") {
          // 표는 페이지·모달이 아니라 이 상자 안에서만 가로로 민다(393에서 페이지 가로 스크롤 없음)
          return (
            <div key={index} data-testid="legal-table" className="max-w-full overflow-x-auto">
              <table className="w-full border-collapse text-left">
                <thead>
                  <tr>
                    {block.header.map((cell, cellIndex) => (
                      <th key={cellIndex} scope="col" className={`${CELL} bg-bg-soft font-bold text-ink`}>
                        <Inline text={cell} />
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {block.rows.map((row, rowIndex) => (
                    <tr key={rowIndex}>
                      {row.map((cell, cellIndex) => (
                        <td key={cellIndex} className={CELL}>
                          <Inline text={cell} />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
