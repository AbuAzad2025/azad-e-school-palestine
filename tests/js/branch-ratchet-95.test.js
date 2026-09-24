/**
 * Branch-coverage ratchet — towards 95% branch coverage.
 *
 * Targets the fallback / guard arms that the happy-path suites never reach:
 * search.js missing-label+icon fallbacks and fetch error/abort/empty-payload
 * arms, charts.js CSS-variable + devicePixelRatio fallbacks (bar and
 * doughnut), ui.js element-guard arms (password wrap, confirm
 * defaults/forms, tooltip target, actions menu), and bulk.js guard arms
 * (missing bar, orphan select-all, non-table sibling, Arabic message
 * fallbacks).
 *
 * Note: ui.js:53 (`if (!tabBar) return` in initTabs) is unreachable through
 * event delegation — the ".tabs .tab" selector already guarantees a .tabs
 * ancestor, so closest(".tabs") can never be null there.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { updateBulkBar } from "@app-static/js/pages/bulk.js";
import { renderChart } from "@app-static/js/components/charts.js";
import {
  initActionsDropdowns,
  initConfirmDialogs,
  initHelpTooltips,
  initPasswordToggle,
} from "@app-static/js/components/ui.js";
import { closeModal, openModal } from "@app-static/js/pages/search.js";

/** Canvas 2d context stub — caches one mock per property so call counts work. */
function makeCtx() {
  const cache = new Map();
  return new Proxy(
    {},
    {
      get(target, prop) {
        if (!cache.has(prop)) cache.set(prop, vi.fn());
        return cache.get(prop);
      },
      set() {
        return true;
      },
    },
  );
}

const jsonResponse = (data) => ({
  ok: true,
  json: async () => ({ data }),
});

const click = (el) =>
  el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));

const key = (el, k) =>
  el.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true }));

// ═════════════════════════════════════════════════════════════════════
// search.js — fallback + fetch-error + keyboard-guard arms
// ═════════════════════════════════════════════════════════════════════

describe("search.js — fallback and error arms", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    vi.useFakeTimers();
    Element.prototype.scrollIntoView = vi.fn();
    delete window.AzadSearchLabels;
    delete window.AzadIcons;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    document.body.innerHTML = "";
    delete Element.prototype.scrollIntoView;
  });

  /** Type into the palette input and flush the debounce + fetch microtasks. */
  async function typeAndSettle(value) {
    const input = document.getElementById("azad-search-input");
    input.value = value;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    vi.advanceTimersByTime(250);
    await vi.advanceTimersByTimeAsync(0);
    return input;
  }

  it("renders results with empty icon fallback and closes with the typing fallback", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          schools: [{ title: "مدرسة أ", subtitle: "s", url: "/s/1", icon: "school" }],
        }),
      ),
    );
    openModal();
    await typeAndSettle("مدر");

    expect(document.querySelector(".azad-search-result__icon").innerHTML).toBe("");
    expect(document.querySelector(".azad-search-result__title").textContent).toBe(
      "مدرسة أ",
    );

    closeModal();
    expect(
      document.getElementById("azad-search-results").textContent,
    ).toContain("اكتب حرفين");
  });

  it("falls back to the no-results label when the payload has no data key", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }),
    );
    openModal();
    await typeAndSettle("ززز");

    expect(document.querySelector(".azad-search-empty").textContent).toBe(
      "لا توجد نتائج",
    );
  });

  it("falls back to the start-typing hint for short queries", async () => {
    openModal();
    await typeAndSettle("a");

    expect(document.querySelector(".azad-search-empty").textContent).toBe(
      "اكتب حرفين على الأقل...",
    );
  });

  it("renders the error fallback when the response is not ok", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 500 }),
    );
    openModal();
    await typeAndSettle("مدر");

    expect(
      document.querySelector(".azad-search-empty--error").textContent,
    ).toBe("حدث خطأ أثناء البحث");
  });

  it("returns silently when the request is aborted", async () => {
    const abortError = new Error("aborted");
    abortError.name = "AbortError";
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abortError));
    openModal();
    await typeAndSettle("مدر");

    expect(document.querySelector(".azad-search-empty--error")).toBeNull();
  });

  it("skips rendering when the results container is gone", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ schools: [] })),
    );
    openModal();
    document.getElementById("azad-search-results").remove();

    await expect(typeAndSettle("مدر")).resolves.toBeTruthy();
  });

  it("ignores navigation keys while the result list is empty", () => {
    openModal();
    const input = document.getElementById("azad-search-input");
    key(input, "ArrowDown");
    key(input, "ArrowUp");

    expect(input.getAttribute("aria-activedescendant")).toBeNull();
  });

  it("wraps ArrowUp around to the last result", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          schools: [
            { title: "أ", subtitle: "1", url: "/1", icon: "school" },
            { title: "ب", subtitle: "2", url: "/2", icon: "school" },
          ],
        }),
      ),
    );
    openModal();
    const input = await typeAndSettle("مدر");
    key(input, "ArrowUp");

    expect(input.getAttribute("aria-activedescendant")).toBe(
      "azad-search-active",
    );
  });

  it("ignores keydown events that do not target the search input", () => {
    openModal();
    const input = document.getElementById("azad-search-input");
    document.body.dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }),
    );

    expect(input.getAttribute("aria-activedescendant")).toBeNull();
  });

  it("steps ArrowUp back through the result list", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          schools: [
            { title: "أ", subtitle: "1", url: "/1", icon: "school" },
            { title: "ب", subtitle: "2", url: "/2", icon: "school" },
          ],
        }),
      ),
    );
    openModal();
    const input = await typeAndSettle("مدر");
    key(input, "ArrowDown");
    key(input, "ArrowDown");
    key(input, "ArrowUp");

    expect(input.getAttribute("aria-activedescendant")).toBe(
      "azad-search-active",
    );
  });

  it("uses the provided labels for hints and error text", async () => {
    window.AzadSearchLabels = {
      startTyping: "اكتب!",
      error: "خطأ!",
      noResults: "لا نتائج",
      title: "بحث",
      placeholder: "؟",
      searchIcon: "",
    };
    openModal();
    await typeAndSettle("a");
    expect(document.querySelector(".azad-search-empty").textContent).toBe(
      "اكتب!",
    );

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 503 }),
    );
    await typeAndSettle("مدر");
    expect(
      document.querySelector(".azad-search-empty--error").textContent,
    ).toBe("خطأ!");

    closeModal();
    expect(document.getElementById("azad-search-results").textContent).toBe(
      "اكتب!",
    );
  });
});

