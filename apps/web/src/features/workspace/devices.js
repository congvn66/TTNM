// "Chrome · macOS" from a browser user agent. Edge and Opera also say Chrome, and Chrome also says Safari, so order matters.
const BROWSERS = [[/Edg\//, "Edge"], [/OPR\//, "Opera"], [/Chrome\//, "Chrome"], [/Firefox\//, "Firefox"], [/Safari\//, "Safari"]];
const SYSTEMS = [[/iPhone|iPad/, "iOS"], [/Android/, "Android"], [/Mac OS X/, "macOS"], [/Windows/, "Windows"], [/Linux/, "Linux"]];
export const OTHER_DEVICE = "Thiết bị khác";

/** A readable name; scripts and unknown clients (no browser, no system) are "Thiết bị khác". */
export function describeDevice(userAgent = "") {
  const browser = BROWSERS.find(([pattern]) => pattern.test(userAgent ?? ""))?.[1];
  const system = SYSTEMS.find(([pattern]) => pattern.test(userAgent ?? ""))?.[1];
  const parts = [browser, system].filter(Boolean);
  return parts.length ? parts.join(" · ") : OTHER_DEVICE;
}

/** "hôm nay 13:30" or "28/11/2026 13:30": minutes are enough here. */
export function formatSeen(value, now = new Date()) {
  const time = Date.parse(value ?? "");
  if (!Number.isFinite(time)) return "";
  const date = new Date(time);
  const clock = date.toLocaleTimeString("vi-VN", { hour: "2-digit", minute: "2-digit" });
  if (date.toDateString() === now.toDateString()) return `hôm nay ${clock}`;
  return `${date.toLocaleDateString("vi-VN", { day: "2-digit", month: "2-digit", year: "numeric" })} ${clock}`;
}

/**
 * Sign-ins grouped by device name, newest first. This device is always its own row on top;
 * the others with the same name share one row that signs them all out.
 */
export function groupSessions(sessions = []) {
  const groups = new Map();
  for (const session of sessions) {
    const name = describeDevice(session.user_agent);
    const key = session.current ? "current" : name;
    const group = groups.get(key) ?? { key, name, current: Boolean(session.current), sessions: [], lastSeen: "" };
    group.sessions.push(session);
    if (String(session.last_seen_at ?? "") > group.lastSeen) group.lastSeen = String(session.last_seen_at ?? "");
    groups.set(key, group);
  }
  return [...groups.values()].sort((a, b) => Number(b.current) - Number(a.current) || b.lastSeen.localeCompare(a.lastSeen));
}
