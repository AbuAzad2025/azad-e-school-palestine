/* منصة مدرسة أزاد الإلكترونية — سلوكيات الواجهة */
(() => {
  const THEME_KEY = "azad-theme";

  function applyTheme(theme) {
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

  function initTheme() {
    const saved = localStorage.getItem(THEME_KEY) || "system";
    applyTheme(saved);
    const btn = document.querySelector("[data-theme-toggle]");
    if (btn) {
      btn.addEventListener("click", () => {
        const current = localStorage.getItem(THEME_KEY) || "system";
        const next = current === "dark" ? "light" : "dark";
        localStorage.setItem(THEME_KEY, next);
        applyTheme(next);
      });
    }
  }

  function initNav() {
    const toggle = document.querySelector("[data-nav-toggle]");
    const links = document.querySelector("[data-nav-links]");
    if (toggle && links) {
      const setOpen = (open) => {
        links.classList.toggle("open", open);
        toggle.setAttribute("aria-expanded", String(open));
        const openIcon = toggle.querySelector("[data-nav-icon-open]");
        const closeIcon = toggle.querySelector("[data-nav-icon-close]");
        if (openIcon) openIcon.hidden = open;
        if (closeIcon) closeIcon.hidden = !open;
      };
      toggle.addEventListener("click", () => setOpen(!links.classList.contains("open")));
      links.querySelectorAll("a, button").forEach((el) => {
        el.addEventListener("click", () => setOpen(false));
      });
    }
  }

  function initAdminDrawer() {
    const close = () => document.body.classList.remove("sidebar-open");
    const openBtn = document.querySelector("[data-admin-nav-toggle]");
    const closeBtn = document.querySelector("[data-admin-nav-close]");
    const overlay = document.querySelector("[data-admin-nav-overlay]");
    if (openBtn)
      openBtn.addEventListener("click", () => document.body.classList.add("sidebar-open"));
    if (closeBtn) closeBtn.addEventListener("click", close);
    if (overlay) overlay.addEventListener("click", close);
  }

  function initFlashes() {
    document.querySelectorAll(".flash").forEach((el) => {
      setTimeout(() => {
        el.style.opacity = "0";
        el.style.transition = "opacity .4s";
        setTimeout(() => el.remove(), 450);
      }, 5000);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    initNav();
    initAdminDrawer();
    initFlashes();
  });
})();
