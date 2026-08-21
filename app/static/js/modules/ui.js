/**
 * UI helpers module — ES module
 *
 * Event delegation for common interactive patterns.
 */

export function delegate(container, selector, event, handler) {
  container.addEventListener(event, (e) => {
    const target = e.target.closest(selector);
    if (target && container.contains(target)) {
      handler.call(target, e, target);
    }
  });
}

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

export function initRipple() {
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

export default {
  delegate,
  initPasswordToggle,
  initAccordions,
  initTabs,
  initFlashes,
  initRipple,
};
