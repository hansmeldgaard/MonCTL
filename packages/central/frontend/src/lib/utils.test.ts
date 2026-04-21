import { describe, expect, it, afterEach, vi } from "vitest";
import { formatBytes, formatUptime, timeAgo } from "./utils.ts";

describe("formatBytes", () => {
  it("renders 0 bytes as '0 B'", () => {
    expect(formatBytes(0)).toBe("0 B");
  });

  it("keeps sub-1-KB values in bytes", () => {
    expect(formatBytes(512)).toBe("512 B");
  });

  it("switches to KB and keeps one decimal for small magnitudes", () => {
    expect(formatBytes(1536)).toBe("1.5 KB");
  });

  it("rounds values ≥ 10 to whole units", () => {
    expect(formatBytes(20 * 1024)).toBe("20 KB");
    expect(formatBytes(100 * 1024 * 1024)).toBe("100 MB");
  });

  it("handles GB and TB scales", () => {
    // Values < 10 keep one decimal; values ≥ 10 are rounded
    expect(formatBytes(5 * 1024 ** 3)).toBe("5.0 GB");
    expect(formatBytes(50 * 1024 ** 3)).toBe("50 GB");
    expect(formatBytes(2 * 1024 ** 4)).toBe("2.0 TB");
  });
});

describe("formatUptime", () => {
  it("shows seconds for under a minute", () => {
    expect(formatUptime(45)).toBe("45s");
  });

  it("shows minutes for under an hour", () => {
    expect(formatUptime(5 * 60)).toBe("5m");
  });

  it("shows hours + minutes for under a day", () => {
    expect(formatUptime(3 * 3600 + 20 * 60)).toBe("3h 20m");
  });

  it("shows days + hours for multi-day uptimes", () => {
    expect(formatUptime(2 * 86400 + 5 * 3600)).toBe("2d 5h");
  });
});

describe("timeAgo", () => {
  const FIXED_NOW = new Date("2026-04-21T12:00:00Z").getTime();

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns 'never' for null / undefined / invalid input", () => {
    expect(timeAgo(null)).toBe("never");
    expect(timeAgo(undefined)).toBe("never");
    expect(timeAgo("not-a-date")).toBe("never");
  });

  it("returns 'just now' for future timestamps (clock skew)", () => {
    vi.setSystemTime(FIXED_NOW);
    expect(timeAgo("2026-04-21T13:00:00Z")).toBe("just now");
  });

  it("reports seconds / minutes / hours / days / months", () => {
    vi.setSystemTime(FIXED_NOW);
    expect(timeAgo("2026-04-21T11:59:30Z")).toBe("30s ago");
    expect(timeAgo("2026-04-21T11:55:00Z")).toBe("5m ago");
    expect(timeAgo("2026-04-21T09:00:00Z")).toBe("3h ago");
    expect(timeAgo("2026-04-15T12:00:00Z")).toBe("6d ago");
    expect(timeAgo("2026-02-15T12:00:00Z")).toBe("2mo ago");
  });
});
