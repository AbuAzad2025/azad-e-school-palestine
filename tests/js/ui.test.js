import { describe, it, expect, beforeEach, vi } from "vitest";

describe("UI - delegate", () => {
  it("calls handler when event matches selector", async () => {
    const { delegate } = await import("@app-static/js/components/ui.js");
    document.body.innerHTML = '<div id="container"><button class="btn">Click</button></div>';
    const container = document.getElementById("container");
    const handler = vi.fn();
    delegate(container, ".btn", "click", handler);

    document.querySelector(".btn").click();
    expect(handler).toHaveBeenCalledOnce();
  });

  it("does not call handler for non-matching selector", async () => {
    const { delegate } = await import("@app-static/js/components/ui.js");
    document.body.innerHTML = '<div id="container"><span>Not a button</span></div>';
    const container = document.getElementById("container");
    const handler = vi.fn();
    delegate(container, ".btn", "click", handler);

    document.querySelector("span").click();
    expect(handler).not.toHaveBeenCalled();
  });

  it("supports nested event delegation", async () => {
    const { delegate } = await import("@app-static/js/components/ui.js");
    document.body.innerHTML = '<div id="container"><div class="outer"><button class="btn">Click</button></div></div>';
    const container = document.getElementById("container");
    const handler = vi.fn();
    delegate(container, ".btn", "click", handler);

    document.querySelector(".btn").click();
    expect(handler).toHaveBeenCalledOnce();
  });
});

describe("UI - initPasswordToggle", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div class="azad-field__input-wrap--password">
        <input type="password" value="secret" />
        <button data-password-toggle aria-pressed="false">Show</button>
      </div>
    `;
  });

  it("toggles password to text on click", async () => {
    const { initPasswordToggle } = await import("@app-static/js/components/ui.js");
    initPasswordToggle();

    const btn = document.querySelector("[data-password-toggle]");
    const input = document.querySelector("input");

    expect(input.type).toBe("password");
    btn.click();
    expect(input.type).toBe("text");
    expect(btn.getAttribute("aria-pressed")).toBe("true");
  });

  it("toggles back to password", async () => {
    const { initPasswordToggle } = await import("@app-static/js/components/ui.js");
    initPasswordToggle();

    const btn = document.querySelector("[data-password-toggle]");
    const input = document.querySelector("input");

    btn.click();
    btn.click();
    expect(input.type).toBe("password");
    expect(btn.getAttribute("aria-pressed")).toBe("false");
  });

  it("does nothing when no parent wrapper", async () => {
    document.body.innerHTML = '<button data-password-toggle>Toggle</button>';
    const { initPasswordToggle } = await import("@app-static/js/components/ui.js");
    initPasswordToggle();

    const btn = document.querySelector("[data-password-toggle]");
    expect(() => btn.click()).not.toThrow();
  });
});

describe("UI - initAccordions", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <button class="accordion-btn" aria-expanded="false">Section</button>
      <div class="accordion-content">Content</div>
    `;
  });

  it("expands accordion on click", async () => {
    const { initAccordions } = await import("@app-static/js/components/ui.js");
    initAccordions();

    const btn = document.querySelector(".accordion-btn");
    const content = document.querySelector(".accordion-content");

    btn.click();
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    expect(content.classList.contains("open")).toBe(true);
  });

  it("collapses accordion on second click", async () => {
    const { initAccordions } = await import("@app-static/js/components/ui.js");
    initAccordions();

    const btn = document.querySelector(".accordion-btn");
    btn.click();
    btn.click();
    expect(btn.getAttribute("aria-expanded")).toBe("false");
  });
});

describe("UI - initTabs", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div class="tabs">
        <a class="tab active" href="#tab1">Tab 1</a>
        <a class="tab" href="#tab2">Tab 2</a>
      </div>
    `;
  });

  it("switches active tab on click", async () => {
    const { initTabs } = await import("@app-static/js/components/ui.js");
    initTabs();

    const tabs = document.querySelectorAll(".tab");
    tabs[1].click();

    expect(tabs[0].classList.contains("active")).toBe(false);
    expect(tabs[1].classList.contains("active")).toBe(true);
  });

  it("prevents default link navigation", async () => {
    const { initTabs } = await import("@app-static/js/components/ui.js");
    initTabs();

    const tab = document.querySelector(".tab");
    const event = new Event("click", { bubbles: true, cancelable: true });
    const preventSpy = vi.spyOn(event, "preventDefault");
    tab.dispatchEvent(event);
    expect(preventSpy).toHaveBeenCalled();
  });
});

describe("UI - initFlashes", () => {
  it("dismisses flash on dismiss button click", async () => {
    document.body.innerHTML = `
      <div class="flash">Alert!<button data-dismiss>×</button></div>
    `;
    const { initFlashes } = await import("@app-static/js/components/ui.js");
    initFlashes();

    document.querySelector("[data-dismiss]").click();
    expect(document.querySelector(".flash")).toBeNull();
  });

  it("dismisses azad-flash variant", async () => {
    document.body.innerHTML = `
      <div class="azad-flash">Alert!<button data-dismiss>×</button></div>
    `;
    const { initFlashes } = await import("@app-static/js/components/ui.js");
    initFlashes();

    document.querySelector("[data-dismiss]").click();
    expect(document.querySelector(".azad-flash")).toBeNull();
  });
});

describe("UI - initUserDropdown", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <button data-user-toggle>Profile</button>
      <div data-user-menu hidden>Menu</div>
    `;
  });

  it("opens user menu on toggle click", async () => {
    const { initUserDropdown } = await import("@app-static/js/components/ui.js");
    initUserDropdown();

    document.querySelector("[data-user-toggle]").click();
    const menu = document.querySelector("[data-user-menu]");
    expect(menu.hidden).toBe(false);
    expect(document.querySelector("[data-user-toggle]").getAttribute("aria-expanded")).toBe("true");
  });

  it("closes user menu on second toggle click", async () => {
    const { initUserDropdown } = await import("@app-static/js/components/ui.js");
    initUserDropdown();

    const toggle = document.querySelector("[data-user-toggle]");
    toggle.click();
    toggle.click();
    expect(document.querySelector("[data-user-menu]").hidden).toBe(true);
  });

  it("closes user menu on outside click", async () => {
    const { initUserDropdown } = await import("@app-static/js/components/ui.js");
    initUserDropdown();

    document.querySelector("[data-user-toggle]").click();
    document.body.click();
    expect(document.querySelector("[data-user-menu]").hidden).toBe(true);
  });
});

