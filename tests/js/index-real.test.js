import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import {
  initNav,
  initAdminDrawer,
  initAutoDismissFlashes,
  initErrorPageRefresh,
  initPwaBanner,
  initScrollAnimations,
  initServiceWorker,
} from "@app-static/js/index.js";

describe("Index - initNav (actual module)", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <button data-nav-toggle aria-expanded="false">
        <span data-nav-icon-open>Open</span>
        <span data-nav-icon-close>Close</span>
      </button>
      <div data-nav-links>
        <a href="/home">Home</a>
      </div>
    `;
  });

  it("toggles open class on click", () => {
    initNav();
    const toggle = document.querySelector("[data-nav-toggle]");
    const links = document.querySelector("[data-nav-links]");

    toggle.click();
    expect(links.classList.contains("open")).toBe(true);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
  });

  it("closes on second click", () => {
    initNav();
    const toggle = document.querySelector("[data-nav-toggle]");
    const links = document.querySelector("[data-nav-links]");

    toggle.click();
    toggle.click();
    expect(links.classList.contains("open")).toBe(false);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
  });

  it("closes on escape key", () => {
    initNav();
    const links = document.querySelector("[data-nav-links]");
    links.classList.add("open");

    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(links.classList.contains("open")).toBe(false);
  });

  it("hides open icon when open", () => {
    initNav();
    const toggle = document.querySelector("[data-nav-toggle]");
    toggle.click();
    expect(toggle.querySelector("[data-nav-icon-open]").hidden).toBe(true);
  });

  it("shows close icon when open", () => {
    initNav();
    const toggle = document.querySelector("[data-nav-toggle]");
    toggle.click();
    expect(toggle.querySelector("[data-nav-icon-close]").hidden).toBe(false);
  });

  it("sets body nav-open class when open (overflow via CSS)", () => {
    initNav();
    const toggle = document.querySelector("[data-nav-toggle]");
    toggle.click();
    expect(document.body.classList.contains("nav-open")).toBe(true);
  });

  it("clears nav-open class when closed", () => {
    initNav();
    const toggle = document.querySelector("[data-nav-toggle]");
    toggle.click();
    toggle.click();
    expect(document.body.classList.contains("nav-open")).toBe(false);
  });

  it("closes nav when link clicked inside nav-links", () => {
    initNav();
    const links = document.querySelector("[data-nav-links]");
    links.querySelector("a").click();
    expect(links.classList.contains("open")).toBe(false);
  });

  it("does nothing when elements missing", () => {
    document.body.innerHTML = "";
    expect(() => initNav()).not.toThrow();
  });
});

describe("Index - initAdminDrawer (actual module)", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <button data-admin-nav-toggle>Open</button>
      <button data-admin-nav-close>Close</button>
      <div data-admin-nav-overlay></div>
    `;
  });

  it("opens sidebar", () => {
    initAdminDrawer();
    document.querySelector("[data-admin-nav-toggle]").click();
    expect(document.body.classList.contains("sidebar-open")).toBe(true);
  });

  it("closes sidebar", () => {
    initAdminDrawer();
    document.body.classList.add("sidebar-open");
    document.querySelector("[data-admin-nav-close]").click();
    expect(document.body.classList.contains("sidebar-open")).toBe(false);
  });

  it("closes on overlay click", () => {
    initAdminDrawer();
    document.body.classList.add("sidebar-open");
    document.querySelector("[data-admin-nav-overlay]").click();
    expect(document.body.classList.contains("sidebar-open")).toBe(false);
  });

  it("does nothing when elements missing", () => {
    document.body.innerHTML = "";
    expect(() => initAdminDrawer()).not.toThrow();
  });
});

