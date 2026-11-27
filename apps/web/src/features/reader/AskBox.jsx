import { forwardRef, useEffect, useState } from "react";

/** Example questions come from the report itself, so they never invite one it cannot answer. */
export const AskBox = forwardRef(function AskBox({ value, onChange, onSubmit, asking, disabled, note, examples = [] }, ref) {
  const [example, setExample] = useState(0);
  useEffect(() => {
    if (value || examples.length < 2) return undefined;
    const timer = window.setInterval(() => setExample((index) => (index + 1) % examples.length), 4000);
    return () => window.clearInterval(timer);
  }, [value, examples.length]);
  // A phone has room for one short line; the example questions are too long for it.
  const narrow = typeof window !== "undefined" && window.matchMedia?.("(max-width: 700px)").matches;
  const placeholder = examples.length && !narrow ? `Ví dụ: ${examples[example % examples.length]}` : "Hỏi về số liệu trong báo cáo…";
  const submit = (event) => { event.preventDefault(); if (!asking && !disabled && value.trim()) onSubmit(value); };
  return <form className="rd-ask" onSubmit={submit} data-tour="ask">
    <label htmlFor="rd-ask-input" className="rd-sr">Câu hỏi về báo cáo</label>
    <textarea id="rd-ask-input" ref={ref} rows={2} value={value} disabled={disabled} placeholder={placeholder}
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); submit(event); } }} />
    <div className="rd-ask-row">
      <small>{note ?? "Enter để gửi · Shift+Enter xuống dòng"}</small>
      <button type="submit" className="rd-button primary" disabled={asking || disabled || !value.trim()}>{asking ? <><span className="rd-spinner small" aria-hidden="true" />Đang trả lời</> : "Hỏi"}</button>
    </div>
  </form>;
});
