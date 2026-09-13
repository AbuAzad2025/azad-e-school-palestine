/**
 * Remaining branch coverage: video_player.js (MANIFEST_PARSED handler,
 * vertical watermark bounce) and index.js (IntersectionObserver entries,
 * PWA deferred-install click, DOMContentLoaded bootstrap).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Import the IIFE once — it attaches window.AzadVideoPlayer
import "@app-static/js/video_player.js";

const { AzadVideoPlayer } = window;

function makeCtx() {
  return {
    clearRect: vi.fn(),
    save: vi.fn(),
    restore: vi.fn(),
    fillText: vi.fn(),
    font: "",
    fillStyle: "",
    shadowColor: "",
    shadowBlur: 0,
  };
}

function makeHls() {
  const handlers = {};
  const instance = {
    loadSource: vi.fn(),
    attachMedia: vi.fn(),
    on: (evt, cb) => {
      handlers[evt] = cb;
    },
    destroy: vi.fn(),
    startLoad: vi.fn(),
    recoverMediaError: vi.fn(),
  };
  window.Hls = Object.assign(vi.fn().mockImplementation(() => instance), {
    isSupported: () => true,
    Events: { MANIFEST_PARSED: "manifest", ERROR: "error" },
    ErrorTypes: { NETWORK_ERROR: "networkError", MEDIA_ERROR: "mediaError" },
  });
  return { instance, handlers };
}

const rsDescriptor = Object.getOwnPropertyDescriptor(Document.prototype, "readyState");

function stubReadyState(value) {
  Object.defineProperty(Document.prototype, "readyState", {
    configurable: true,
    get: () => value,
  });
}

beforeEach(() => {
  document.body.innerHTML = `<div id="player-box"></div>`;
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => makeCtx());
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  delete window.Hls;
  if (rsDescriptor) {
    Object.defineProperty(Document.prototype, "readyState", rsDescriptor);
  }
});

describe("AzadVideoPlayer — remaining branches", () => {
  it("resizes the watermark canvas when the manifest is parsed", () => {
    const { handlers } = makeHls();
    const p = new AzadVideoPlayer("player-box", "/s.m3u8", { enableWatermark: true });
    const spy = vi.spyOn(p, "_resizeCanvas");
    expect(spy).not.toHaveBeenCalled();
    handlers["manifest"]();
    expect(spy).toHaveBeenCalledTimes(1);
    p.destroy();
  });

  it("bounces the watermark off both vertical edges", () => {
    makeHls();
    const p = new AzadVideoPlayer("player-box", "/s.m3u8", { enableWatermark: true });
    vi.spyOn(Math, "random").mockReturnValue(0); // deterministic drift

    // Above the upper bound → direction flips and position is clamped back
    p.watermarkY = 0; // < 20 → out of bounds
    p.watermarkDy = 2;
    p._driftWatermark();
    expect(p.watermarkDy).toBe(-1);
    expect(p.watermarkY).toBe(20);

    // Below the lower bound of maxY (canvas.height - 30) → flips the other way
    p.watermarkY = 2000;
    p.watermarkDy = -2;
    p._driftWatermark();
    expect(p.watermarkDy).toBe(2);
    expect(p.watermarkY).toBeLessThanOrEqual(p.canvas.height - 30);
    p.destroy();
  });
});

describe("index.js — remaining branches", () => {
  let FakeIO;
  beforeEach(() => {
    // restoreAllMocks() in the video block wipes the setup.js matchMedia
    // mock, and importing index.js runs init() → initTheme eagerly.
    vi.stubGlobal("matchMedia", vi.fn().mockImplementation(() => ({ matches: false })));
    document.body.innerHTML = `
      <div class="azad-card" id="card1"></div>
      <div class="azad-card" id="card2"></div>
    `;
    // Observable IntersectionObserver double (class scoped to beforeEach)
    const IOClass = class {
      constructor(cb, opts) {
        IOClass.last = this;
        this.cb = cb;
        this.opts = opts;
        this.observed = [];
      }
      observe(el) {
        this.observed.push(el);
      }
      unobserve(el) {
        this.unobserved = el;
      }
      disconnect() {}
    };
    FakeIO = IOClass;
    vi.stubGlobal("IntersectionObserver", FakeIO);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    delete FakeIO.last;
  });

  it("adds azad-in-view and unobserves only intersecting entries", async () => {
    const { initScrollAnimations } = await import("@app-static/js/index.js");
    initScrollAnimations();
    const io = FakeIO.last;
    expect(io).toBeTruthy();
    expect(io.observed.map((el) => el.id)).toEqual(["card1", "card2"]);

    const card1 = document.getElementById("card1");
    const card2 = document.getElementById("card2");
    io.cb([
      { isIntersecting: true, target: card1 },
      { isIntersecting: false, target: card2 },
    ]);
    expect(card1.classList.contains("azad-in-view")).toBe(true);
    expect(card2.classList.contains("azad-in-view")).toBe(false);
    expect(io.unobserved).toBe(card1);
  });

  it("gracefully skips scroll animations without IntersectionObserver", async () => {
    // Simulate an old browser: the feature check must fail, not the constructor
    delete window.IntersectionObserver;
    const { initScrollAnimations } = await import("@app-static/js/index.js");
    expect(() => initScrollAnimations()).not.toThrow();
  });

  it("PWA install button uses the deferred prompt and hides the banner", async () => {
    localStorage.clear();
    document.body.innerHTML = `
      <div id="pwa-install-banner" class="u-none">
        <button id="pwa-install-btn">Install</button>
        <button id="pwa-install-dismiss">Dismiss</button>
      </div>
    `;
    const { initPwaBanner } = await import("@app-static/js/index.js");
    initPwaBanner();
    const banner = document.getElementById("pwa-install-banner");

    // Clicking before the prompt event is a no-op
    document.getElementById("pwa-install-btn").click();
    expect(banner.classList.contains("u-none")).toBe(true);

    const prompt = vi.fn();
    const ev = new Event("beforeinstallprompt");
    Object.assign(ev, {
      preventDefault: vi.fn(),
      prompt,
      userChoice: Promise.resolve({ outcome: "accepted" }),
    });
    window.dispatchEvent(ev);
    expect(ev.preventDefault).toHaveBeenCalled();
    expect(banner.classList.contains("u-none")).toBe(false);

    document.getElementById("pwa-install-btn").click();
    await vi.waitFor(() => expect(prompt).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(banner.classList.contains("u-none")).toBe(true));

    // deferredPrompt cleared → a second click cannot re-prompt
    document.getElementById("pwa-install-btn").click();
    expect(prompt).toHaveBeenCalledTimes(1);
  });

  it("bootstraps the full init chain on DOMContentLoaded when still loading", async () => {
    stubReadyState("loading");
    vi.stubGlobal("matchMedia", vi.fn().mockImplementation(() => ({ matches: false }))); // initTheme
    document.body.innerHTML = `<div class="azad-card" id="card1"></div>`;
    vi.resetModules(); // fresh module instance so the deferred-init branch runs
    await import("@app-static/js/index.js");
    // Not initialized yet
    expect(FakeIO.last).toBeUndefined();
    document.dispatchEvent(new Event("DOMContentLoaded"));
    // init() ran the chain through initScrollAnimations
    expect(FakeIO.last).toBeTruthy();
  });
});
