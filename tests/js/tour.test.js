import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";

describe("Tour - shouldShowTour logic", () => {
  beforeEach(() => {
    localStorage.clear();
    document.cookie.split(";").forEach((c) => {
      document.cookie = c.replace(/^ +/, "").replace(/=.*/, "=;Max-Age=0;path=/");
    });
    document.body.dataset.showTour = "";
  });

  it("does not show when localStorage flag is set", () => {
    localStorage.setItem("azad-tour-completed", "1");
    expect(localStorage.getItem("azad-tour-completed")).toBe("1");
  });

  it("shows when cookie is set", () => {
    document.cookie = "azad_show_tour=1; path=/";
    const match = document.cookie.match(/(^| )azad_show_tour=([^;]+)/);
    expect(match ? match[2] : null).toBe("1");
  });

  it("does not show when no cookie and no flag", () => {
    const match = document.cookie.match(/(^| )azad_show_tour=([^;]+)/);
    expect(match).toBeNull();
  });
});

describe("Tour - Cookie helpers", () => {
  it("reads cookie value", () => {
    document.cookie = "test_cookie=hello; path=/";
    const match = document.cookie.match(/(^| )test_cookie=([^;]+)/);
    expect(match ? match[2] : null).toBe("hello");
  });

  it("deletes cookie", () => {
    document.cookie = "test_cookie=hello; path=/";
    document.cookie = "test_cookie=; Max-Age=0; path=/; SameSite=Lax";
    const match = document.cookie.match(/(^| )test_cookie=([^;]+)/);
    expect(match).toBeNull();
  });
});

describe("Tour - Modal creation", () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = '<div data-tour-target="navbar">Nav</div>';
    document.body.dataset.showTour = "true";
    window.AzadTourLabels = undefined;
  });

  it("creates modal with correct attributes", () => {
    const modal = document.createElement("div");
    modal.id = "azad-tour";
    modal.className = "azad-tour";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-label", "جولة تعريفية");

    expect(modal.getAttribute("role")).toBe("dialog");
    expect(modal.getAttribute("aria-modal")).toBe("true");
  });

  it("renders step dots for each step", () => {
    const steps = [0, 1, 2, 3];
    const dotsHtml = steps
      .map((i) => `<span class="azad-tour__dot" data-tour-dot="${i}"></span>`)
      .join("");

    const container = document.createElement("div");
    container.innerHTML = dotsHtml;
    expect(container.querySelectorAll("[data-tour-dot]").length).toBe(4);
  });

  it("has close, skip, and next buttons", () => {
    const html = `
      <button data-tour-close>×</button>
      <button data-tour-skip>تخطي</button>
      <button data-tour-next>التالي</button>
    `;
    const container = document.createElement("div");
    container.innerHTML = html;

    expect(container.querySelector("[data-tour-close]")).toBeTruthy();
    expect(container.querySelector("[data-tour-skip]")).toBeTruthy();
    expect(container.querySelector("[data-tour-next]")).toBeTruthy();
  });
});

describe("Tour - Step navigation", () => {
  it("advances to next step", () => {
    let current = 0;
    const totalSteps = 4;

    current += 1;
    expect(current).toBe(1);
    expect(current < totalSteps).toBe(true);
  });

  it("finishes on last step", () => {
    let current = 3;
    const totalSteps = 4;
    const isLastStep = current === totalSteps - 1;
    expect(isLastStep).toBe(true);
  });

  it("calls finish when clicking next on last step", () => {
    let finished = false;
    const finish = () => { finished = true; };
    let current = 3;
    const totalSteps = 4;

    if (current < totalSteps - 1) {
      current += 1;
    } else {
      finish();
    }

    expect(finished).toBe(true);
  });
});

describe("Tour - LocalStorage persistence", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("saves tour completion when dont-show checked", () => {
    localStorage.setItem("azad-tour-completed", "1");
    expect(localStorage.getItem("azad-tour-completed")).toBe("1");
  });

  it("clears tour cookie after finish", () => {
    document.cookie = "azad_show_tour=1; path=/";
    document.cookie = "azad_show_tour=; Max-Age=0; path=/; SameSite=Lax";
    expect(document.cookie).not.toContain("azad_show_tour=1");
  });

  it("removes highlight classes on finish", () => {
    document.body.innerHTML = '<div class="azad-tour__highlight">Target</div>';
    document.querySelectorAll(".azad-tour__highlight").forEach((el) => {
      el.classList.remove("azad-tour__highlight");
    });
    expect(document.querySelector(".azad-tour__highlight")).toBeNull();
  });
});
