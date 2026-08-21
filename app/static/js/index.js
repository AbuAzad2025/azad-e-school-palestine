/**
 * Azad application entry point — ES module
 */

import { initFileUploads, initInlineValidation } from "./modules/forms.js";
import { initTheme } from "./modules/theme.js";
import { initTour } from "./modules/tour.js";
import {
  initAccordions,
  initActionsDropdowns,
  initConfirmDialogs,
  initFlashes,
  initHelpTooltips,
  initPasswordToggle,
  initRipple,
  initTabs,
  initUserDropdown,
} from "./modules/ui.js";
import "./modules/search.js";
import "./modules/bulk.js";
import "./modules/charts.js";

function initNav() {
  const toggle = document.querySelector("[data-nav-toggle]");
  const links = document.querySelector("[data-nav-links]");
  if (!toggle || !links) return;

  const setOpen = (open) => {
    links.classList.toggle("open", open);
    toggle.setAttribute("aria-expanded", String(open));
    const openIcon = toggle.querySelector("[data-nav-icon-open]");
    const closeIcon = toggle.querySelector("[data-nav-icon-close]");
    if (openIcon) openIcon.hidden = open;
    if (closeIcon) closeIcon.hidden = !open;
    document.body.style.overflow = open ? "hidden" : "";
  };

  toggle.addEventListener("click", () => setOpen(!links.classList.contains("open")));
  links.addEventListener("click", (e) => {
    if (e.target.closest("a, button")) setOpen(false);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && links.classList.contains("open")) setOpen(false);
  });
}

function initAdminDrawer() {
  const close = () => document.body.classList.remove("sidebar-open");
  const openBtn = document.querySelector("[data-admin-nav-toggle]");
  const closeBtn = document.querySelector("[data-admin-nav-close]");
  const overlay = document.querySelector("[data-admin-nav-overlay]");
  if (openBtn) openBtn.addEventListener("click", () => document.body.classList.add("sidebar-open"));
  if (closeBtn) closeBtn.addEventListener("click", close);
  if (overlay) overlay.addEventListener("click", close);
}

function initScrollAnimations() {
  if (!("IntersectionObserver" in window)) return;
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("azad-in-view");
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.1, rootMargin: "0px 0px -40px 0px" },
  );

  document
    .querySelectorAll(
      ".azad-card, .azad-stat-card, .azad-item, .stat-card, .azad-action-card, .dash-card",
    )
    .forEach((el) => {
      el.style.opacity = "0";
      el.style.transform = "translateY(12px)";
      el.style.transition = "opacity .4s ease, transform .4s ease";
      observer.observe(el);
    });

  if (!document.getElementById("azad-scroll-styles")) {
    const style = document.createElement("style");
    style.id = "azad-scroll-styles";
    style.textContent =
      ".azad-in-view { opacity: 1 !important; transform: translateY(0) !important; }";
    document.head.appendChild(style);
  }
}

function initAutoDismissFlashes() {
  document
    .querySelectorAll(".flash[data-auto-dismiss], .azad-flash[data-auto-dismiss]")
    .forEach((el) => {
      const delay = parseInt(el.dataset.autoDismiss, 10) || 5000;
      setTimeout(() => {
        el.style.opacity = "0";
        el.style.transform = "translateY(-8px)";
        el.style.transition = "opacity .3s, transform .3s";
        setTimeout(() => el.remove(), 350);
      }, delay);
    });
}

function initPwaBanner() {
  const banner = document.getElementById("pwa-install-banner");
  const installBtn = document.getElementById("pwa-install-btn");
  const dismissBtn = document.getElementById("pwa-install-dismiss");
  if (!banner || !installBtn) return;

  let deferredPrompt = null;
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e;
    banner.style.display = "flex";
  });

  installBtn.addEventListener("click", async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    deferredPrompt = null;
    banner.style.display = "none";
  });

  if (dismissBtn) {
    dismissBtn.addEventListener("click", () => {
      banner.style.display = "none";
      localStorage.setItem("azad-pwa-dismissed", "1");
    });
  }
  if (localStorage.getItem("azad-pwa-dismissed")) {
    banner.style.display = "none";
  }
}

function initServiceWorker() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/static/sw.js").catch(() => {});
  }
}

function init() {
  initTheme();
  initNav();
  initAdminDrawer();
  initPasswordToggle();
  initUserDropdown();
  initActionsDropdowns();
  initConfirmDialogs();
  initHelpTooltips();
  initInlineValidation();
  initFileUploads();
  initTour();
  initAccordions();
  initTabs();
  initFlashes();
  initAutoDismissFlashes();
  initRipple();
  initScrollAnimations();
  initPwaBanner();
  initServiceWorker();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}

// Keep global toast API for inline scripts
import("./modules/toast.js").then((m) => {
  window.AzadToast = m.default;
});
