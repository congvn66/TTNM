// PDF.js represents affine transforms as [a, b, c, d, e, f]. Keeping this
// tiny operation local avoids pulling the whole PDF.js runtime into the
// initial bundle just to derive a citation box from the already-rendered text.
function multiplyTransform(first, second) {
  return [
    first[0] * second[0] + first[2] * second[1],
    first[1] * second[0] + first[3] * second[1],
    first[0] * second[2] + first[2] * second[3],
    first[1] * second[2] + first[3] * second[3],
    first[0] * second[4] + first[2] * second[5] + first[4],
    first[1] * second[4] + first[3] * second[5] + first[5],
  ];
}

const compact = (value) => String(value ?? "").normalize("NFKC").replace(/\s+/g, "").toLocaleLowerCase("vi");
const clamp = (value) => Math.max(0, Math.min(1, value));

/**
 * Normalised boxes [x0, y0, x1, y1] of the first place the quote appears in
 * the page text: one box per text run, trimmed to the quoted characters, so a
 * quote inside a paragraph marks only its own words. Whitespace is ignored
 * when matching because PDF text runs split and join words unpredictably.
 */
export function quoteBoxes(textItems, viewport, quote) {
  const quoteText = compact(quote);
  if (!quoteText || !viewport) return [];
  const runs = textItems.map((item) => compact(item.str));
  const start = runs.join("").indexOf(quoteText);
  if (start < 0) return [];
  const end = start + quoteText.length;
  const boxes = [];
  let cursor = 0;
  textItems.forEach((item, index) => {
    const runStart = cursor;
    const runEnd = cursor + runs[index].length;
    cursor = runEnd;
    if (runEnd <= start || runStart >= end || runEnd === runStart) return;
    const transformed = multiplyTransform(viewport.transform, item.transform || [1, 0, 0, 1, 0, 0]);
    const fontSize = Math.max(6, Math.hypot(transformed[2], transformed[3]));
    const width = Math.max(2, Number(item.width || 0) * viewport.scale);
    const length = runEnd - runStart;
    const left = clamp((transformed[4] + width * (Math.max(start, runStart) - runStart) / length) / viewport.width);
    const right = clamp((transformed[4] + width * (Math.min(end, runEnd) - runStart) / length) / viewport.width);
    const top = clamp((transformed[5] - fontSize) / viewport.height);
    const bottom = clamp((transformed[5] + Math.max(2, fontSize * 0.18)) / viewport.height);
    boxes.push([left, top, Math.max(left, right), Math.max(top, bottom)]);
  });
  return boxes;
}
