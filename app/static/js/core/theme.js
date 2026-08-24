/**
 * Theme module — ES module
 */

const THEME_KEY = "azad-theme";

/**
 * Apply a light / dark / system theme to the document root.
 * @param {string} theme - One of 'light', 'dark', or 'system'.
 * @returns {void}
 */
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

/**
 * Return the next theme in the toggle cycle (dark → light → dark).
 * @param {string} current
 * @returns {string}
 */
export function getNextTheme(current) {
  return current === "dark" ? "light" : "dark";
}

/**
 * Initialise theme from localStorage and wire up toggle buttons.
 * @returns {void}
 */
export function initTheme() {
  const saved = localStorage.getItem(THEME_KEY) || "system";
  applyTheme(saved);

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-theme-toggle]");
    if (!btn) return;
    const current = localStorage.getItem(THEME_KEY) || "system";
    const next = getNextTheme(current);
    localStorage.setItem(THEME_KEY, next);
    applyTheme(next);
  });
}

export default { initTheme, applyTheme };