// ═════════════════════════════════════════════════════════════════════
// charts.js — CSS variable / ratio fallbacks
// ═════════════════════════════════════════════════════════════════════

describe("charts.js — fallback arms", () => {
  let ctx;

  beforeEach(() => {
    ctx = makeCtx();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(ctx);
    vi.stubGlobal("getComputedStyle", () => ({ getPropertyValue: () => "" }));
    Object.defineProperty(window, "devicePixelRatio", {
      configurable: true,
      value: 0,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  function render(attrs) {
    document.body.innerHTML = `<canvas ${attrs}></canvas>`;
    const canvas = document.querySelector("canvas");
    canvas.getBoundingClientRect = vi.fn().mockReturnValue({
      width: 300,
      height: 150,
    });
    renderChart(canvas);
    return canvas;
  }

  it("bar chart falls back for pixel ratio, CSS vars and missing labels", () => {
    render(
      `data-chart="bar" data-chart-title="عنوان" data-chart-labels='["أ"]' data-chart-values='[3,5]'`,
    );

    expect(ctx.fillText).toHaveBeenCalledWith("عنوان", 150, 18);
    expect(ctx.fillText).toHaveBeenCalledWith("5", expect.any(Number), expect.any(Number));
    expect(ctx.fillRect).toHaveBeenCalled();
  });

  it("doughnut chart survives a zero total and label-less legend", () => {
    render(
      `data-chart="doughnut" data-chart-title="دائري" data-chart-values='[0,0]'`,
    );

    expect(ctx.arc).toHaveBeenCalled();
    expect(ctx.fillText).toHaveBeenCalledWith("دائري", 150, 18);
  });
});

// ═════════════════════════════════════════════════════════════════════
// ui.js — element guard arms
// ═════════════════════════════════════════════════════════════════════

describe("ui.js — guard arms", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
    delete window.AzadConfirmDefaults;
  });

  it("password toggle ignores a wrap without an input", () => {
    document.body.innerHTML = `
      <div class="azad-field__input-wrap--password">
        <button data-password-toggle>eye</button>
      </div>`;
    initPasswordToggle();
    expect(() => click(document.querySelector("[data-password-toggle]"))).not.toThrow();
  });

  it("confirm uses the defaults message when the trigger has none", () => {
    document.body.innerHTML = `<button data-confirm="">حذف</button>`;
    window.AzadConfirmDefaults = { message: "افتراضي" };
    const confirmSpy = vi.fn().mockReturnValue(false);
    vi.stubGlobal("confirm", confirmSpy);
    initConfirmDialogs();
    click(document.querySelector("[data-confirm]"));

    expect(confirmSpy).toHaveBeenCalledWith("افتراضي");
  });

  it("confirm dialogs skip clicks that land directly on the form", () => {
    document.body.innerHTML = `<form data-confirm="متأكد؟"></form>`;
    const confirmSpy = vi.fn();
    vi.stubGlobal("confirm", confirmSpy);
    initConfirmDialogs();
    click(document.querySelector("form"));

    expect(confirmSpy).not.toHaveBeenCalled();
  });

  it("falls back to the generic confirm message without defaults", () => {
    document.body.innerHTML = `<button data-confirm="">x</button>`;
    const confirmSpy = vi.fn().mockReturnValue(false);
    vi.stubGlobal("confirm", confirmSpy);
    initConfirmDialogs();
    click(document.querySelector("[data-confirm]"));

    expect(confirmSpy).toHaveBeenCalledWith("هل أنت متأكد؟");
  });

  it("help tooltips ignore triggers without a described-by target", () => {
    document.body.innerHTML = `<button data-help-tooltip>x</button>`;
    initHelpTooltips();
    expect(() => click(document.querySelector("[data-help-tooltip]"))).not.toThrow();
  });

  it("actions dropdown ignores a dropdown without a menu", () => {
    document.body.innerHTML = `
      <div data-actions-dropdown><button data-actions-toggle>x</button></div>`;
    initActionsDropdowns();
    expect(() =>
      click(document.querySelector("[data-actions-toggle]")),
    ).not.toThrow();
  });
});

// ═════════════════════════════════════════════════════════════════════
// bulk.js — guard arms + Arabic message fallbacks
// ═════════════════════════════════════════════════════════════════════

describe("bulk.js — guard arms", () => {
  const originalToast = window.AzadToast;

  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
    window.AzadToast = originalToast;
    delete window.AzadBulkLabels;
  });

  function bulkTable() {
    document.body.innerHTML = `
      <div data-bulk-bar>
        <select data-bulk-action-select>
          <option value="delete" data-confirm="تأكيد؟">حذف</option>
        </select>
        <button data-bulk-apply>تطبيق</button>
      </div>
      <table data-bulk-entity="users">
        <tr><td><input type="checkbox" data-bulk-id="7" checked></td></tr>
      </table>`;
  }

  it("updateBulkBar returns when no bulk bar precedes the table", () => {
    document.body.innerHTML = `
      <table data-bulk-entity="users">
        <tr><td><input type="checkbox" data-bulk-id="1"></td></tr>
      </table>`;
    expect(() => updateBulkBar(document.querySelector("table"))).not.toThrow();
  });

  it("updateBulkBar returns when the preceding element is not a bulk bar", () => {
    document.body.innerHTML = `
      <div id="other"></div>
      <table data-bulk-entity="users">
        <tr><td><input type="checkbox" data-bulk-id="1"></td></tr>
      </table>`;
    expect(() => updateBulkBar(document.querySelector("table"))).not.toThrow();
  });

  it("ignores a select-all change outside any bulk table", () => {
    document.body.innerHTML = `<input type="checkbox" data-bulk-select-all>`;
    expect(() =>
      document
        .querySelector("[data-bulk-select-all]")
        .dispatchEvent(new Event("change", { bubbles: true })),
    ).not.toThrow();
  });

  it("ignores an apply click whose sibling is not a bulk table", () => {
    document.body.innerHTML = `
      <div data-bulk-bar><button data-bulk-apply>x</button></div>
      <p id="not-a-table"></p>`;
    expect(() => click(document.querySelector("[data-bulk-apply]"))).not.toThrow();
  });

  it("falls back to Arabic messages when AzadBulkLabels is absent", async () => {
    window.AzadToast = { show: vi.fn() };
    bulkTable();
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ success: false }),
      }),
    );

    click(document.querySelector("[data-bulk-apply]"));
    await vi.waitFor(() =>
      expect(window.AzadToast.show).toHaveBeenCalledWith(
        "فشل تنفيذ الإجراء",
        "error",
      ),
    );
  });

  it("shows the network fallback error when the request fails", async () => {
    window.AzadToast = { show: vi.fn() };
    bulkTable();
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));

    click(document.querySelector("[data-bulk-apply]"));
    await vi.waitFor(() =>
      expect(window.AzadToast.show).toHaveBeenCalledWith(
        "حدث خطأ أثناء تنفيذ الإجراء الجماعي",
        "error",
      ),
    );
  });

  it("uses the AzadBulkLabels messages when they exist", async () => {
    window.AzadToast = { show: vi.fn() };
    window.AzadBulkLabels = { actionFailed: "فشل مخصص", error: "خطأ مخصص" };
    bulkTable();
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ success: false }),
      }),
    );
    click(document.querySelector("[data-bulk-apply]"));
    await vi.waitFor(() =>
      expect(window.AzadToast.show).toHaveBeenCalledWith("فشل مخصص", "error"),
    );

    window.AzadToast.show.mockClear();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    click(document.querySelector("[data-bulk-apply]"));
    await vi.waitFor(() =>
      expect(window.AzadToast.show).toHaveBeenCalledWith("خطأ مخصص", "error"),
    );
  });

  it("applies without a confirm prompt when the option has no confirm text", async () => {
    window.AzadToast = { show: vi.fn() };
    document.body.innerHTML = `
      <div data-bulk-bar>
        <select data-bulk-action-select>
          <option value="archive">أرشفة</option>
        </select>
        <button data-bulk-apply>تطبيق</button>
      </div>
      <table data-bulk-entity="users">
        <tr><td><input type="checkbox" data-bulk-id="9" checked></td></tr>
      </table>`;
    const confirmSpy = vi.fn().mockReturnValue(true);
    vi.stubGlobal("confirm", confirmSpy);
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ success: false }),
    });
    vi.stubGlobal("fetch", fetchSpy);

    click(document.querySelector("[data-bulk-apply]"));
    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    expect(confirmSpy).not.toHaveBeenCalled();
  });
});
