/**
 * Theme module — ES module
 */

const THEME_KEY = "azad-theme";

export function applyTheme(theme) {
  const dark =
    theme === "dark" ||
    (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.querySelectorAll("[data-theme-icon-light]").forEach((el) => {
    el.hidden = dark;
  });
  document.querySelectorAll("[data-theme-icon-dark]").forEach((el) => {
    el.hidden = !dark;
  });
}

export function getNextTheme(current) {
  return current === "dark" ? "light" : "dark";
}

export function initTheme() {
  const saved = localStorage.getItem(THEME_KEY) || "system";
  applyTheme(saved);

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-theme-toggle], [data-theme-toggle-bottom]");
    if (!btn) return;
    if (btn.matches("[data-theme-toggle-bottom]")) e.preventDefault();
    const current = localStorage.getItem(THEME_KEY) || "system";
    const next = getNextTheme(current);
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
  });
}

export default { initTheme, applyTheme };
