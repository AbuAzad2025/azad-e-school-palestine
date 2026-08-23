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
    const bottomBtn = document.querySelector("[data-theme-toggle-bottom]");
    if (bottomBtn) {
      bottomBtn.addEventListener("click", (e) => {
        e.preventDefault();
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

  /* ─────────── Mobile Bottom Nav: Scroll Behavior ─────────── */
  function initBottomNav() {
    const nav = document.querySelector(".azad-bottom-nav");
    if (!nav) return;
    let lastY = window.scrollY;
    let ticking = false;

    window.addEventListener(
      "scroll",
      () => {
        if (!ticking) {
          window.requestAnimationFrame(() => {
            const curY = window.scrollY;
            if (curY > lastY && curY > 120) {
              nav.classList.add("hide-on-scroll");
            } else {
              nav.classList.remove("hide-on-scroll");
            }
            lastY = curY;
            ticking = false;
          });
          ticking = true;
        }
      },
      { passive: true },
    );
  }

  /* ─────────── Touch Gestures ─────────── */
  function initTouchGestures() {
    const SWIPE_THRESHOLD = 40;

    function addSwipeListener(el, callbacks) {
      let startX = 0,
        startY = 0,
        swiping = false;
      el.addEventListener(
        "touchstart",
        (e) => {
          startX = e.touches[0].clientX;
          startY = e.touches[0].clientY;
          swiping = true;
        },
        { passive: true },
      );
      el.addEventListener("touchmove", () => {}, { passive: true });
      el.addEventListener(
        "touchend",
        (e) => {
          if (!swiping) return;
          swiping = false;
          const dx = e.changedTouches[0].clientX - startX;
          const dy = e.changedTouches[0].clientY - startY;
          if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > SWIPE_THRESHOLD) {
            if (dx > 0 && callbacks.right) callbacks.right(e);
            if (dx < 0 && callbacks.left) callbacks.left(e);
          }
        },
        { passive: true },
      );
    }

    const navLinks = document.querySelector("[data-nav-links]");
    if (navLinks) {
      addSwipeListener(navLinks, {
        left: () => {
          if (navLinks.classList.contains("open")) {
            navLinks.classList.remove("open");
            document.body.style.overflow = "";
            const navToggle = document.querySelector("[data-nav-toggle]");
            if (navToggle) navToggle.setAttribute("aria-expanded", "false");
          }
        },
      });
    }

    const sidebar = document.querySelector(".admin-sidebar");
    if (sidebar) {
      addSwipeListener(document.body, {
        right: (e) => {
          if (window.innerWidth < 1024 && !document.body.classList.contains("sidebar-open")) {
            const touchX = e.changedTouches[0].clientX;
            const isRTL = document.documentElement.dir === "rtl";
            const nearEdge = isRTL ? touchX > window.innerWidth - 30 : touchX < 30;
            if (nearEdge) document.body.classList.add("sidebar-open");
          }
        },
        left: () => {
          if (document.body.classList.contains("sidebar-open")) {
            document.body.classList.remove("sidebar-open");
          }
        },
      });
    }

    document.querySelectorAll(".tabs").forEach((tabBar) => {
      addSwipeListener(tabBar, {
        left: () => {
          const active = tabBar.querySelector(".tab.active");
          if (active?.nextElementSibling?.classList.contains("tab")) {
            active.nextElementSibling.click();
          }
        },
        right: () => {
          const active = tabBar.querySelector(".tab.active");
          if (active?.previousElementSibling?.classList.contains("tab")) {
            active.previousElementSibling.click();
          }
        },
      });
    });

    let longPressTimer = null;
    document.querySelectorAll(".azad-item, .azad-card").forEach((el) => {
      el.addEventListener(
        "touchstart",
        () => {
          longPressTimer = setTimeout(() => {
            el.style.transform = "scale(0.97)";
            el.style.transition = "transform 0.15s";
            setTimeout(() => {
              el.style.transform = "";
              el.style.transition = "";
            }, 300);
          }, 500);
        },
        { passive: true },
      );
      el.addEventListener(
        "touchend",
        () => {
          clearTimeout(longPressTimer);
        },
        { passive: true },
      );
      el.addEventListener(
        "touchmove",
        () => {
          clearTimeout(longPressTimer);
        },
        { passive: true },
      );
    });

    document.querySelectorAll("video").forEach((vid) => {
      let lastTap = 0;
      vid.addEventListener("touchend", (e) => {
        const now = Date.now();
        if (now - lastTap < 300) {
          e.preventDefault();
          if (vid.requestFullscreen) vid.requestFullscreen();
          else if (vid.webkitRequestFullscreen) vid.webkitRequestFullscreen();
        }
        lastTap = now;
      });
    });

    let pullStartY = 0;
    let pullRefreshing = false;
    window.addEventListener(
      "touchstart",
      (e) => {
        if (window.scrollY === 0) pullStartY = e.touches[0].clientY;
      },
      { passive: true },
    );
    window.addEventListener(
      "touchend",
      (e) => {
        if (pullRefreshing) return;
        const dy = e.changedTouches[0].clientY - pullStartY;
        if (dy > 100 && window.scrollY === 0) {
          pullRefreshing = true;
          window.location.reload();
        }
      },
      { passive: true },
    );
  }

  /* ─────────── Keyboard: Scroll inputs into view ─────────── */
  function initKeyboardHandling() {
    if (!("visualViewport" in window)) return;
    window.visualViewport.addEventListener("resize", () => {
      const active = document.activeElement;
      if (
        active &&
        (active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.tagName === "SELECT")
      ) {
        setTimeout(() => {
          active.scrollIntoView({ behavior: "smooth", block: "center" });
        }, 100);
      }
    });
  }

  /* ─────────── Lazy Load Images ─────────── */
  function initLazyImages() {
    if (!("IntersectionObserver" in window)) return;
    const lazyImgs = document.querySelectorAll("img[data-src]");
    if (!lazyImgs.length) return;
    const imgObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            const img = entry.target;
            img.src = img.dataset.src;
            img.removeAttribute("data-src");
            imgObserver.unobserve(img);
          }
        });
      },
      { rootMargin: "200px" },
    );
    lazyImgs.forEach((img) => {
      imgObserver.observe(img);
    });
  }

  /* ─────────── Offline Progress Sync ─────────── */
  function initOfflineSync() {
    if (!("serviceWorker" in navigator)) return;
    const PENDING_KEY = "azad-offline-progress";

    async function syncPending() {
      const pending = JSON.parse(localStorage.getItem(PENDING_KEY) || "[]");
      if (!pending.length) return;
      const synced = [];
      for (const entry of pending) {
        try {
          await fetch(entry.url, { method: "POST", headers: entry.headers, body: entry.body });
          synced.push(entry);
        } catch {
          /* keep for next sync */
        }
      }
      const remaining = pending.filter((e) => !synced.includes(e));
      localStorage.setItem(PENDING_KEY, JSON.stringify(remaining));
    }

    window.addEventListener("online", syncPending);
    if (navigator.onLine) syncPending();
  }

  /* ─────────── Init All ─────────── */

  /* ─────────── Inline Form Validation ─────────── */
  // biome-ignore lint/correctness/noUnusedVariables: called in DOMContentLoaded
  function initInlineValidation() {
    const validators = {
      required: (v) => v.trim().length > 0,
      email: (v) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v),
      password: (v) => v.length >= 8,
    };

    document.querySelectorAll("[data-validate]").forEach((field) => {
      const rules = field.dataset.validate.split("|");
      const feedback = field.closest(".azad-field")?.querySelector(".azad-field__feedback");

      function validate() {
        const value = field.value;
        let valid = true;
        let message = "";
        for (const rule of rules) {
          if (!validators[rule](value)) {
            valid = false;
            message =
              {
                required: "هذا الحقل مطلوب",
                email: "بريد إلكتروني غير صالح",
                password: "يجب أن تكون 8 أحرف على الأقل",
              }[rule] || "";
            break;
          }
        }
        field.classList.toggle("is-valid", valid && value.length > 0);
        field.classList.toggle("is-invalid", !valid);
        if (feedback) feedback.textContent = message;
      }

      field.addEventListener("blur", validate);
      field.addEventListener("input", () => {
        if (field.classList.contains("is-invalid")) validate();
      });
    });
  }

  /* ─────────── Password Strength Meter ─────────── */
  // biome-ignore lint/correctness/noUnusedVariables: called in DOMContentLoaded
  function initPasswordStrength() {
    document.querySelectorAll("[data-password-strength]").forEach((input) => {
      const wrap = input.closest(".azad-field") || input.parentElement;
      let meter = wrap.querySelector(".azad-password-strength");
      if (!meter) {
        meter = document.createElement("div");
        meter.className = "azad-password-strength";
        meter.innerHTML = '<div class="azad-password-strength__bar"></div>';
        input.parentNode.insertBefore(meter, input.nextSibling);
      }
      const bar = meter.querySelector(".azad-password-strength__bar");

      input.addEventListener("input", () => {
        const val = input.value;
        let score = 0;
        if (val.length >= 8) score++;
        if (/[A-Z]/.test(val)) score++;
        if (/[0-9]/.test(val)) score++;
        if (/[^A-Za-z0-9]/.test(val)) score++;

        bar.className = "azad-password-strength__bar";
        if (val.length === 0) {
          bar.style.width = "0%";
        } else if (score <= 1) {
          bar.classList.add("azad-password-strength__bar--weak");
          bar.style.width = "33%";
        } else if (score <= 3) {
          bar.classList.add("azad-password-strength__bar--fair");
          bar.style.width = "66%";
        } else {
          bar.classList.add("azad-password-strength__bar--strong");
          bar.style.width = "100%";
        }
      });
    });
  }

  /* ─────────── Copy to Clipboard ─────────── */
  // biome-ignore lint/correctness/noUnusedVariables: called in DOMContentLoaded
  function initCopyToClipboard() {
    document.querySelectorAll("[data-copy]").forEach((el) => {
      el.style.cursor = "pointer";
      el.addEventListener("click", async () => {
        const text = el.dataset.copy;
        try {
          await navigator.clipboard.writeText(text);
          el.classList.add("azad-copy-btn--copied");
          if (window.AzadToast) {
            window.AzadToast.success("تم النسخ إلى الحافظة");
          }
          setTimeout(() => el.classList.remove("azad-copy-btn--copied"), 2000);
        } catch {
          if (window.AzadToast) {
            window.AzadToast.error("فشل النسخ — حاول يدوياً");
          }
        }
      });
    });
  }

  /* ─────────── Reduced Motion Respect ─────────── */
  // biome-ignore lint/correctness/noUnusedVariables: called in DOMContentLoaded
  function initReducedMotion() {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = () => document.documentElement.classList.toggle("reduced-motion", mq.matches);
    apply();
    mq.addEventListener?.("change", apply);
  }

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
    initBottomNav();
    initTouchGestures();
    initKeyboardHandling();
    initLazyImages();
    initOfflineSync();
  });
})();
