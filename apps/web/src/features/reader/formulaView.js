// An answer's calculation script read back as one formula people can follow,
// with each cell it reads as a numbered input: "(2 − 1) ÷ 1 × 100".
// Only plain arithmetic is shown. A result that depends on anything else
// (loops, lists, comparisons, other calls) gives null, and the card falls
// back to listing the inputs: no formula is better than a wrong one.

// Identifiers may be Vietnamese ("dt_miền_trung"), so letters are Unicode letters.
const NAME = String.raw`[\p{L}_][\p{L}\p{N}_]*`;
const TOKEN = new RegExp(String.raw`\s*(?:(value)\(\s*(['"])([^'"]+)\2\s*\)|(\d+(?:\.\d+)?)|(${NAME})|(\*\*|\/\/|[-+*/%(),{}:\[\]=<>!]|"[^"]*"|'[^']*'))`, "uy");
const ASSIGN = new RegExp(String.raw`^(${NAME})\s*=(?!=)\s*(.+)$`, "su");

function tokenize(text) {
  const tokens = [];
  TOKEN.lastIndex = 0;
  while (TOKEN.lastIndex < text.length) {
    const start = TOKEN.lastIndex;
    const match = TOKEN.exec(text);
    if (!match) return text.slice(start).trim() ? null : tokens;
    if (match[1]) tokens.push({ type: "cell", key: match[3] });
    else if (match[4]) tokens.push({ type: "num", value: match[4] });
    else if (match[5]) tokens.push({ type: "name", value: match[5] });
    else tokens.push({ type: /^["']/.test(match[6]) ? "str" : "op", value: match[6].replace(/^["']|["']$/g, "") });
  }
  return tokens;
}

/** Recursive descent over + − × ÷, unary minus, brackets, round(), abs() and Decimal('n'). */
function parse(tokens) {
  let at = 0;
  const peek = () => tokens[at];
  const take = (value) => (peek()?.type !== "str" && peek()?.value === value ? tokens[at++] : null);
  const expr = () => {
    let left = term();
    while (left && (peek()?.value === "+" || peek()?.value === "-") && peek().type === "op") { const op = tokens[at++].value; const right = term(); if (!right) return null; left = { op, left, right }; }
    return left;
  };
  const term = () => {
    let left = unary();
    while (left && (peek()?.value === "*" || peek()?.value === "/") && peek().type === "op") { const op = tokens[at++].value; const right = unary(); if (!right) return null; left = { op, left, right }; }
    return left;
  };
  const unary = () => {
    if (take("-")) { const inner = unary(); return inner && { op: "neg", inner }; }
    if (take("+")) return unary();
    return atom();
  };
  const atom = () => {
    const token = peek();
    if (!token) return null;
    if (token.type === "cell") { at++; return { cell: token.key }; }
    if (token.type === "num") { at++; return { num: token.value }; }
    if (take("(")) { const inner = expr(); return inner && take(")") ? inner : null; }
    const call = token.type === "name" && tokens[at + 1]?.value === "(" ? token.value : null;
    if (call === "Decimal") {
      // Decimal('100') is the number 100.
      const arg = tokens[at + 2];
      if ((arg?.type === "str" || arg?.type === "num") && /^-?\d+(\.\d+)?$/.test(arg.value) && tokens[at + 3]?.value === ")") { at += 4; return { num: arg.value }; }
      return null;
    }
    if (call === "round" || call === "abs" || call === "float") {
      at += 2;
      const inner = expr();
      if (!inner) return null;
      // round(x, 2) is shown as x: the result line already shows the rounding.
      if (call === "round" && take(",")) { if (peek()?.type !== "num") return null; at++; }
      if (!take(")")) return null;
      // round is kept in the tree: only an outermost round may be left out of the formula shown.
      return call === "abs" ? { op: "abs", inner } : call === "round" ? { op: "round", inner } : inner;
    }
    if (token.type === "name" && !call) { at++; return { name: token.value }; }
    return null;
  };
  const tree = expr();
  return tree && at === tokens.length ? tree : null;
}

// A name whose value the formula cannot show (a list, a comparison, a loop variable).
const UNKNOWN = Symbol("unknown");

/** Put in the value each name has at this point of the script, so a reassigned name reads right. */
function resolve(tree, known) {
  if (!tree) return UNKNOWN;
  if (tree.name) { const value = known.get(tree.name); return value === undefined ? UNKNOWN : value; }
  if (tree.cell || tree.num) return tree;
  if (tree.inner) { const inner = resolve(tree.inner, known); return inner === UNKNOWN ? UNKNOWN : { ...tree, inner }; }
  const left = resolve(tree.left, known);
  const right = resolve(tree.right, known);
  return left === UNKNOWN || right === UNKNOWN ? UNKNOWN : { ...tree, left, right };
}

