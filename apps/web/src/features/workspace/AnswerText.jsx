// Answer text from the model is plain text with a little Markdown: blank
// lines between paragraphs, "- " or "1. " list items and **bold**. It is
// turned into React elements, never into HTML, so no markup in the text runs.

const BULLET = /^[-*•+]\s+(.*)$/;
const NUMBERED = /^\d+[.)]\s+(.*)$/;
const HEADING = /^#{1,6}\s+(.*)$/;

/** Paragraphs and lists of an answer: [{ type: "p" | "ul" | "ol", lines: [...] }]. */
export function answerBlocks(text) {
  const blocks = [];
  let current = null;
  for (const raw of String(text ?? "").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) { current = null; continue; }
    const bullet = line.match(BULLET);
    const numbered = !bullet && line.match(NUMBERED);
    const type = bullet ? "ul" : numbered ? "ol" : "p";
    const content = bullet?.[1] ?? numbered?.[1] ?? line.replace(HEADING, "**$1**");
    if (current?.type !== type) { current = { type, lines: [] }; blocks.push(current); }
    current.lines.push(content);
  }
  return blocks;
}

function Inline({ text }) {
  // "**a**" is bold; an unmatched "**" stays as typed.
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, index) => (/^\*\*[^*]+\*\*$/.test(part) ? <strong key={index}>{part.slice(2, -2)}</strong> : part));
}

/** The answer as paragraphs and lists; the first paragraph is the lead. */
export function AnswerText({ text }) {
  return answerBlocks(text).map((block, index) => {
    if (block.type === "p") {
      return <p key={index} className={index === 0 ? "answer-lead" : "answer-paragraph"}>{block.lines.map((line, lineIndex) => <span key={lineIndex}>{lineIndex > 0 && <br />}<Inline text={line} /></span>)}</p>;
    }
    const List = block.type;
    return <List key={index} className="answer-list">{block.lines.map((line, lineIndex) => <li key={lineIndex}><Inline text={line} /></li>)}</List>;
  });
}
