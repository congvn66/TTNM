import { useEffect, useRef } from "react";

/**
 * Calls poll() every `ms` while `active`, starting the next call only after the
 * previous one settles. A fixed interval would overlap slow responses (a cloud
 * database can take longer than `ms`), and a loader that keeps only its newest
 * response would then drop every one of them.
 */
export function usePolling(active, poll, ms) {
  const pollRef = useRef(poll);
  pollRef.current = poll;
  useEffect(() => {
    if (!active) return undefined;
    let stopped = false;
    let timer;
    const next = () => {
      timer = window.setTimeout(async () => {
        try { await pollRef.current(); } catch { /* the next round tries again */ }
        if (!stopped) next();
      }, ms);
    };
    next();
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [active, ms]);
}
