/**
 * Toast notification module — ES module
 */

const ICONS = {
  success:
    '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6 9 17l-5-5"/></svg>',
  error:
    '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>',
  warning:
    '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/></svg>',
  info: '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>',
};

function getContainer() {
  let container = document.getElementById("azad-toasts");
  if (!container) {
    container = document.createElement("div");
    container.className = "azad-toast-container";
    container.id = "azad-toasts";
    document.body.appendChild(container);
  }
  return container;
}

function announce(message) {
  const region = document.getElementById("azad-live-region");
  if (!region) return;
  region.textContent = message;
  setTimeout(() => {
    region.textContent = "";
  }, 1000);
}

function removeToast(toast) {
  toast.style.opacity = "0";
  toast.style.transform = "translateX(100%)";
  toast.style.transition = "all .3s";
  setTimeout(() => toast.remove(), 300);
}

export function show(options) {
  const {
    type = "info",
    title = "",
    message = "",
    duration = 4000,
  } = typeof options === "string" ? { message: options } : options;
  const container = getContainer();

  const toast = document.createElement("div");
  toast.className = `azad-toast azad-toast--${type}`;
  toast.innerHTML = `
    <div class="azad-toast__icon">${ICONS[type] || ICONS.info}</div>
    <div class="azad-toast__content">
      ${title ? `<div class="azad-toast__title">${title}</div>` : ""}
      <div class="azad-toast__message">${message}</div>
    </div>
    <button class="azad-toast__close" aria-label="إغلاق">
      <svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
    </button>
    <div class="azad-toast__progress" style="animation-duration: ${duration}ms"></div>
  `;

  toast.querySelector(".azad-toast__close").addEventListener("click", () => removeToast(toast));
  container.appendChild(toast);
  announce(message || title);

  if (duration > 0) {
    setTimeout(() => {
      if (toast.parentNode) removeToast(toast);
    }, duration);
  }

  return toast;
}

export const success = (msg, title) =>
  show({ type: "success", title: title || "نجح", message: msg });
export const error = (msg, title) => show({ type: "error", title: title || "خطأ", message: msg });
export const warning = (msg, title) =>
  show({ type: "warning", title: title || "تنبيه", message: msg });
export const info = (msg, title) => show({ type: "info", title: title || "معلومة", message: msg });

export default { show, success, error, warning, info };
