import { expect, it } from "vitest";
import { readableFormula } from "./formulaView.js";

const show = (pieces) => pieces?.map((piece) => (piece.cell ? `[${piece.cell}]` : piece.text)).join("") ?? null;

it("reads a growth script with a dict result as the formula of the asked result", () => {
  const code = "q1 = value('a')\nq2 = value('b')\ndiff = q2 - q1\npct = round((diff / q1) * 100, 2)\nresult = {\"diff\": diff, \"pct\": pct}";
  expect(show(readableFormula(code, "pct"))).toBe("([b] − [a]) ÷ [a] × 100");
  expect(show(readableFormula(code, "diff"))).toBe("[b] − [a]");
});

it("reads a share script with a single result", () => {
  expect(show(readableFormula("dt = value('north')\ntong = value(\"total\")\nresult = round((dt / tong) * 100, 2)"))).toBe("[north] ÷ [total] × 100");
});

it("keeps the brackets the order needs and drops the others", () => {
  expect(show(readableFormula("result = value('a') - (value('b') - value('c'))"))).toBe("[a] − ([b] − [c])");
  expect(show(readableFormula("result = (value('a') + value('b')) + value('c')"))).toBe("[a] + [b] + [c]");
  expect(show(readableFormula("result = value('a') / (value('b') * 2.5)"))).toBe("[a] ÷ ([b] × 2,5)");
});

it("gives nothing for a script that is more than arithmetic, or that only copies a cell", () => {
  expect(readableFormula("rows = [value('a'), value('b')]\nresult = max(rows)")).toBeNull();
  expect(readableFormula("for x in range(3):\n  pass")).toBeNull();
  expect(readableFormula("result = value('a')")).toBeNull();
});

it("reads scripts as the AI writes them: print lines, Decimal numbers, Vietnamese names, dicts over several lines", () => {
  expect(show(readableFormula("q1 = value('a')\nq2 = value('b')\nresult = q1 + q2\nprint(result)"))).toBe("[a] + [b]");
  expect(show(readableFormula("t = value('a')\nty_le = value('b') / Decimal('100')\nresult = round(t * ty_le, 2)"))).toBe("[a] × [b] ÷ 100");
  expect(show(readableFormula("dt_miền_trung = value('a')\ntổng = value('b')\nresult = dt_miền_trung / tổng * 100"))).toBe("[a] ÷ [b] × 100");
  const multiline = "q1 = value('a')\nq2 = value('b')\ntotal = q1 + q2\nresult = {\n    'total': total,\n    'pct': round(q2 / q1 * 100, 2),\n}";
  expect(show(readableFormula(multiline, "total"))).toBe("[a] + [b]");
  expect(show(readableFormula(multiline, "pct"))).toBe("[b] ÷ [a] × 100");
});

it("reads a reassigned name as it was at that line, and skips only the lines it cannot read", () => {
  expect(show(readableFormula("x = value('a')\nx = x - value('b')\nresult = x * 2"))).toBe("([a] − [b]) × 2");
  const mixed = "a = value('a')\nb = value('b')\nsame = a == b\nresult = {'same': same, 'gap': b - a}";
  expect(readableFormula(mixed, "same")).toBeNull();
  expect(show(readableFormula(mixed, "gap"))).toBe("[b] − [a]");
});

it("never shows a formula for powers, integer division, or what follows a loop", () => {
  expect(readableFormula("result = value('a') ** 2")).toBeNull();
  expect(readableFormula("result = value('a') // 2")).toBeNull();
  expect(readableFormula("t = value('a')\nfor i in range(2):\n    t = t + 1\nresult = t * 2")).toBeNull();
  expect(show(readableFormula("result = -value('a') * 2"))).toBe("−[a] × 2");
  expect(show(readableFormula("result = value('b') * -value('a')"))).toBe("[b] × (−[a])");
});

it("keeps the brackets that change the result", () => {
  expect(show(readableFormula("result = value('a') - (value('b') + value('c'))"))).toBe("[a] − ([b] + [c])");
  expect(show(readableFormula("result = value('a') + (value('b') - value('c'))"))).toBe("[a] + [b] − [c]");
  expect(show(readableFormula("result = value('a') / (value('b') / value('c'))"))).toBe("[a] ÷ ([b] ÷ [c])");
  expect(show(readableFormula("result = -(value('a') + value('b'))"))).toBe("−([a] + [b])");
});

it("shows no formula when a rounding happens inside the calculation", () => {
  expect(readableFormula("result = round(value('a') / value('b'), 3) * 100")).toBeNull();
  expect(readableFormula("p = round(value('a') / value('b'), 3)\nresult = p * 100")).toBeNull();
  expect(show(readableFormula("p = value('a') / value('b') * 100\nresult = round(p, 2)"))).toBe("[a] ÷ [b] × 100");
});

it("shows nothing when a statement may bind names it cannot follow", () => {
  expect(readableFormula("y = value('a')\nx = y = value('b') - value('c')\nresult = y - value('d')")).toBeNull();
  expect(readableFormula("y = value('a')\nx = (y := value('b')) + 1\nresult = y - value('d')")).toBeNull();
  expect(readableFormula("b = value('p')\na = value('x'); b = value('y')\nresult = b - value('q')")).toBeNull();
  expect(readableFormula("y = value('a')\nprint(y := value('z'))\nresult = y - value('d')")).toBeNull();
  expect(readableFormula("y = value('a')\nnote = \"\"\"\ny = value('b')\n\"\"\"\nresult = y - value('d')")).toBeNull();
  expect(show(readableFormula("a = value('x')  # it's the north\nb = value('y')  # see # here\nresult = a <= b and a - b if False else a - b"))).toBeNull();
});

it("never takes a variable in place of a dict entry it could not read", () => {
  const code = "growth = value('a') - value('b')\nresult = {\"growth\": round(growth / value('b') * 100, 2),  # it's % change\n}";
  expect(show(readableFormula(code, "growth"))).toBe("([a] − [b]) ÷ [b] × 100");
  expect(readableFormula("growth = value('a') - value('b')\nresult = {k: growth for k in 'x'}", "growth")).toBeNull();
});
