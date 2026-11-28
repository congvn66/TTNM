/** @vitest-environment jsdom */
import { afterEach, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { AnswerText, answerBlocks } from "./AnswerText.jsx";

afterEach(cleanup);

it("splits an answer into paragraphs and lists", () => {
  expect(answerBlocks("Doanh thu tăng:\n - Miền Bắc: 3.110\n - Miền Nam: 1.490\n\nCả hai miền tăng.\n1. Một\n2) Hai")).toEqual([
    { type: "p", lines: ["Doanh thu tăng:"] },
    { type: "ul", lines: ["Miền Bắc: 3.110", "Miền Nam: 1.490"] },
    { type: "p", lines: ["Cả hai miền tăng."] },
    { type: "ol", lines: ["Một", "Hai"] },
  ]);
});

it("renders bold and lists as elements and never runs markup from the text", () => {
  const view = render(<div><AnswerText text={"Tăng **3.110** <img src=x onerror=alert(1)>\n- **Bắc**: 3.110"} /></div>);
  expect(view.container.querySelector("p.answer-lead strong").textContent).toBe("3.110");
  expect(view.container.querySelector("ul.answer-list li strong").textContent).toBe("Bắc");
  expect(view.container.querySelector("img")).toBeNull();
  expect(view.container.textContent).toContain("<img src=x onerror=alert(1)>");
});
