// Problems the reader marked "Bỏ qua", kept per report in this browser so they stay
// hidden after a reload. "Hiện lại" brings them all back; "Hoàn tác" brings back one.
import { useCallback, useEffect, useState } from "react";

const STORE_KEY = "sourcelens-dismissed-v1";

function readStore() {
  try { return JSON.parse(localStorage.getItem(STORE_KEY) ?? "{}") ?? {}; } catch { return {}; }
}

export function loadDismissed(reportId) {
  const keys = reportId ? readStore()[reportId] : null;
  return new Set(Array.isArray(keys) ? keys : []);
}

export function saveDismissed(reportId, keys) {
  if (!reportId) return;
  const store = readStore();
  if (keys.size) store[reportId] = [...keys];
  else delete store[reportId];
  try { localStorage.setItem(STORE_KEY, JSON.stringify(store)); } catch { /* private mode: dismissals last until reload */ }
}

/** A failing check stays on the page and in the summary until the reader dismisses it. */
export const isOpenProblem = (check, dismissed) => !check.ok && !dismissed.has(check.chip.key);

export function useDismissed(reportId) {
  const [dismissed, setDismissed] = useState(() => loadDismissed(reportId));
  useEffect(() => { setDismissed(loadDismissed(reportId)); }, [reportId]);
  const change = useCallback((make) => setDismissed((old) => { const next = make(old); saveDismissed(reportId, next); return next; }), [reportId]);
  const dismiss = useCallback((key) => change((old) => new Set([...old, key])), [change]);
  const undismiss = useCallback((key) => change((old) => new Set([...old].filter((item) => item !== key))), [change]);
  const restore = useCallback(() => change(() => new Set()), [change]);
  return { dismissed, dismiss, undismiss, restore };
}