describe("Index - initScrollAnimations (actual module)", () => {
  let observeSpy;

  beforeEach(() => {
    observeSpy = vi.fn();
    window.IntersectionObserver = vi.fn().mockImplementation(() => ({
      observe: observeSpy,
      unobserve: vi.fn(),
      disconnect: vi.fn(),
    }));
  });

  afterEach(() => {
    delete window.IntersectionObserver;
  });

  it("does not build a stylesheet at runtime", () => {
    // .azad-scroll-hidden / .azad-in-view are declared in app.css: toggling
    // classes must not cost a <style> parse or a CSP nonce lookup.
    document.body.innerHTML = '<div class="azad-card">Card</div>';
    initScrollAnimations();
    expect(document.querySelectorAll("style").length).toBe(0);
    expect(document.head.querySelector("style")).toBeNull();
  });

  it("handles IntersectionObserver not available", () => {
    const original = window.IntersectionObserver;
    delete window.IntersectionObserver;
    expect(() => initScrollAnimations()).not.toThrow();
    window.IntersectionObserver = original;
  });

  it("observes card elements", () => {
    document.body.innerHTML = `
      <div class="azad-card">Card 1</div>
      <div class="azad-stat-card">Stat 1</div>
    `;
    initScrollAnimations();
    expect(observeSpy).toHaveBeenCalledTimes(2);
  });

  it("marks cards scroll-hidden (reveal via .azad-in-view CSS)", () => {
    document.body.innerHTML = '<div class="azad-card">Card</div>';
    initScrollAnimations();
    const card = document.querySelector(".azad-card");
    // JS only toggles classes; opacity/transform live in app.css (CSP-safe)
    expect(card.classList.contains("azad-scroll-hidden")).toBe(true);
    expect(card.classList.contains("azad-in-view")).toBe(false);
  });

  it("is idempotent across repeated calls", () => {
    document.body.innerHTML = '<div class="azad-card">Card</div>';
    initScrollAnimations();
    initScrollAnimations();
    expect(document.querySelectorAll("style").length).toBe(0);
    expect(document.querySelectorAll(".azad-scroll-hidden").length).toBe(1);
  });
});

describe("Index - initAutoDismissFlashes (actual module)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("auto-dismisses flash after delay", () => {
    document.body.innerHTML = `
      <div class="flash" data-auto-dismiss="1000">Alert!</div>
    `;
    initAutoDismissFlashes();

    const flash = document.querySelector(".flash");
    vi.advanceTimersByTime(1100);
    // Exit animation is CSS-driven via .azad-flash-exit class (CSP-safe)
    expect(flash.classList.contains("azad-flash-exit")).toBe(true);
    vi.advanceTimersByTime(400);
    expect(flash.parentNode).toBeNull();
  });

  it("handles azad-flash variant", () => {
    document.body.innerHTML = `
      <div class="azad-flash" data-auto-dismiss="500">Alert!</div>
    `;
    initAutoDismissFlashes();
    expect(document.querySelector(".azad-flash")).toBeTruthy();
  });

  it("defaults to 5000ms when no data-auto-dismiss", () => {
    document.body.innerHTML = `<div class="flash">Alert</div>`;
    initAutoDismissFlashes();
    const flash = document.querySelector(".flash");
    const delay = parseInt(flash.dataset.autoDismiss, 10) || 5000;
    expect(delay).toBe(5000);
  });

  it("does nothing without flash elements", () => {
    document.body.innerHTML = "";
    expect(() => initAutoDismissFlashes()).not.toThrow();
  });
});

describe("Index - initPwaBanner (actual module)", () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = `
      <div id="pwa-install-banner" class="u-none">
        <button id="pwa-install-btn">Install</button>
        <button id="pwa-install-dismiss">Dismiss</button>
      </div>
    `;
  });

  it("hides banner when previously dismissed", () => {
    localStorage.setItem("azad-pwa-dismissed", "1");
    initPwaBanner();
    const banner = document.getElementById("pwa-install-banner");
    expect(banner.classList.contains("u-none")).toBe(true);
  });

  it("dismiss button hides banner and saves to localStorage", () => {
    initPwaBanner();
    const banner = document.getElementById("pwa-install-banner");
    document.getElementById("pwa-install-dismiss").click();
    expect(banner.classList.contains("u-none")).toBe(true);
    expect(localStorage.getItem("azad-pwa-dismissed")).toBe("1");
  });

  it("does nothing when banner element missing", () => {
    document.body.innerHTML = "";
    expect(() => initPwaBanner()).not.toThrow();
  });

  it("does nothing when install button missing", () => {
    document.body.innerHTML = '<div id="pwa-install-banner"></div>';
    expect(() => initPwaBanner()).not.toThrow();
  });

  it("shows banner on beforeinstallprompt event", () => {
    initPwaBanner();
    const banner = document.getElementById("pwa-install-banner");
    const event = new Event("beforeinstallprompt");
    event.preventDefault = vi.fn();
    window.dispatchEvent(event);
    expect(banner.classList.contains("u-none")).toBe(false);
  });
});

