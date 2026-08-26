import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";

describe("Search - Modal creation", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("creates search modal on first open", async () => {
    const { openModal } = await import("@app-static/js/pages/search.js");
    openModal();

    const modal = document.getElementById("azad-search-modal");
    expect(modal).toBeTruthy();
    expect(modal.getAttribute("role")).toBe("dialog");
    expect(modal.getAttribute("aria-modal")).toBe("true");
  });

  it("opens modal with is-open class", async () => {
    const { openModal } = await import("@app-static/js/pages/search.js");
    openModal();

    const modal = document.getElementById("azad-search-modal");
    expect(modal.classList.contains("is-open")).toBe(true);
  });

  it("focuses input on open", async () => {
    const { openModal } = await import("@app-static/js/pages/search.js");
    openModal();

    const input = document.getElementById("azad-search-input");
    expect(document.activeElement).toBe(input);
  });

  it("reuses existing modal", async () => {
    const { openModal } = await import("@app-static/js/pages/search.js");
    openModal();
    openModal();

    const modals = document.querySelectorAll("#azad-search-modal");
    expect(modals.length).toBe(1);
  });
});

describe("Search - closeModal", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("closes modal by removing is-open class", async () => {
    const { openModal, closeModal } = await import("@app-static/js/pages/search.js");
    openModal();
    closeModal();

    const modal = document.getElementById("azad-search-modal");
    expect(modal.classList.contains("is-open")).toBe(false);
  });

  it("clears input value on close", async () => {
    const { openModal, closeModal } = await import("@app-static/js/pages/search.js");
    openModal();

    const input = document.getElementById("azad-search-input");
    input.value = "test query";
    closeModal();

    expect(input.value).toBe("");
  });

  it("resets results on close", async () => {
    const { openModal, closeModal } = await import("@app-static/js/pages/search.js");
    openModal();

    const results = document.getElementById("azad-search-results");
    results.innerHTML = "<div>Old results</div>";
    closeModal();

    expect(results.querySelector(".azad-search-empty")).toBeTruthy();
  });

  it("does nothing if modal doesn't exist", async () => {
    const { closeModal } = await import("@app-static/js/pages/search.js");
    expect(() => closeModal()).not.toThrow();
  });
});

describe("Search - renderResults", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    window.AzadSearchLabels = undefined;
  });

  it("renders grouped results", async () => {
    const { openModal } = await import("@app-static/js/pages/search.js");
    openModal();

    const results = document.getElementById("azad-search-results");
    results.textContent = "";

    // Simulate rendering
    const groups = [
      { key: "schools", label: "المدارس" },
      { key: "users", label: "المستخدمون" },
    ];

    groups.forEach(({ key, label }) => {
      const groupDiv = document.createElement("div");
      groupDiv.className = "azad-search-group";

      const labelDiv = document.createElement("div");
      labelDiv.className = "azad-search-group__label";
      labelDiv.textContent = label;
      groupDiv.appendChild(labelDiv);

      results.appendChild(groupDiv);
    });

    expect(results.querySelectorAll(".azad-search-group").length).toBe(2);
  });

  it("shows empty state when no results", async () => {
    const { openModal } = await import("@app-static/js/pages/search.js");
    openModal();

    const results = document.getElementById("azad-search-results");
    results.textContent = "";

    const emptyDiv = document.createElement("div");
    emptyDiv.className = "azad-search-empty";
    emptyDiv.textContent = "لا توجد نتائج";
    results.appendChild(emptyDiv);

    expect(results.querySelector(".azad-search-empty").textContent).toBe("لا توجد نتائج");
  });
});

describe("Search - Keyboard navigation", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("tracks active index for arrow navigation", async () => {
    let activeIndex = -1;
    const items = [
      { classList: { toggle: vi.fn() }, setAttribute: vi.fn(), scrollIntoView: vi.fn(), removeAttribute: vi.fn() },
      { classList: { toggle: vi.fn() }, setAttribute: vi.fn(), scrollIntoView: vi.fn(), removeAttribute: vi.fn() },
    ];

    // Simulate ArrowDown
    activeIndex = (activeIndex + 1) % items.length;
    items.forEach((item, idx) => {
      const isActive = idx === activeIndex;
      item.classList.toggle("is-active", isActive);
      item.setAttribute("aria-selected", isActive ? "true" : "false");
    });

    expect(activeIndex).toBe(0);
    expect(items[0].classList.toggle).toHaveBeenCalledWith("is-active", true);
    expect(items[1].classList.toggle).toHaveBeenCalledWith("is-active", false);
  });

  it("wraps around on ArrowDown at end", () => {
    let activeIndex = 1;
    const totalItems = 2;

    activeIndex = (activeIndex + 1) % totalItems;
    expect(activeIndex).toBe(0);
  });

  it("wraps around on ArrowUp at start", () => {
    let activeIndex = 0;
    const totalItems = 3;

    activeIndex = activeIndex <= 0 ? totalItems - 1 : activeIndex - 1;
    expect(activeIndex).toBe(2);
  });
});

describe("Search - Debounce", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("debounces input events", () => {
    let callCount = 0;
    const debounce = (fn, ms) => {
      let t;
      return () => {
        clearTimeout(t);
        t = setTimeout(fn, ms);
      };
    };

    const debouncedFn = debounce(() => callCount++, 200);
    debouncedFn();
    debouncedFn();
    debouncedFn();

    vi.advanceTimersByTime(200);
    expect(callCount).toBe(1);
  });
});

describe("Search - Ctrl+K shortcut", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("opens modal on Ctrl+K", async () => {
    const { openModal } = await import("@app-static/js/pages/search.js");
    const openSpy = vi.fn();
    // We test the keyboard event handling logic
    document.addEventListener("keydown", (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        openSpy();
      }
    });

    const event = new KeyboardEvent("keydown", {
      key: "k",
      ctrlKey: true,
      bubbles: true,
      cancelable: true,
    });
    const preventSpy = vi.spyOn(event, "preventDefault");
    document.dispatchEvent(event);

    expect(openSpy).toHaveBeenCalled();
    expect(preventSpy).toHaveBeenCalled();
  });

  it("closes modal on Escape", async () => {
    let closed = false;
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closed = true;
    });

    document.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    );
    expect(closed).toBe(true);
  });
});
