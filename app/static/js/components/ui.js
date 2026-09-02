/**
 * UI helpers module — ES module
 *
 * Event delegation for common interactive patterns.
 */

/**
 * Attach a delegated event listener to a container.
 * @param {HTMLElement} container
 * @param {string} selector
 * @param {string} event
 * @param {Function} handler
 * @returns {void}
 */
export function delegate(container, selector, event, handler) {
  container.addEventListener(event, (e) => {
    const target = e.target.closest(selector);
    if (target && container.contains(target)) {
      handler.call(target, e, target);
    }
  });
}

/**
 * Wire up password visibility toggle buttons inside password fields.
 * @returns {void}
 */
export function initPasswordToggle() {
  delegate(document.body, "[data-password-toggle]", "click", (_e, btn) => {
    const wrap = btn.closest(".azad-field__input-wrap--password");
    if (!wrap) return;
    const input = wrap.querySelector("input");
    if (!input) return;
    const isPassword = input.type === "password";
    input.type = isPassword ? "text" : "password";
    btn.setAttribute("aria-pressed", String(isPassword));
  });
}

export function initAccordions() {
  delegate(document.body, ".accordion-btn", "click", (_e, btn) => {
    const expanded = btn.getAttribute("aria-expanded") === "true";
    btn.setAttribute("aria-expanded", String(!expanded));
    const content = btn.nextElementSibling;
    if (content) content.classList.toggle("open", !expanded);
  });
}

export function initTabs() {
  delegate(document.body, ".tabs .tab", "click", (e, tab) => {
    e.preventDefault();
    const tabBar = tab.closest(".tabs");
    if (!tabBar) return;
    tabBar.querySelectorAll(".tab").forEach((t) => {
      t.classList.remove("active");
    });
    tab.classList.add("active");
  });
}

export function initFlashes() {
  delegate(
    document.body,
    ".flash [data-dismiss], .azad-flash [data-dismiss]",
    "click",
    (_e, btn) => {
      const flash = btn.closest(".flash, .azad-flash");
      if (flash) flash.remove();
    },
  );
}

export function initUserDropdown() {
  document.addEventListener("click", (e) => {
    const toggle = e.target.closest("[data-user-toggle]");
    const menu = document.querySelector("[data-user-menu]");
    if (!menu) return;

    if (toggle) {
      e.preventDefault();
      const isOpen = !menu.hidden;
      menu.hidden = isOpen;
      toggle.setAttribute("aria-expanded", String(!isOpen));
      return;
    }

    if (!e.target.closest("[data-user-menu]")) {
      menu.hidden = true;
      const toggleBtn = document.querySelector("[data-user-toggle]");
      if (toggleBtn) toggleBtn.setAttribute("aria-expanded", "false");
    }
  });
}

/**
 * Intercept clicks / submits on elements with [data-confirm] and show a native confirm dialog.
 * @returns {void}
 */
export function initConfirmDialogs() {
  const ask = (trigger, e) => {
    const message =
      trigger.dataset.confirm || window.AzadConfirmDefaults?.message || "هل أنت متأكد؟";
    if (!confirm(message)) {
      e.preventDefault();
      e.stopPropagation();
      return false;
    }
    return true;
  };

  delegate(document.body, "[data-confirm]", "click", (e, trigger) => {
    if (trigger.tagName === "FORM") return;
    ask(trigger, e);
  });

  document.addEventListener("submit", (e) => {
    const form = e.target.closest("form[data-confirm]");
    if (!form) return;
    if (!ask(form, e)) return;
  });
}

/**
 * Trap focus inside a modal/dialog element.
 * @param {HTMLElement} modal
 * @returns {Function} cleanup function to remove the trap
 */
export function trapFocus(modal) {
  const focusableSelectors =
    'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';
  function handler(e) {
    if (e.key !== "Tab") return;
    const focusable = Array.from(modal.querySelectorAll(focusableSelectors));
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (e.shiftKey) {
      if (document.activeElement === first) {
        e.preventDefault();
        last.focus();
      }
    } else {
      if (document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }
  modal.addEventListener("keydown", handler);
  return () => modal.removeEventListener("keydown", handler);
}

export function initHelpTooltips() {
  const hideAll = () => {
    document.querySelectorAll(".azad-field__help-popover").forEach((popover) => {
      popover.hidden = true;
    });
  };

  delegate(document.body, "[data-help-tooltip]", "click", (e) => {
    e.preventDefault();
    const trigger = e.target.closest("[data-help-tooltip]");
    const describedBy = trigger?.getAttribute("aria-describedby");
    const popover = describedBy ? document.getElementById(describedBy) : null;
    if (!popover) return;
    const wasHidden = popover.hidden;
    hideAll();
    popover.hidden = !wasHidden;
  });

  document.addEventListener("click", (e) => {
    if (
      !e.target.closest("[data-help-tooltip]") &&
      !e.target.closest(".azad-field__help-popover")
    ) {
      hideAll();
    }
  });
}

export function initActionsDropdowns() {
  document.addEventListener("click", (e) => {
    const toggle = e.target.closest("[data-actions-toggle]");
    if (toggle) {
      e.preventDefault();
      const dropdown = toggle.closest("[data-actions-dropdown]");
      const menu = dropdown?.querySelector("[data-actions-menu]");
      if (!menu) return;
      const isOpen = !menu.hidden;
      menu.hidden = isOpen;
      toggle.setAttribute("aria-expanded", String(!isOpen));
      return;
    }

    if (!e.target.closest("[data-actions-dropdown]")) {
      document.querySelectorAll("[data-actions-menu]").forEach((menu) => {
        menu.hidden = true;
        const btn = menu.closest("[data-actions-dropdown]")?.querySelector("[data-actions-toggle]");
        if (btn) btn.setAttribute("aria-expanded", "false");
      });
    }
  });
}

/**
 * Add a material-design ripple effect to primary buttons on click.
 * @returns {void}
 */
export function initRipple() {
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(
      ".azad-btn, .azad-btn-primary, .azad-btn-outline, .azad-btn-accent, .azad-btn-ghost, .azad-btn-danger, .stat-card.link, .azad-action-card",
    );
    if (!btn?.isConnected) return;

    // Remove any existing ripple to prevent accumulation
    const existing = btn.querySelector(".azad-ripple");
    if (existing) existing.remove();

    const ripple = document.createElement("span");
    ripple.className = "azad-ripple";
    const rect = btn.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height) * 2;
    ripple.style.width = ripple.style.height = `${size}px`;
    ripple.style.left = `${e.clientX - rect.left - size / 2}px`;
    ripple.style.top = `${e.clientY - rect.top - size / 2}px`;
    if (!btn.style.position) btn.style.position = "relative";
    btn.style.overflow = "hidden";
    btn.appendChild(ripple);
    setTimeout(() => {
      if (ripple.isConnected) ripple.remove();
    }, 600);
  });
}

export default {
  delegate,
  initPasswordToggle,
  initAccordions,
  initTabs,
  initFlashes,
  initUserDropdown,
  initConfirmDialogs,
  initHelpTooltips,
  initActionsDropdowns,
  initRipple,
};
