/** @vitest-environment jsdom */
import { describe, expect, it, beforeEach, afterEach } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { ThemeProvider, useTheme } from "./ThemeProvider.jsx";

function Probe() {
  const { preference, resolvedTheme, setPreference } = useTheme();
  return <div><output>{preference}:{resolvedTheme}</output><button onClick={() => setPreference("dark")}>dark</button></div>;
}

describe("ThemeProvider", () => {
  afterEach(cleanup);
  beforeEach(() => {
    localStorage.clear();
    Object.defineProperty(window, "matchMedia", { configurable: true, value: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }) });
  });

  it("applies a persisted dark preference to the document root", () => {
    localStorage.setItem("sourcelens-theme", "dark");
    render(<ThemeProvider><Probe /></ThemeProvider>);
    expect(screen.getByText("dark:dark")).toBeTruthy();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("updates preference through the shared command", () => {
    render(<ThemeProvider><Probe /></ThemeProvider>);
    fireEvent.click(screen.getByRole("button", { name: "dark" }));
    expect(screen.getByText("dark:dark")).toBeTruthy();
  });
});
