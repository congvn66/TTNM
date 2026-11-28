import { forwardRef, useRef } from "react";
import { Icon } from "./Icon.jsx";

export const AskBox = forwardRef(function AskBox({ value, onChange, onSubmit, asking, disabled, note, suggestions = [], suggestionsLabel = "" }, ref) {
  const send = (text) => { if (!asking && !disabled && text.trim()) onSubmit(text); };
  const submit = (event) => { event.preventDefault(); send(value); };
  // Enter pressed while a Vietnamese input method still holds the last word:
  // send after the word is committed, or the input method types it again into
  // the emptied box.
  const sendAfterComposition = useRef(false);
  return <form className="rd-ask" onSubmit={submit}>
    {suggestions.length > 0 && <div className="rd-asksugs" id="rd-asksugs" role="group" aria-labelledby="rd-asksugs-label"><span id="rd-asksugs-label">{suggestionsLabel}</span>{suggestions.map((question) => <button type="button" key={question} disabled={asking} onClick={() => onSubmit(question)}>{question}</button>)}</div>}
    <label htmlFor="rd-ask-input" className="rd-sr">Câu hỏi về báo cáo</label>
    <textarea id="rd-ask-input" ref={ref} rows={2} value={value} disabled={disabled} placeholder="Hỏi về báo cáo này"
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={(event) => {
        if (event.key !== "Enter" || event.shiftKey) return;
        event.preventDefault();
        if (event.nativeEvent.isComposing) sendAfterComposition.current = true;
        else send(event.currentTarget.value);
      }}
      onCompositionEnd={(event) => {
        if (!sendAfterComposition.current) return;
        sendAfterComposition.current = false;
        const text = event.currentTarget.value;
        setTimeout(() => send(text), 0);
      }} />
    <div className="rd-ask-row">
      {note && <small>{note}</small>}
      <button type="submit" className="rd-button primary rd-send" aria-label={asking ? "Đang trả lời" : "Gửi"} title="Gửi" disabled={asking || disabled || !value.trim()}>{asking ? <span className="rd-spinner small" aria-hidden="true" /> : <Icon name="send" size={16} />}</button>
    </div>
  </form>;
});
