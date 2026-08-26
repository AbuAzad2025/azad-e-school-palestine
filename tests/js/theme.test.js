import { describe, it, expect, beforeEach, vi } from "vitest";

describe("Theme - applyTheme", () => {
  beforeEach(() => {
    document.documentElement.dataset.theme = "";
    document.body.innerHTML = `
      <span data-theme-icon-light>Sun</span>
      <span data-theme-icon-dark>Moon</span>
    `;
  });

  it("sets dark theme explicitly", async () => {
    const { applyTheme } = await import("@app-static/js/core/theme.js");
    applyTheme("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("sets light theme explicitly", async () => {
    const { applyTheme } = await import("@app-static/js/core/theme.js");
    applyTheme("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("follows system preference when theme is 'system'", async () => {
    const { applyTheme } = await import("@app-static/js/core/theme.js");
    // Default matchMedia mock returns matches: false (light)
    applyTheme("system");
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("hides light icon and shows dark icon when dark", async () => {
    const { applyTheme } = await import("@app-static/js/core/theme.js");
    applyTheme("dark");
    const lightIcon = document.querySelector("[data-theme-icon-light]");
    const darkIcon = document.querySelector("[data-theme-icon-dark]");
    expect(lightIcon.hidden).toBe(true);
    expect(darkIcon.hidden).toBe(false);
  });

  it("shows light icon and hides dark icon when light", async () => {
    const { applyTheme } = await import("@app-static/js/core/theme.js");
    applyTheme("light");
    const lightIcon = document.querySelector("[data-theme-icon-light]");
    const darkIcon = document.querySelector("[data-theme-icon-dark]");
    expect(lightIcon.hidden).toBe(false);
    expect(darkIcon.hidden).toBe(true);
  });

  it("handles missing icon elements gracefully", async () => {
    document.body.innerHTML = "";
    const { applyTheme } = await import("@app-static/js/core/theme.js");
    expect(() => applyTheme("dark")).not.toThrow();
  });
});

describe("Theme - getNextTheme", () => {
  it("returns light when current is dark", async () => {
    const { getNextTheme } = await import("@app-static/js/core/theme.js");
    expect(getNextTheme("dark")).toBe("light");
  });

  it("returns dark when current is light", async () => {
    const { getNextTheme } = await import("@app-static/js/core/theme.js");
    expect(getNextTheme("light")).toBe("dark");
  });

  it("returns dark when current is system", async () => {
    const { getNextTheme } = await import("@app-static/js/core/theme.js");
    expect(getNextTheme("system")).toBe("dark");
  });
});

describe("Theme - initTheme", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.dataset.theme = "";
    document.body.innerHTML = `
      <button data-theme-toggle>Toggle</button>
      <span data-theme-icon-light>☀️</span>
      <span data-theme-icon-dark>🌙</span>
    `;
  });

  it("loads saved theme from localStorage", async () => {
    localStorage.setItem("azad-theme", "dark");
    const { initTheme } = await import("@app-static/js/core/theme.js");
    initTheme();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("defaults to system when no saved theme", async () => {
    const { initTheme } = await import("@app-static/js/core/theme.js");
    initTheme();
    // matchMedia mock returns false (light)
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("toggles theme on button click", async () => {
    localStorage.setItem("azad-theme", "light");
    const { initTheme } = await import("@app-static/js/core/theme.js");
    initTheme();

    const btn = document.querySelector("[data-theme-toggle]");
    btn.click();

    expect(localStorage.getItem("azad-theme")).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("does not toggle when clicking non-toggle element", async () => {
    localStorage.setItem("azad-theme", "light");
    const { initTheme } = await import("@app-static/js/core/theme.js");
    initTheme();

    document.body.click();
    expect(localStorage.getItem("azad-theme")).toBe("light");
  });
});
