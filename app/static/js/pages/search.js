/**
 * Global command palette / search module.
 *
 * Keyboard: Ctrl+K or Cmd+K opens the search modal.
 *           ↑ / ↓ navigates results, Enter selects, Escape closes.
 * Debounced AJAX to /api/v1/search?q= with AbortController cancellation.
 */

const SEARCH_ENDPOINT = "/api/v1/search";
const DEBOUNCE_MS = 200;

let activeIndex = -1;
let resultItems = [];

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
               placeholder="${window.AzadSearchLabels?.placeholder || "ابحث عن مدارس، مستخدمين، صفوف..."}"
               role="combobox" aria-autocomplete="list" aria-expanded="true"
               aria-controls="azad-search-results">
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
  const inputForExpanded = modal.querySelector("#azad-search-input");
  if (inputForExpanded) inputForExpanded.setAttribute("aria-expanded", "false");
  // Cancel any pending search
  if (abortController) abortController.abort();
  clearTimeout(debounceTimer);
  const input = modal.querySelector("#azad-search-input");
  if (input) {
    input.value = "";
    input.removeAttribute("aria-activedescendant");
  }
  const results = modal.querySelector("#azad-search-results");
  if (results) {
    results.textContent = "";
    const div = document.createElement("div");
    div.className = "azad-search-empty";
    div.textContent = window.AzadSearchLabels?.startTyping || "اكتب حرفين على الأقل...";
    results.appendChild(div);
  }
  activeIndex = -1;
  resultItems = [];
}

function openModal() {
  const modal = createModal();
  modal.classList.add("is-open");
  const inputForExpanded = modal.querySelector("#azad-search-input");
  if (inputForExpanded) inputForExpanded.setAttribute("aria-expanded", "true");
  const input = modal.querySelector("#azad-search-input");
  if (input) {
    input.focus();
    input.value = "";
  }
  activeIndex = -1;
  resultItems = [];
}

function updateActiveItem() {
  resultItems.forEach((item, idx) => {
    const isActive = idx === activeIndex;
    item.classList.toggle("is-active", isActive);
    item.setAttribute("aria-selected", isActive ? "true" : "false");
    if (isActive) {
      item.id = "azad-search-active";
      item.scrollIntoView({ block: "nearest" });
    } else {
      item.removeAttribute("id");
    }
  });

  const input = document.getElementById("azad-search-input");
  if (input) {
    if (activeIndex >= 0 && resultItems[activeIndex]) {
      input.setAttribute("aria-activedescendant", "azad-search-active");
    } else {
      input.removeAttribute("aria-activedescendant");
    }
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

  container.textContent = "";
  let total = 0;
  let resultId = 0;

  groups.forEach(({ key, label }) => {
    const items = data[key] || [];
    if (!items.length) return;
    total += items.length;

    const groupDiv = document.createElement("div");
    groupDiv.className = "azad-search-group";

    const labelDiv = document.createElement("div");
    labelDiv.className = "azad-search-group__label";
    labelDiv.textContent = label;
    groupDiv.appendChild(labelDiv);

    const listUl = document.createElement("ul");
    listUl.className = "azad-search-group__list";

    items.forEach((item) => {
      const li = document.createElement("li");
      const a = document.createElement("a");
      a.href = item.url;
      a.className = "azad-search-result";
      a.setAttribute("role", "option");
      a.setAttribute("aria-selected", "false");
      a.id = `azad-search-result-${resultId++}`;

      const iconSpan = document.createElement("span");
      iconSpan.className = "azad-search-result__icon";
      iconSpan.innerHTML = window.AzadIcons?.[item.icon] || "";

      const bodyDiv = document.createElement("div");
      bodyDiv.className = "azad-search-result__body";

      const titleDiv = document.createElement("div");
      titleDiv.className = "azad-search-result__title";
      titleDiv.textContent = item.title;

      const subtitleDiv = document.createElement("div");
      subtitleDiv.className = "azad-search-result__subtitle";
      subtitleDiv.textContent = item.subtitle;

      bodyDiv.appendChild(titleDiv);
      bodyDiv.appendChild(subtitleDiv);
      a.appendChild(iconSpan);
      a.appendChild(bodyDiv);
      li.appendChild(a);
      listUl.appendChild(li);
    });

    groupDiv.appendChild(listUl);
    container.appendChild(groupDiv);
  });

  if (!total) {
    const emptyDiv = document.createElement("div");
    emptyDiv.className = "azad-search-empty";
    emptyDiv.textContent = window.AzadSearchLabels?.noResults || "لا توجد نتائج";
    container.appendChild(emptyDiv);
  }

  // Refresh result items reference for keyboard nav
  resultItems = Array.from(container.querySelectorAll(".azad-search-result"));
  activeIndex = -1;
}

let abortController = null;
let debounceTimer = null;

async function performSearch(query) {
  const container = document.getElementById("azad-search-results");
  if (!query || query.length < 2) {
    if (container) {
      container.textContent = "";
      const div = document.createElement("div");
      div.className = "azad-search-empty";
      div.textContent = window.AzadSearchLabels?.startTyping || "اكتب حرفين على الأقل...";
      container.appendChild(div);
    }
    activeIndex = -1;
    resultItems = [];
    return;
  }

  if (container) {
    container.textContent = "";
    const div = document.createElement("div");
    div.className = "azad-search-empty";
    div.textContent = window.AzadSearchLabels?.searching || "جاري البحث...";
    container.appendChild(div);
  }

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
      container.textContent = "";
      const div = document.createElement("div");
      div.className = "azad-search-empty azad-search-empty--error";
      div.textContent = window.AzadSearchLabels?.error || "حدث خطأ أثناء البحث";
      container.appendChild(div);
    }
    activeIndex = -1;
    resultItems = [];
  }
}

function handleSearchKeydown(e) {
  if (e.key === "ArrowDown") {
    e.preventDefault();
    if (!resultItems.length) return;
    activeIndex = (activeIndex + 1) % resultItems.length;
    updateActiveItem();
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    if (!resultItems.length) return;
    activeIndex = activeIndex <= 0 ? resultItems.length - 1 : activeIndex - 1;
    updateActiveItem();
  } else if (e.key === "Enter") {
    if (activeIndex >= 0 && resultItems[activeIndex]) {
      e.preventDefault();
      resultItems[activeIndex].click();
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

  document.addEventListener("keydown", (e) => {
    if (e.target.id === "azad-search-input") {
      handleSearchKeydown(e);
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}

export { closeModal, openModal };