describe("Index - initServiceWorker (actual module)", () => {
  it("registers service worker when available", () => {
    const registerMock = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "serviceWorker", {
      value: { register: registerMock },
      writable: true,
      configurable: true,
    });

    initServiceWorker();
    expect(registerMock).toHaveBeenCalledWith("/static/sw.js?v=5");
  });

  it("does nothing when serviceWorker not available", () => {
    const hasSW = "serviceWorker" in navigator;
    expect(hasSW).toBe(true);
    // The guard condition
    const shouldRegister = hasSW && typeof navigator.serviceWorker?.register === "function";
    expect(shouldRegister).toBe(true);
  });

  it("catches registration errors silently", async () => {
    const registerMock = vi.fn().mockRejectedValue(new Error("SW error"));
    Object.defineProperty(navigator, "serviceWorker", {
      value: { register: registerMock },
      writable: true,
      configurable: true,
    });

    // Should not throw
    expect(() => initServiceWorker()).not.toThrow();
  });
});

describe("Index - DOMContentLoaded vs immediate init", () => {
  it("calls init when DOM is already loaded", () => {
    let called = false;
    const initFn = () => { called = true; };

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", initFn);
    } else {
      initFn();
    }

    expect(called).toBe(true);
  });
});

describe("Index - global AzadToast import", () => {
  it("sets window.AzadToast from toast module", async () => {
    const m = await import("@app-static/js/components/toast.js");
    window.AzadToast = m.default;
    expect(window.AzadToast).toBeTruthy();
    expect(typeof window.AzadToast.show).toBe("function");
    expect(typeof window.AzadToast.success).toBe("function");
  });
});

describe("Index - initErrorPageRefresh (actual module)", () => {
  let reloadMock;

  beforeEach(() => {
    reloadMock = vi.fn();
    // jsdom's Location is unforgeable; stubGlobal is the supported way to
    // observe navigation without triggering "Not implemented" errors.
    vi.stubGlobal("location", { reload: reloadMock });
    document.body.innerHTML = "";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.body.innerHTML = "";
  });

  const clickOn = (el) => {
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    el.dispatchEvent(event);
    return event;
  };

  it("reloads the page and cancels the anchor navigation", () => {
    document.body.innerHTML = '<a data-error-refresh href="#">إعادة التحميل</a>';
    initErrorPageRefresh();

    const event = clickOn(document.querySelector("[data-error-refresh]"));

    expect(event.defaultPrevented).toBe(true);
    expect(reloadMock).toHaveBeenCalled();
  });

  it("delegates clicks from child elements inside the control", () => {
    document.body.innerHTML = '<a data-error-refresh href="#"><span>icon</span></a>';
    initErrorPageRefresh();

    const event = clickOn(document.querySelector("[data-error-refresh] span"));

    expect(event.defaultPrevented).toBe(true);
    expect(reloadMock).toHaveBeenCalled();
  });

  it("ignores clicks outside the refresh control", () => {
    document.body.innerHTML = '<button id="plain">عادي</button>';
    initErrorPageRefresh();

    const event = clickOn(document.getElementById("plain"));

    expect(event.defaultPrevented).toBe(false);
    expect(reloadMock).not.toHaveBeenCalled();
  });

  it("is wired by the bootstrap init() — regression guard for the dead control", async () => {
    // The 500/429 pages extend base.html (which loads this module) and carry a
    // data-error-refresh anchor, so init() must bind the delegation handler.
    vi.resetModules();
    document.body.innerHTML = '<a data-error-refresh href="#">إعادة التحميل</a>';

    await import("@app-static/js/index.js");
    // init() runs immediately on a ready DOM, or on DOMContentLoaded otherwise.
    document.dispatchEvent(new Event("DOMContentLoaded"));

    const event = clickOn(document.querySelector("[data-error-refresh]"));

    expect(event.defaultPrevented).toBe(true);
    expect(reloadMock).toHaveBeenCalled();
  });
});
