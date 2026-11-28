import { useEffect, useRef, useState } from "react";

const SOUND_KEY = "sourcelens-sound";
let audioContext = null;

export function soundEnabled() {
  try { return localStorage.getItem(SOUND_KEY) !== "off"; } catch { return true; }
}
export function setSoundEnabled(on) {
  try { localStorage.setItem(SOUND_KEY, on ? "on" : "off"); } catch { /* ignore */ }
}

/** Browsers only allow sound after a click, so the upload click unlocks it. */
export function unlockSound() {
  try {
    const Context = window.AudioContext || window.webkitAudioContext;
    if (!Context) return;
    audioContext = audioContext ?? new Context();
    if (audioContext.state === "suspended") audioContext.resume();
  } catch { /* no audio */ }
}

/** Two soft rising notes. */
export function playChime() {
  if (!soundEnabled()) return;
  try {
    unlockSound();
    if (!audioContext) return;
    const now = audioContext.currentTime;
    [[659.25, 0], [880, 0.14]].forEach(([frequency, delay]) => {
      const oscillator = audioContext.createOscillator();
      const gain = audioContext.createGain();
      oscillator.type = "sine";
      oscillator.frequency.value = frequency;
      gain.gain.setValueAtTime(0.0001, now + delay);
      gain.gain.exponentialRampToValueAtTime(0.18, now + delay + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, now + delay + 0.5);
      oscillator.connect(gain).connect(audioContext.destination);
      oscillator.start(now + delay);
      oscillator.stop(now + delay + 0.55);
    });
  } catch { /* no audio */ }
}

/**
 * Fires once when a watched report goes from "being read" to "ready" (or "failed"):
 * chime, tab title, and an event the screen turns into a toast.
 */
export function useReadySignal(reports, onSignal, watched = () => true) {
  const previous = useRef(new Map());
  const first = useRef(true);
  const callback = useRef(onSignal);
  callback.current = onSignal;
  const watch = useRef(watched);
  watch.current = watched;
  useEffect(() => {
    const before = previous.current;
    const next = new Map(reports.map((report) => [report.id, report.extraction_status]));
    if (!first.current) {
      for (const report of reports) {
        const was = before.get(report.id);
        // Only reports the person is waiting for: on a shared account other people's uploads stay quiet.
        if (!["queued", "processing"].includes(was) || !watch.current(report)) continue;
        if (report.extraction_status === "ready") {
          playChime();
          flashTitle(`✓ Đã đọc xong · ${report.file_name}`);
          callback.current?.({ kind: "ready", report });
        } else if (report.extraction_status === "failed") {
          flashTitle(`Không đọc được · ${report.file_name}`);
          callback.current?.({ kind: "failed", report });
        }
      }
    }
    first.current = false;
    previous.current = next;
  }, [reports]);
}

let titleTimer = null;
function flashTitle(text) {
  const original = "SourceLens";
  window.clearTimeout(titleTimer);
  document.title = text;
  const restore = () => { document.title = original; window.removeEventListener("focus", restore); };
  if (document.hasFocus()) titleTimer = window.setTimeout(restore, 6000);
  else window.addEventListener("focus", restore);
}

/** Seconds since a moment, ticking once a second. */
export function useElapsed(since) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!since) return undefined;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [since]);
  return since ? Math.max(0, Math.round((now - since) / 1000)) : 0;
}
