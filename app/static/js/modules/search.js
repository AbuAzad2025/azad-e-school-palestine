/**
 * Global command palette / search module.
 *
 * Keyboard: Ctrl+K or Cmd+K opens the search modal.
 * Debounced AJAX to /api/v1/search?q= with AbortController cancellation.
 */

const SEARCH_ENDPOINT = "/api/v1/search";
const DEBOUNCE_MS = 200;

function createModal() {
  let modal = document.getElementById("azad-search-modal");
  if (modal) return modal;

  modal = document.createElement("div");
  modal.id = "azad-search-modal";
  modal.className = "azad-search-modal";
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  modal.setAttribute("aria-label", window.AzadSearchLabels?.title || "بحث");
  modal.innerHTML = `
    <div class="azad-search-overlay" data-search-close></div>
    <div class="azad-search-container">
      <div class="azad-search-input-wrap">
        <span class="azad-search__icon">${window.AzadSearchLabels?.searchIcon || ""}</span>
        <input type="search" class="azad-search__input" id="azad-search-input" autocomplete="off"
               placeholder="${window.AzadSearchLabels?.placeholder || "ابحث عن مدارس، مستخدمين، صفوف..."}">
        <kbd class="azad-search__shortcut" aria-hidden="true">Esc</kbd>
      </div>
      <div class="azad-search-results" id="azad-search-results" role="listbox" aria-label="نتائج البحث">
        <div class="azad-search-empty">${window.AzadSearchLabels?.startTyping || "اكتب حرفين على الأقل..."}</div>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  return modal;
}

function closeModal() {
  const modal = document.getElementById("azad-search-modal");
  if (!modal) return;
  modal.classList.remove("is-open");
  const input = modal.querySelector("#azad-search-input");
  if (input) input.value = "";
  const results = modal.querySelector("#azad-search-results");
  if (results)
    results.innerHTML = `<div class="azad-search-empty">${window.AzadSearchLabels?.startTyping || "اكتب حرفين على الأقل..."}</div>`;
}

function openModal() {
  const modal = createModal();
  modal.classList.add("is-open");
  const input = modal.querySelector("#azad-search-input");
  if (input) {
    input.focus();
    input.value = "";
  }
}

function renderResults(data) {
  const container = document.getElementById("azad-search-results");
  if (!container) return;

  const groups = [
    { key: "schools", label: window.AzadSearchLabels?.schools || "المدارس" },
    { key: "users", label: window.AzadSearchLabels?.users || "المستخدمون" },
    { key: "classes", label: window.AzadSearchLabels?.classes || "الصفوف" },
    { key: "subscriptions", label: window.AzadSearchLabels?.subscriptions || "الاشتراكات" },
  ];

  let html = "";
  let total = 0;
  groups.forEach(({ key, label }) => {
    const items = data[key] || [];
    if (!items.length) return;
    total += items.length;
    html += `<div class="azad-search-group">
      <div class="azad-search-group__label">${label}</div>
      <ul class="azad-search-group__list">`;
    items.forEach((item) => {
      html += `
        <li>
          <a href="${item.url}" class="azad-search-result" role="option">
            <span class="azad-search-result__icon">${window.AzadIcons?.[item.icon] || ""}</span>
            <div class="azad-search-result__body">
              <div class="azad-search-result__title">${escapeHtml(item.title)}</div>
              <div class="azad-search-result__subtitle">${escapeHtml(item.subtitle)}</div>
            </div>
          </a>
        </li>`;
    });
    html += "</ul></div>";
  });

  if (!total) {
    html = `<div class="azad-search-empty">${window.AzadSearchLabels?.noResults || "لا توجد نتائج"}</div>`;
  }
  container.innerHTML = html;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

let abortController = null;
let debounceTimer = null;

async function performSearch(query) {
  const container = document.getElementById("azad-search-results");
  if (!query || query.length < 2) {
    if (container) {
      container.innerHTML = `<div class="azad-search-empty">${window.AzadSearchLabels?.startTyping || "اكتب حرفين على الأقل..."}</div>`;
    }
    return;
  }

  if (container)
    container.innerHTML = `<div class="azad-search-empty">${window.AzadSearchLabels?.searching || "جاري البحث..."}</div>`;

  if (abortController) abortController.abort();
  abortController = new AbortController();

  try {
    const response = await fetch(`${SEARCH_ENDPOINT}?q=${encodeURIComponent(query)}&limit=5`, {
      signal: abortController.signal,
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    renderResults(payload.data || {});
  } catch (error) {
    if (error.name === "AbortError") return;
    if (container) {
      container.innerHTML = `<div class="azad-search-empty azad-search-empty--error">${window.AzadSearchLabels?.error || "حدث خطأ أثناء البحث"}</div>`;
    }
  }
}

function init() {
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openModal();
    }
    if (e.key === "Escape") closeModal();
  });

  document.addEventListener("click", (e) => {
    const openTrigger = e.target.closest("[data-search-open]");
    if (openTrigger) {
      e.preventDefault();
      openModal();
    }
    const closeTrigger = e.target.closest("[data-search-close]");
    if (closeTrigger) closeModal();
  });

  document.addEventListener("input", (e) => {
    if (e.target.id !== "azad-search-input") return;
    clearTimeout(debounceTimer);
    const query = e.target.value.trim();
    debounceTimer = setTimeout(() => performSearch(query), DEBOUNCE_MS);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}

export { closeModal, openModal };
