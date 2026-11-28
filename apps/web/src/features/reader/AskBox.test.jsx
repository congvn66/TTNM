/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { AskBox } from "./AskBox.jsx";

afterEach(cleanup);


it("sends with Enter", () => {
  const onSubmit = vi.fn();
  render(<AskBox value="Doanh thu quý 1?" onChange={() => {}} onSubmit={onSubmit} />);
  fireEvent.keyDown(screen.getByLabelText("Câu hỏi về báo cáo"), { key: "Enter" });
  expect(onSubmit).toHaveBeenCalledWith("Doanh thu quý 1?");
});

it("waits for the input method to commit the last word before sending", async () => {
  const onSubmit = vi.fn();
  function Box() {
    const [value, setValue] = useState("xuất khẩ");
    return <AskBox value={value} onChange={setValue} onSubmit={(text) => { onSubmit(text); setValue(""); }} />;
  }
  render(<Box />);
  const box = screen.getByLabelText("Câu hỏi về báo cáo");
  fireEvent.keyDown(box, { key: "Enter", isComposing: true });
  expect(onSubmit).not.toHaveBeenCalled();
  fireEvent.change(box, { target: { value: "xuất khẩu" } });
  fireEvent.compositionEnd(box);
  await waitFor(() => expect(onSubmit).toHaveBeenCalledWith("xuất khẩu"));
  expect(box.value).toBe("");
});

it("keeps Shift+Enter for a new line", () => {
  const onSubmit = vi.fn();
  render(<AskBox value="a" onChange={() => {}} onSubmit={onSubmit} />);
  fireEvent.keyDown(screen.getByLabelText("Câu hỏi về báo cáo"), { key: "Enter", shiftKey: true });
  expect(onSubmit).not.toHaveBeenCalled();
});
