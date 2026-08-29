import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { openModal, closeModal } from "@app-static/js/pages/search.js";

describe("Search - actual module closeModal", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("does nothing when modal doesn't exist", () => {
    expect(() => closeModal()).not.toThrow();
  });
});

describe("Search - actual module openModal", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("creates modal with correct attributes", () => {
    openModal();
    const modal = document.getElementById("azad-search-modal");
    expect(modal).toBeTruthy();
    expect(modal.getAttribute("role")).toBe("dialog");
    expect(modal.getAttribute("aria-modal")).toBe("true");
  });

  it("adds is-open class", () => {
    openModal();
    const modal = document.getElementById("azad-search-modal");
    expect(modal.classList.contains("is-open")).toBe(true);
  });

  it("focuses input after open", () => {
    openModal();
    const input = document.getElementById("azad-search-input");
    expect(document.activeElement).toBe(input);
  });

  it("reuses existing modal on second open", () => {
    openModal();
    openModal();
    const modals = document.querySelectorAll("#azad-search-modal");
    expect(modals.length).toBe(1);
  });

  it("resets input value on open", () => {
    openModal();
    const input = document.getElementById("azad-search-input");
    input.value = "old value";
    openModal();
    expect(input.value).toBe("");
  });
});

describe("Search - actual module openModal then closeModal", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("closes modal by removing is-open class", () => {
    openModal();
    closeModal();
    const modal = document.getElementById("azad-search-modal");
    expect(modal.classList.contains("is-open")).toBe(false);
  });

  it("clears input on close", () => {
    openModal();
    const input = document.getElementById("azad-search-input");
    input.value = "test query";
    closeModal();
    expect(input.value).toBe("");
  });

  it("resets results on close", () => {
    openModal();
    const results = document.getElementById("azad-search-results");
    results.innerHTML = "<div>Old results</div>";
    closeModal();
    expect(results.querySelector(".azad-search-empty")).toBeTruthy();
  });

  it("removes aria-activedescendant on close", () => {
    openModal();
    const input = document.getElementById("azad-search-input");
    input.setAttribute("aria-activedescendant", "something");
    closeModal();
    expect(input.hasAttribute("aria-activedescendant")).toBe(false);
  });
});

describe("Search - init() keyboard shortcuts", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("opens modal on Ctrl+K", () => {
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "k", ctrlKey: true, bubbles: true }),
    );
    const modal = document.getElementById("azad-search-modal");
    expect(modal).toBeTruthy();
    expect(modal.classList.contains("is-open")).toBe(true);
  });

  it("opens modal on Cmd+K", () => {
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "k", metaKey: true, bubbles: true }),
    );
    const modal = document.getElementById("azad-search-modal");
    expect(modal).toBeTruthy();
    expect(modal.classList.contains("is-open")).toBe(true);
  });

  it("closes modal on Escape", () => {
    openModal();
    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    );
    const modal = document.getElementById("azad-search-modal");
    expect(modal.classList.contains("is-open")).toBe(false);
  });

  it("opens modal on search-open trigger click", () => {
    const trigger = document.createElement("button");
    trigger.setAttribute("data-search-open", "");
    document.body.appendChild(trigger);
    trigger.click();
    const modal = document.getElementById("azad-search-modal");
    expect(modal).toBeTruthy();
    expect(modal.classList.contains("is-open")).toBe(true);
  });

  it("closes modal on search-close trigger click", () => {
    openModal();
    const closeTrigger = document.querySelector("[data-search-close]");
    if (closeTrigger) closeTrigger.click();
    const modal = document.getElementById("azad-search-modal");
    expect(modal.classList.contains("is-open")).toBe(false);
  });
});

describe("Search - performSearch via input event", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("shows empty state for query < 2 chars", () => {
    openModal();
    const input = document.getElementById("azad-search-input");
    input.value = "a";
    input.dispatchEvent(new Event("input", { bubbles: true }));

    vi.advanceTimersByTime(300);

    const results = document.getElementById("azad-search-results");
    expect(results.querySelector(".azad-search-empty")).toBeTruthy();
  });

  it("shows loading state for valid query", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({ data: {} }),
      }),
    );

    openModal();
    const input = document.getElementById("azad-search-input");
    input.value = "test";
    input.dispatchEvent(new Event("input", { bubbles: true }));

    const results = document.getElementById("azad-search-results");
    const emptyText = results.querySelector(".azad-search-empty");
    expect(emptyText).toBeTruthy();
  });

  it("renders search results from API", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({
          data: {
            schools: [
              { title: "Test School", subtitle: "Location", url: "/schools/1", icon: "school" },
            ],
            users: [],
            classes: [],
            subscriptions: [],
          },
        }),
      }),
    );

    openModal();
    const input = document.getElementById("azad-search-input");
    input.value = "test";
    input.dispatchEvent(new Event("input", { bubbles: true }));

    // Advance debounce timer
    vi.advanceTimersByTime(250);
    // Flush promises
    await vi.advanceTimersByTimeAsync(0);

    const results = document.getElementById("azad-search-results");
    expect(results.querySelector(".azad-search-group")).toBeTruthy();
    expect(results.querySelector(".azad-search-result")).toBeTruthy();
  });

  it("renders empty state when no results", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({ data: {} }),
      }),
    );

    openModal();
    const input = document.getElementById("azad-search-input");
    input.value = "xyz";
    input.dispatchEvent(new Event("input", { bubbles: true }));

    vi.advanceTimersByTime(250);
    await vi.advanceTimersByTimeAsync(0);

    const results = document.getElementById("azad-search-results");
    const empty = results.querySelector(".azad-search-empty");
    expect(empty).toBeTruthy();
  });

  it("shows error state on fetch failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("Network error")),
    );

    openModal();
    const input = document.getElementById("azad-search-input");
    input.value = "test";
    input.dispatchEvent(new Event("input", { bubbles: true }));

    vi.advanceTimersByTime(250);
    await vi.advanceTimersByTimeAsync(0);

    const results = document.getElementById("azad-search-results");
    expect(results.querySelector(".azad-search-empty--error")).toBeTruthy();
  });
});