describe("UI - initConfirmDialogs", () => {
  beforeEach(() => {
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
    document.body.innerHTML = `
      <button data-confirm="Are you sure?">Delete</button>
      <form data-confirm="Submit?"><button type="submit">Submit</button></form>
    `;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows confirm dialog on click", async () => {
    const { initConfirmDialogs } = await import("@app-static/js/components/ui.js");
    initConfirmDialogs();

    document.querySelector("[data-confirm]").click();
    expect(confirm).toHaveBeenCalledWith("Are you sure?");
  });

  it("prevents default when user cancels", async () => {
    confirm.mockReturnValue(false);
    const { initConfirmDialogs } = await import("@app-static/js/components/ui.js");
    initConfirmDialogs();

    const btn = document.querySelector("[data-confirm]");
    const event = new Event("click", { bubbles: true, cancelable: true });
    const preventSpy = vi.spyOn(event, "preventDefault");
    btn.dispatchEvent(event);
    expect(preventSpy).toHaveBeenCalled();
  });
});

describe("UI - initActionsDropdowns", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div data-actions-dropdown>
        <button data-actions-toggle aria-expanded="false">Actions</button>
        <div data-actions-menu hidden>Menu</div>
      </div>
    `;
  });

  it("opens actions menu on toggle click", async () => {
    const { initActionsDropdowns } = await import("@app-static/js/components/ui.js");
    initActionsDropdowns();

    document.querySelector("[data-actions-toggle]").click();
    const menu = document.querySelector("[data-actions-menu]");
    expect(menu.hidden).toBe(false);
  });

  it("closes actions menu on second click", async () => {
    const { initActionsDropdowns } = await import("@app-static/js/components/ui.js");
    initActionsDropdowns();

    const toggle = document.querySelector("[data-actions-toggle]");
    toggle.click();
    toggle.click();
    expect(document.querySelector("[data-actions-menu]").hidden).toBe(true);
  });

  it("closes all menus on outside click", async () => {
    const { initActionsDropdowns } = await import("@app-static/js/components/ui.js");
    initActionsDropdowns();

    document.querySelector("[data-actions-toggle]").click();
    document.body.click();
    expect(document.querySelector("[data-actions-menu]").hidden).toBe(true);
  });
});

describe("UI - initRipple", () => {
  it("creates ripple element on button click", async () => {
    document.body.innerHTML = '<button class="azad-btn">Click me</button>';
    const { initRipple } = await import("@app-static/js/components/ui.js");
    initRipple();

    const btn = document.querySelector(".azad-btn");
    btn.getBoundingClientRect = vi.fn().mockReturnValue({
      x: 0, y: 0, width: 200, height: 50, top: 0, left: 0, right: 200, bottom: 50,
    });
    btn.click();

    const ripple = btn.querySelector(".azad-ripple");
    expect(ripple).toBeTruthy();
  });

  it("removes ripple after animation", async () => {
    vi.useFakeTimers();
    document.body.innerHTML = '<button class="azad-btn-primary">Click</button>';
    const { initRipple } = await import("@app-static/js/components/ui.js");
    initRipple();

    const btn = document.querySelector(".azad-btn-primary");
    btn.getBoundingClientRect = vi.fn().mockReturnValue({
      x: 0, y: 0, width: 200, height: 50, top: 0, left: 0, right: 200, bottom: 50,
    });
    btn.click();

    expect(btn.querySelector(".azad-ripple")).toBeTruthy();
    vi.advanceTimersByTime(700);
    expect(btn.querySelector(".azad-ripple")).toBeNull();
    vi.useRealTimers();
  });

  it("does not create ripple for non-button clicks", async () => {
    document.body.innerHTML = '<div class="other">No ripple</div>';
    const { initRipple } = await import("@app-static/js/components/ui.js");
    initRipple();

    document.querySelector(".other").click();
    expect(document.querySelector(".azad-ripple")).toBeNull();
  });
});

describe("UI - initHelpTooltips", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <button data-help-tooltip aria-describedby="tip1">?</button>
      <div class="azad-field__help-popover" id="tip1" hidden>Help text</div>
    `;
  });

  it("shows popover on tooltip click", async () => {
    const { initHelpTooltips } = await import("@app-static/js/components/ui.js");
    initHelpTooltips();

    document.querySelector("[data-help-tooltip]").click();
    expect(document.getElementById("tip1").hidden).toBe(false);
  });

  it("hides popover on second click", async () => {
    const { initHelpTooltips } = await import("@app-static/js/components/ui.js");
    initHelpTooltips();

    const btn = document.querySelector("[data-help-tooltip]");
    btn.click();
    btn.click();
    expect(document.getElementById("tip1").hidden).toBe(true);
  });

  it("hides popover on outside click", async () => {
    const { initHelpTooltips } = await import("@app-static/js/components/ui.js");
    initHelpTooltips();

    document.querySelector("[data-help-tooltip]").click();
    document.body.click();
    expect(document.getElementById("tip1").hidden).toBe(true);
  });
});
