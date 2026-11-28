import { readableFormula } from "./formulaView.js";
import { PART_COLORS, PART_INK } from "./partColors.js";
import { formatNumber } from "./reportChecks.js";

export const partColor = (index) => PART_COLORS[index % PART_COLORS.length];
export const partInk = (index) => PART_INK[index % PART_INK.length];

/**
 * The numbered tag of a calculation input. The number is decoration for
 * sighted readers: screen readers and copy-paste get "số 1: 42.290", never "1 42.290".
 */
export function InputTag({ index }) {
  return <><span className="rd-tag" style={{ "--part": partColor(index), "--part-ink": partInk(index) }} aria-hidden="true">{index + 1}</span><span className="rd-sr">số {index + 1}: </span></>;
}

/** Hover or keyboard focus on an input outlines its cell on the page. */
export const peekProps = (key, onPeek) => (onPeek ? {
  onMouseEnter: () => onPeek(key), onMouseLeave: () => onPeek(null), onFocus: () => onPeek(key), onBlur: () => onPeek(null),
} : {});

/**
 * "= (2 − 1) ÷ 1 × 100" with each cell as its numbered value; null when the
 * script is not plain arithmetic. `lead` is what comes before it ("" when the result follows).
 */
export function FormulaLine({ formula, result, onPeek, lead = "= " }) {
  const pieces = formula?.expression ? readableFormula(formula.expression, result) : null;
  if (!pieces) return null;
  const inputs = formula.inputs ?? [];
  return <span className="rd-fx">{lead}{pieces.map((piece, i) => {
    if (piece.text != null) return <span key={i}>{piece.text}</span>;
    const index = inputs.findIndex((input) => input.evidence_key === piece.cell);
    const input = inputs[index];
    if (!input) return <span key={i}>?</span>;
    // Not a Tab stop: it does nothing on Enter. Keyboard users reach the same inputs in the answer card.
    return <span key={i} className="rd-tok" style={{ "--part": partColor(index) }} {...peekProps(piece.cell, onPeek)}><InputTag index={index} />{formatNumber(Number(input.value))}</span>;
  })}</span>;
}