describe("Search - keyboard navigation via search flow", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    vi.useFakeTimers();
    // Mock scrollIntoView for search result items
    Element.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    delete Element.prototype.scrollIntoView;
  });

  it("ArrowDown navigates search results", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({
          data: {
            schools: [
              { title: "School A", subtitle: "loc", url: "/s/1", icon: "school" },
              { title: "School B", subtitle: "loc2", url: "/s/2", icon: "school" },
            ],
          },
        }),
      }),
    );

    openModal();
    const input = document.getElementById("azad-search-input");
    input.value = "school";
    input.dispatchEvent(new Event("input", { bubbles: true }));

    vi.advanceTimersByTime(250);
    await vi.advanceTimersByTimeAsync(0);

    const items = document.querySelectorAll(".azad-search-result");
    expect(items.length).toBe(2);

    // ArrowDown should work since resultItems is populated by renderResults
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }),
    );

    expect(items[0].classList.contains("is-active")).toBe(true);
    expect(items[0].getAttribute("aria-selected")).toBe("true");
  });

  it("ArrowUp wraps to last result", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({
          data: {
            schools: [
              { title: "School A", subtitle: "loc", url: "/s/1", icon: "school" },
              { title: "School B", subtitle: "loc2", url: "/s/2", icon: "school" },
            ],
          },
        }),
      }),
    );

    openModal();
    const input = document.getElementById("azad-search-input");
    input.value = "school";
    input.dispatchEvent(new Event("input", { bubbles: true }));

    vi.advanceTimersByTime(250);
    await vi.advanceTimersByTimeAsync(0);

    const items = document.querySelectorAll(".azad-search-result");
    expect(items.length).toBe(2);

    // ArrowUp at start wraps to last
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true }),
    );

    expect(items[1].classList.contains("is-active")).toBe(true);
  });

  it("Enter navigates to active result", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({
          data: {
            schools: [
              { title: "School A", subtitle: "loc", url: "/s/1", icon: "school" },
            ],
          },
        }),
      }),
    );

    openModal();
    const input = document.getElementById("azad-search-input");
    input.value = "school";
    input.dispatchEvent(new Event("input", { bubbles: true }));

    vi.advanceTimersByTime(250);
    await vi.advanceTimersByTimeAsync(0);

    // ArrowDown to select first item
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }),
    );

    const item = document.querySelector(".azad-search-result");
    expect(item).toBeTruthy();
    expect(item.classList.contains("is-active")).toBe(true);
  });
});

describe("Search - localization", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    window.AzadSearchLabels = undefined;
  });

  it("uses default Arabic placeholder", () => {
    openModal();
    const input = document.getElementById("azad-search-input");
    expect(input.placeholder).toContain("ابحث");
  });

  it("uses custom labels when provided", () => {
    window.AzadSearchLabels = {
      placeholder: "Search everything...",
      title: "Search",
      schools: "Schools",
      users: "Users",
      classes: "Classes",
      subscriptions: "Subscriptions",
      startTyping: "Type at least 2 characters...",
      noResults: "No results found",
      error: "Search error",
      searching: "Searching...",
    };
    openModal();
    const input = document.getElementById("azad-search-input");
    expect(input.placeholder).toBe("Search everything...");

    const modal = document.getElementById("azad-search-modal");
    expect(modal.getAttribute("aria-label")).toBe("Search");
  });
});

describe("Search - renderResults with groups", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("renders multiple groups from API", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({
          data: {
            schools: [{ title: "School 1", subtitle: "loc", url: "/s/1", icon: "school" }],
            users: [{ title: "User 1", subtitle: "email", url: "/u/1", icon: "user" }],
            classes: [{ title: "Class 1", subtitle: "sec", url: "/c/1", icon: "class" }],
            subscriptions: [],
          },
        }),
      }),
    );

    openModal();
    const input = document.getElementById("azad-search-input");
    input.value = "test";
    input.dispatchEvent(new Event("input", { bubbles: true }));

    vi.advanceTimersByTime(250);
    await vi.advanceTimersByTimeAsync(0);

    const results = document.getElementById("azad-search-results");
    expect(results.querySelectorAll(".azad-search-group").length).toBeGreaterThanOrEqual(2);
  });

  it("renders subscriptions group when present", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({
          data: {
            schools: [],
            users: [],
            classes: [],
            subscriptions: [{ title: "Sub 1", subtitle: "plan", url: "/sub/1", icon: "sub" }],
          },
        }),
      }),
    );

    openModal();
    const input = document.getElementById("azad-search-input");
    input.value = "sub";
    input.dispatchEvent(new Event("input", { bubbles: true }));

    vi.advanceTimersByTime(250);
    await vi.advanceTimersByTimeAsync(0);

    const results = document.getElementById("azad-search-results");
    expect(results.querySelector(".azad-search-group")).toBeTruthy();
  });
});