/** The script's statements, one per entry, with lines inside brackets joined. */
function statements(code) {
  const out = [];
  let current = "";
  let depth = 0;
  for (const raw of String(code ?? "").split(/\r?\n/)) {
    const line = withoutComment(raw);
    current += (current ? " " : "") + line.trim();
    for (const char of line.replace(/"[^"]*"|'[^']*'/g, "")) { if ("([{".includes(char)) depth++; if (")]}".includes(char)) depth--; }
    if (depth <= 0) { if (current.trim()) out.push({ text: current.trim(), indented: /^\s/.test(raw) }); current = ""; depth = 0; }
  }
  if (current.trim()) out.push({ text: current.trim(), indented: false });
  return out;
}

/** A line without its comment: a # outside quotes starts one. */
function withoutComment(line) {
  let quote = null;
  for (let i = 0; i < line.length; i++) {
    const char = line[i];
    if (quote) { if (char === quote) quote = null; } else if (char === '"' || char === "'") quote = char;
    else if (char === "#") return line.slice(0, i);
  }
  return line;
}

const TRIPLE_QUOTE = /"{3}|'{3}/;

/**
 * A statement that may bind names this reader does not follow: several
 * statements on one line, x = y = …, :=, or a multi-line string. Nothing
 * after it can be trusted, so no formula is shown.
 */
function bindsHidden(text) {
  const bare = text.replace(/"[^"]*"|'[^']*'/g, "");
  return TRIPLE_QUOTE.test(text) || bare.includes(";") || bare.includes(":=") || (bare.replace(/[=!<>]=/g, "").match(/=/g) ?? []).length > 1;
}

/** name → resolved expression for every assignment, in order; a dict result gives one entry per key. */
function steps(code) {
  const known = new Map();
  for (const { text, indented } of statements(code)) {
    if (bindsHidden(text)) return known.set("__stop__", true), known;
    if (/^print\s*\(/.test(text)) continue;
    const match = text.match(ASSIGN);
    // Anything else (a loop, an if, a def) may change any name: stop trusting what follows.
    if (!match || indented) {
      if (match) known.set(match[1], UNKNOWN);
      if (!match && !indented) return known.set("__stop__", true), known;
      continue;
    }
    const [, name, body] = match;
    if (body.startsWith("{")) {
      // result = {"diff": diff, "pct": round(pct, 2)}
      const tokens = tokenize(body);
      known.set(name, UNKNOWN);
      // A dict result: its own entries only, never a variable that happens to share a key's name.
      known.set(`${name}.__dict__`, true);
      if (!tokens || tokens.at(-1)?.value !== "}") continue;
      const inner = tokens.slice(1, -1);
      for (let i = 0; i < inner.length;) {
        if (inner[i].type !== "str" || inner[i + 1]?.value !== ":") break;
        let end = i + 2;
        let depth = 0;
        while (end < inner.length && !(depth === 0 && inner[end].value === ",")) { if ("([{".includes(inner[end].value)) depth++; if (")]}".includes(inner[end].value)) depth--; end++; }
        // Kept apart from the variables: {"diff": diff} must not make diff point at itself.
        known.set(`${name}.${inner[i].value}`, resolve(parse(inner.slice(i + 2, end)), known));
        i = end + 1;
      }
      continue;
    }
    const tokens = tokenize(body);
    known.set(name, tokens ? resolve(parse(tokens), known) : UNKNOWN);
  }
  return known;
}

const RANK = { "+": 1, "-": 1, "*": 2, "/": 2 };
const SHOWN = { "+": " + ", "-": " − ", "*": " × ", "/": " ÷ " };

/** Pieces to render: {cell: key} or {text}. Brackets only where the order needs them. */
function print(tree, out, parentOp = null, rightSide = false) {
  const parentRank = RANK[parentOp] ?? 0;
  if (tree.cell) { out.push({ cell: tree.cell }); return; }
  if (tree.num) { out.push({ text: tree.num.replace(".", ",") }); return; }
  if (tree.op === "neg") {
    // "−a × 2" reads right; "b × −a" needs the bracket.
    const wrap = rightSide && parentRank > 0;
    out.push({ text: wrap ? "(−" : "−" });
    print(tree.inner, out, "neg");
    if (wrap) out.push({ text: ")" });
    return;
  }
  if (tree.op === "abs") { out.push({ text: "|" }); print(tree.inner, out); out.push({ text: "|" }); return; }
  const rank = RANK[tree.op];
  // The parent decides: a − (b + c) and a ÷ (b × c) keep their brackets, a + (b − c) does not need one.
  const wrap = parentOp === "neg" || rank < parentRank || (rightSide && rank === parentRank && (parentOp === "-" || parentOp === "/"));
  if (wrap) out.push({ text: "(" });
  print(tree.left, out, tree.op);
  out.push({ text: SHOWN[tree.op] });
  print(tree.right, out, tree.op, true);
  if (wrap) out.push({ text: ")" });
}

/** A round() anywhere but the outside changes the result in a way the formula cannot show. */
const hasRound = (tree) => Boolean(tree) && (tree.op === "round" || hasRound(tree.inner) || hasRound(tree.left) || hasRound(tree.right));

/**
 * The formula behind one result of a script: `target` is the name the script
 * gave that result ("pct"), or null for its single result. Null when the
 * result is more than plain arithmetic, or only copies one cell.
 */
export function readableFormula(code, target = null) {
  const known = steps(code);
  if (known.get("__stop__")) {
    // A statement the reader does not follow (a loop, an if): nothing after it can be trusted.
    return null;
  }
  const tree = known.get("result.__dict__")
    ? (target != null ? known.get(`result.${target}`) : undefined)
    : [target != null ? known.get(target) : undefined, known.get("result")].find((value) => value !== undefined);
  if (!tree || tree === UNKNOWN) return null;
  // round(x, 2) around the whole result is shown as x: the result line already shows the rounding.
  let shown = tree;
  while (shown.op === "round") shown = shown.inner;
  if (shown.cell || shown.num || hasRound(shown)) return null;
  const out = [];
  print(shown, out);
  // Merge neighbouring text so the renderer gets few pieces.
  return out.reduce((acc, piece) => {
    if (piece.text != null && acc.at(-1)?.text != null) acc[acc.length - 1] = { text: acc.at(-1).text + piece.text };
    else acc.push(piece);
    return acc;
  }, []);
}
