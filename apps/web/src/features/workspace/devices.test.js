import { describe, expect, it } from "vitest";
import { describeDevice, formatSeen, groupSessions } from "./devices.js";

describe("device list", () => {
  it("names a device by browser and system, and anything else as another device", () => {
    expect(describeDevice("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")).toBe("Chrome · macOS");
    expect(describeDevice("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0")).toBe("Edge · Windows");
    expect(describeDevice("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1")).toBe("Safari · iOS");
    expect(describeDevice("python-requests/2.34.2")).toBe("Thiết bị khác");
    expect(describeDevice("node")).toBe("Thiết bị khác");
    expect(describeDevice(null)).toBe("Thiết bị khác");
  });

  it("groups other sign-ins of the same device and keeps this device first", () => {
    const mac = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/131.0.0.0 Safari/537.36";
    const groups = groupSessions([
      { id: "a", user_agent: mac, last_seen_at: "2026-11-28T10:00:00Z" },
      { id: "b", user_agent: "python-requests/2.34.2", last_seen_at: "2026-11-28T12:00:00Z" },
      { id: "c", user_agent: mac, last_seen_at: "2026-11-28T11:00:00Z", current: true },
      { id: "d", user_agent: mac, last_seen_at: "2026-11-28T09:00:00Z" },
    ]);
    expect(groups.map((group) => [group.name, group.current, group.sessions.map((s) => s.id)])).toEqual([
      ["Chrome · macOS", true, ["c"]],
      ["Thiết bị khác", false, ["b"]],
      ["Chrome · macOS", false, ["a", "d"]],
    ]);
    expect(groups[2].lastSeen).toBe("2026-11-28T10:00:00Z");
  });

  it("shows the time without seconds", () => {
    const now = new Date("2026-11-28T15:00:00");
    expect(formatSeen("2026-11-28T13:30:39", now)).toMatch(/^hôm nay 13:30$/);
    expect(formatSeen("2026-11-20T08:05:00", now)).toMatch(/20\/11\/2026 08:05$/);
    expect(formatSeen("", now)).toBe("");
  });
});
