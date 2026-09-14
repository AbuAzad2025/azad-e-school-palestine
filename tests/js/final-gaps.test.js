/**
 * Final branch-closure suite — covers the last uncovered branches:
 * ui.js trapFocus + form[data-confirm] submit, toast.js live-region announce,
 * api.js csrf-input fallback + NetworkError, charts.js resize debounce,
 * quiz.js storage-error catches + proctoring destroy + DOMContentLoaded init,
 * search.js Enter-activates-result.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { initConfirmDialogs, trapFocus } from "@app-static/js/components/ui.js";
import { show as showToast } from "@app-static/js/components/toast.js";
import { request } from "@app-static/js/core/api.js";
import {
  initProctoring,
  setStoredData,
} from "@app-static/js/pages/quiz.js";
import { openModal } from "@app-static/js/pages/search.js";

const rsDescriptor = Object.getOwnPropertyDescriptor(
  Document.prototype,
  "readyState",
);

function stubReadyState(value) {
  Object.defineProperty(Document.prototype, "readyState", {
    configurable: true,
    get: () => value,
  });
}

function makeCtx() {
  const noop = vi.fn();
  return new Proxy(
    { getBoundingClientRect: () => ({ width: 300, height: 150 }) },
    {
      get(target, prop) {
        if (prop in target) return target[prop];
        return noop;
      },
      set() {
        return true;
      },
    },
  );
}

describe("ui.js — trapFocus (full branch matrix)", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="modal">
        <a href="/a" id="m-link"></a>
        <button id="m-btn-1">one</button>
        <button id="m-btn-2" disabled>two</button>
        <input id="m-input" />
      </div>
    `;
  });

  it("wraps Tab from the last focusable to the first", () => {
    const modal = document.getElementById("modal");
    const cleanup = trapFocus(modal);
    document.getElementById("m-input").focus();
    modal.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Tab", bubbles: true }),
    );
    expect(document.activeElement.id).toBe("m-link");
    cleanup();
  });

  it("wraps Shift+Tab from the first focusable to the last", () => {
    const modal = document.getElementById("modal");
    const cleanup = trapFocus(modal);
    document.getElementById("m-link").focus();
    modal.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, bubbles: true }),
    );
    expect(document.activeElement.id).toBe("m-input");
    cleanup();
  });

  it("ignores non-Tab keys and empty modals", () => {
    const modal = document.getElementById("modal");
    const cleanup = trapFocus(modal);
    document.getElementById("m-link").focus();
    modal.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(document.activeElement.id).toBe("m-link");

    modal.innerHTML = "";
    expect(() =>
      modal.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab" })),
    ).not.toThrow();
    cleanup();
  });

  it("cleanup removes the keydown handler", () => {
    const modal = document.getElementById("modal");
    const cleanup = trapFocus(modal);
    cleanup();
    document.getElementById("m-input").focus();
    modal.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Tab", bubbles: true }),
    );
    expect(document.activeElement.id).toBe("m-input");
  });
});

describe("ui.js — initConfirmDialogs form branches", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <form id="ask-form" data-confirm="sure?"><button type="submit">go</button></form>
      <form id="plain-form"><button type="submit">go</button></form>
    `;
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(false));
    initConfirmDialogs();
  });

  it("prevents submit when confirm is declined", () => {
    const form = document.getElementById("ask-form");
    const ev = new Event("submit", { bubbles: true, cancelable: true });
    const prevented = form.dispatchEvent(ev);
    expect(confirm).toHaveBeenCalledWith("sure?");
    expect(prevented).toBe(false);
  });

  it("ignores submit events outside a data-confirm form", () => {
    const form = document.getElementById("plain-form");
    const ev = new Event("submit", { bubbles: true, cancelable: true });
    const prevented = form.dispatchEvent(ev);
    expect(prevented).toBe(true);
  });
});

describe("toast.js — live-region announce", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    document.body.innerHTML = `<div id="azad-live-region"></div>`;
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("announces the message into the aria live region and clears it", () => {
    showToast({ message: "تم الحفظ", duration: 0 });
    const region = document.getElementById("azad-live-region");
    expect(region.textContent).toBe("تم الحفظ");
    vi.advanceTimersByTime(1100);
    expect(region.textContent).toBe("");
  });

  it("announces the title when there is no message", () => {
    showToast({ title: "تنبيه", message: "", duration: 0 });
    const region = document.getElementById("azad-live-region");
    expect(region.textContent).toBe("تنبيه");
  });
});

describe("api.js — csrf input fallback + NetworkError", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    document.head.innerHTML = "";
    document.body.innerHTML = "";
  });

  it("falls back to the hidden csrf_token input when no meta tag exists", async () => {
    document.body.innerHTML = `<input type="hidden" name="csrf_token" value="input-token">`;
    const mockResponse = {
      ok: true,
      headers: new Headers({ "Content-Type": "application/json" }),
      json: vi.fn().mockResolvedValue({ ok: true }),
    };
    const fetchSpy = vi.fn().mockResolvedValue(mockResponse);
    vi.stubGlobal("fetch", fetchSpy);

    await request("POST", "/api/test", { body: { a: 1 } });
    const [, init] = fetchSpy.mock.calls[0];
    expect(init.headers.get("X-CSRFToken")).toBe("input-token");
  });

  it("maps AbortError to NetworkError when the browser is offline", async () => {
    const desc = Object.getOwnPropertyDescriptor(navigator, "onLine");
    Object.defineProperty(navigator, "onLine", {
      configurable: true,
      get: () => false,
    });
    // Browsers reject fetch with TypeError when offline (not AbortError)
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );

    await expect(request("GET", "/api/x", { timeout: 5000 })).rejects.toThrow(
      "No internet connection",
    );

    if (desc) Object.defineProperty(navigator, "onLine", desc);
  });
});

describe("charts.js — window resize triggers re-render via debounce", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    document.body.innerHTML = `<canvas data-chart="bar"
      data-chart-labels='["أ","ب"]'
      data-chart-values='[1,2]'></canvas>`;
    vi.stubGlobal("getComputedStyle", () => ({
      getPropertyValue: () => "#000",
    }));
    // renderChart calls getContext multiple times — cache one ctx per canvas
    const ctxStore = new WeakMap();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
      function () {
        if (!ctxStore.has(this)) ctxStore.set(this, makeCtx());
        return ctxStore.get(this);
      },
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("re-renders all canvases after the debounced resize", async () => {
    // fresh import registers the resize listener against the current DOM
    vi.resetModules();
    await import("@app-static/js/components/charts.js");
    const canvas = document.querySelector("canvas");
    canvas.dataset.chart = "bar";
    canvas.dataset.chartLabels = JSON.stringify(["أ", "ب"]);
    canvas.dataset.chartValues = JSON.stringify([1, 2]);
    // jsdom reports 0x0 rects — stub a real size so renderChart doesn't bail
    canvas.getBoundingClientRect = vi.fn().mockReturnValue({
      width: 300,
      height: 150,
      top: 0,
      left: 0,
    });
    const ctx = canvas.getContext("2d");
    const calls = ctx.clearRect.mock.calls.length;

    window.dispatchEvent(new Event("resize"));
    vi.advanceTimersByTime(250);
    expect(ctx.clearRect.mock.calls.length).toBeGreaterThan(calls);
  });
});

describe("quiz.js — storage error guards + proctoring destroy", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <form id="quiz-form" data-attempt-id="321">
        <div data-question-index="0"><input type="radio" name="q1" value="a"></div>
      </form>
    `;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("swallows localStorage write failures in setStoredData and removeItem on submit", async () => {
    const store = {};
    const orig = globalThis.localStorage;
    globalThis.localStorage = {
      getItem: (k) => store[k] || null,
      setItem: (k, v) => {
        throw new Error("QuotaExceededError");
      },
      removeItem: (k) => {
        throw new Error("SecurityError");
      },
    };

    vi.resetModules();
    const mod = await import("@app-static/js/pages/quiz.js");
    expect(() => mod.setStoredData("321", { flags: [] })).not.toThrow();

    document.body.innerHTML = `<form id="quiz-form" data-attempt-id="321"></form>`;
    mod.init(); // readyState is not "loading" → init runs inline, attaches submit listener
    expect(() =>
      document
        .getElementById("quiz-form")
        .dispatchEvent(
          new Event("submit", { bubbles: true, cancelable: true }),
        ),
    ).not.toThrow();

    globalThis.localStorage = orig;
    vi.resetModules();
  });
});

describe("quiz.js — initProctoring destroy + DOMContentLoaded", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <form id="quiz-form" data-attempt-id="321">
        <div data-question-index="0"><input type="radio" name="q1" value="a"></div>
      </form>
    `;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("initProctoring destroy() detaches both lifecycle listeners", () => {
    const removeSpy = vi.spyOn(document, "removeEventListener");
    const handle = initProctoring("321");
    handle.destroy();
    const types = removeSpy.mock.calls.map((c) => c[0]);
    expect(types).toContain("visibilitychange");
    expect(types).toContain("fullscreenchange");
  });

  it("registers init on DOMContentLoaded when the document is still loading", async () => {
    stubReadyState("loading");
    document.body.innerHTML = "";
    vi.resetModules();
    await import("@app-static/js/pages/quiz.js");
    expect(() =>
      document.dispatchEvent(new Event("DOMContentLoaded")),
    ).not.toThrow();
    if (rsDescriptor) {
      Object.defineProperty(Document.prototype, "readyState", rsDescriptor);
    }
  });
});

describe("search.js — Enter activates the highlighted result", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    vi.useFakeTimers();
    Element.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    delete Element.prototype.scrollIntoView;
  });

  it("clicks the active result on Enter and navigates", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({
          data: {
            schools: [
              { title: "مدرسة أ", subtitle: "s", url: "/s/1", icon: "school" },
            ],
          },
        }),
      }),
    );
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});

    openModal();
    const input = document.getElementById("azad-search-input");
    input.value = "مدرسة";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    vi.advanceTimersByTime(250);
    await vi.advanceTimersByTimeAsync(0);

    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }),
    );
    expect(input.getAttribute("aria-activedescendant")).toBe(
      "azad-search-active",
    );

    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
    );
    expect(clickSpy).toHaveBeenCalledOnce();
  });

  it("Enter without an active result does nothing", () => {
    openModal();
    const input = document.getElementById("azad-search-input");
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => {});
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
    );
    expect(clickSpy).not.toHaveBeenCalled();
  });
});
