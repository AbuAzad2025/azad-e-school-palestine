/* ═══════════════════════════════════════════════════════
   منصة مدرسة أزاد الإلكترونية — UI Engine v2.0
   ═══════════════════════════════════════════════════════ */
(() => {
  const THEME_KEY = "azad-theme";

  /* ─────────── Theme Toggle ─────────── */
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

  /* ─────────── Mobile Nav ─────────── */
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
    links.querySelectorAll("a, button").forEach((el) => {
      el.addEventListener("click", () => setOpen(false));
    });

    // Close on escape
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && links.classList.contains("open")) setOpen(false);
    });
  }

  /* ─────────── Admin Sidebar Drawer ─────────── */
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

  /* ─────────── Flash Messages Auto-Dismiss ─────────── */
  function initFlashes() {
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

  /* ─────────── Toast Notification System ─────────── */
  const AzadToast = {
    _container: null,

    _getContainer() {
      if (!this._container) {
        this._container = document.getElementById("azad-toasts");
        if (!this._container) {
          this._container = document.createElement("div");
          this._container.className = "azad-toast-container";
          this._container.id = "azad-toasts";
          this._container.setAttribute("aria-live", "polite");
          document.body.appendChild(this._container);
        }
      }
      return this._container;
    },

    _getIcon(type) {
      const icons = {
        success:
          '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6 9 17l-5-5"/></svg>',
        error:
          '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>',
        warning:
          '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/></svg>',
        info: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>',
      };
      return icons[type] || icons.info;
    },

    show(options) {
      const {
        type = "info",
        title = "",
        message = "",
        duration = 4000,
      } = typeof options === "string" ? { message: options } : options;
      const container = this._getContainer();

      const toast = document.createElement("div");
      toast.className = `azad-toast azad-toast--${type}`;
      toast.innerHTML = `
        <div class="azad-toast__icon">${this._getIcon(type)}</div>
        <div class="azad-toast__content">
          ${title ? `<div class="azad-toast__title">${title}</div>` : ""}
          <div class="azad-toast__message">${message}</div>
        </div>
        <button class="azad-toast__close" aria-label="إغلاق">
          <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
        </button>
        <div class="azad-toast__progress" style="animation-duration: ${duration}ms"></div>
      `;

      const closeBtn = toast.querySelector(".azad-toast__close");
      closeBtn.addEventListener("click", () => {
        toast.style.opacity = "0";
        toast.style.transform = "translateX(100%)";
        toast.style.transition = "all .3s";
        setTimeout(() => toast.remove(), 300);
      });

      container.appendChild(toast);

      if (duration > 0) {
        setTimeout(() => {
          if (toast.parentNode) {
            toast.style.opacity = "0";
            toast.style.transform = "translateX(100%)";
            toast.style.transition = "all .3s";
            setTimeout(() => toast.remove(), 300);
          }
        }, duration);
      }

      return toast;
    },

    success(msg, title) {
      return this.show({ type: "success", title: title || "نجح", message: msg });
    },
    error(msg, title) {
      return this.show({ type: "error", title: title || "خطأ", message: msg });
    },
    warning(msg, title) {
      return this.show({ type: "warning", title: title || "تنبيه", message: msg });
    },
    info(msg, title) {
      return this.show({ type: "info", title: title || "معلومة", message: msg });
    },
  };

  // Expose globally
  window.AzadToast = AzadToast;

  /* ─────────── Ripple Effect ─────────── */
  function initRipple() {
    document.addEventListener("click", (e) => {
      const btn = e.target.closest(
        ".azad-btn, .azad-btn-primary, .azad-btn-outline, .azad-btn-accent, .azad-btn-ghost, .azad-btn-danger, .stat-card.link, .azad-action-card",
      );
      if (!btn) return;

      const ripple = document.createElement("span");
      ripple.className = "azad-ripple";
      const rect = btn.getBoundingClientRect();
      const size = Math.max(rect.width, rect.height) * 2;
      ripple.style.width = ripple.style.height = `${size}px`;
      ripple.style.left = `${e.clientX - rect.left - size / 2}px`;
      ripple.style.top = `${e.clientY - rect.top - size / 2}px`;
      btn.style.position = btn.style.position || "relative";
      btn.style.overflow = "hidden";
      btn.appendChild(ripple);
      setTimeout(() => ripple.remove(), 600);
    });
  }

  /* ─────────── Password Toggle ─────────── */
  function initPasswordToggle() {
    document.querySelectorAll("[data-password-toggle]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const wrap = btn.closest(".azad-field__input-wrap--password");
        if (!wrap) return;
        const input = wrap.querySelector("input");
        if (!input) return;
        const isPassword = input.type === "password";
        input.type = isPassword ? "text" : "password";
        btn.innerHTML = isPassword
          ? '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>'
          : '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>';
      });
    });
  }

  /* ─────────── IntersectionObserver (animate on scroll) ─────────── */
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

    // Add the visible class style
    if (!document.getElementById("azad-scroll-styles")) {
      const style = document.createElement("style");
      style.id = "azad-scroll-styles";
      style.textContent =
        ".azad-in-view { opacity: 1 !important; transform: translateY(0) !important; }";
      document.head.appendChild(style);
    }
  }

  /* ─────────── Accordion ─────────── */
  function initAccordions() {
    document.querySelectorAll(".accordion-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const expanded = btn.getAttribute("aria-expanded") === "true";
        btn.setAttribute("aria-expanded", String(!expanded));
        const content = btn.nextElementSibling;
        if (content) content.classList.toggle("open", !expanded);
      });
    });
  }

  /* ─────────── Tabs ─────────── */
  function initTabs() {
    document.querySelectorAll(".tabs").forEach((tabBar) => {
      const tabs = tabBar.querySelectorAll(".tab");
      tabs.forEach((tab) => {
        tab.addEventListener("click", (e) => {
          e.preventDefault();
          tabs.forEach((t) => {
            t.classList.remove("active");
          });
          tab.classList.add("active");
        });
      });
    });
  }

  /* ─────────── Dropdown ─────────── */
  function initDropdowns() {
    document.querySelectorAll(".dropdown-toggle").forEach((toggle) => {
      toggle.addEventListener("click", (e) => {
        e.stopPropagation();
        const dropdown = toggle.closest(".dropdown");
        const wasOpen = dropdown.classList.contains("open");
        // Close all open dropdowns
        document.querySelectorAll(".dropdown.open").forEach((d) => {
          d.classList.remove("open");
        });
        if (!wasOpen) dropdown.classList.add("open");
      });
    });
    document.addEventListener("click", () => {
      document.querySelectorAll(".dropdown.open").forEach((d) => {
        d.classList.remove("open");
      });
    });
  }

  /* ─────────── Smooth Page Transitions ─────────── */
  function initPageTransitions() {
    document.querySelectorAll('a[href^="/"]').forEach((link) => {
      if (link.target === "_blank" || link.hasAttribute("download")) return;
      link.addEventListener("click", (_e) => {
        const href = link.getAttribute("href");
        if (!href || href === window.location.pathname) return;
        document.body.style.opacity = "0.7";
        document.body.style.transition = "opacity .15s";
      });
    });
    window.addEventListener("pageshow", () => {
      document.body.style.opacity = "1";
    });
  }

  /* ─────────── Init All ─────────── */
  document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    initNav();
    initAdminDrawer();
    initFlashes();
    initRipple();
    initPasswordToggle();
    initScrollAnimations();
    initAccordions();
    initTabs();
    initDropdowns();
    initPageTransitions();
  });
})();
