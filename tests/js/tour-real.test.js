import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { initTour } from "@app-static/js/components/tour.js";

describe("Tour - initTour (actual module)", () => {
  beforeEach(() => {
    localStorage.clear();
    document.cookie.split(";").forEach((c) => {
      const name = c.split("=")[0].trim();
      document.cookie = `${name}=; Max-Age=0; path=/`;
    });
    document.body.innerHTML = "";
    document.body.dataset.showTour = "";
    window.AzadTourLabels = undefined;
    // Mock scrollIntoView for jsdom
    Element.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    delete Element.prototype.scrollIntoView;
  });

  it("does nothing when no tour flag and no cookie", () => {
    document.body.dataset.showTour = "";
    initTour();
    const modal = document.getElementById("azad-tour");
    expect(modal).toBeNull();
  });

  it("does nothing when localStorage flag is set", () => {
    localStorage.setItem("azad-tour-completed", "1");
    document.body.dataset.showTour = "true";
    initTour();
    const modal = document.getElementById("azad-tour");
    expect(modal).toBeNull();
  });

  it("creates and shows modal when showTour flag is set", () => {
    document.body.dataset.showTour = "true";
    initTour();
    const modal = document.getElementById("azad-tour");
    expect(modal).toBeTruthy();
    expect(modal.hidden).toBe(false);
    expect(modal.getAttribute("role")).toBe("dialog");
    expect(modal.getAttribute("aria-modal")).toBe("true");
  });

  it("creates modal when cookie is set", () => {
    document.cookie = "azad_show_tour=1; path=/";
    initTour();
    const modal = document.getElementById("azad-tour");
    expect(modal).toBeTruthy();
    expect(modal.hidden).toBe(false);
  });

  it("renders step dots", () => {
    document.body.dataset.showTour = "true";
    initTour();
    const modal = document.getElementById("azad-tour");
    const dots = modal.querySelectorAll("[data-tour-dot]");
    expect(dots.length).toBe(4);
  });

  it("renders step title and text", () => {
    document.body.dataset.showTour = "true";
    initTour();
    const modal = document.getElementById("azad-tour");
    const titleEl = modal.querySelector("[data-tour-step-title]");
    const textEl = modal.querySelector("[data-tour-step-text]");
    expect(titleEl.textContent).toBeTruthy();
    expect(textEl.textContent).toBeTruthy();
  });

  it("navigates to next step on next button click", () => {
    document.body.dataset.showTour = "true";
    initTour();
    const modal = document.getElementById("azad-tour");
    const nextBtn = modal.querySelector("[data-tour-next]");
    const titleEl = modal.querySelector("[data-tour-step-title]");

    const firstTitle = titleEl.textContent;
    nextBtn.click();
    expect(titleEl.textContent).not.toBe(firstTitle);
  });

  it("finishes on last step click", () => {
    document.body.dataset.showTour = "true";
    initTour();
    const modal = document.getElementById("azad-tour");
    const nextBtn = modal.querySelector("[data-tour-next]");

    for (let i = 0; i < 4; i++) {
      nextBtn.click();
    }
    expect(modal.hidden).toBe(true);
  });

  it("shows finish text on last step", () => {
    document.body.dataset.showTour = "true";
    initTour();
    const modal = document.getElementById("azad-tour");
    const nextBtn = modal.querySelector("[data-tour-next]");

    for (let i = 0; i < 3; i++) {
      nextBtn.click();
    }
    expect(nextBtn.textContent).toBe("انتهاء");
  });

  it("skips tour on skip button click", () => {
    document.body.dataset.showTour = "true";
    initTour();
    const modal = document.getElementById("azad-tour");
    const skipBtn = modal.querySelector("[data-tour-skip]");

    skipBtn.click();
    expect(modal.hidden).toBe(true);
  });

  it("closes tour on close button click", () => {
    document.body.dataset.showTour = "true";
    initTour();
    const modal = document.getElementById("azad-tour");
    const closeBtn = modal.querySelector("[data-tour-close]");

    closeBtn.click();
    expect(modal.hidden).toBe(true);
  });

  it("saves to localStorage when dont-show checkbox is checked", () => {
    document.body.dataset.showTour = "true";
    initTour();
    const modal = document.getElementById("azad-tour");
    const dontShow = modal.querySelector("[data-tour-dont-show]");
    const nextBtn = modal.querySelector("[data-tour-next]");

    dontShow.checked = true;
    for (let i = 0; i < 4; i++) {
      nextBtn.click();
    }

    expect(localStorage.getItem("azad-tour-completed")).toBe("1");
  });

  it("does not save to localStorage when dont-show is unchecked", () => {
    document.body.dataset.showTour = "true";
    initTour();
    const modal = document.getElementById("azad-tour");
    const nextBtn = modal.querySelector("[data-tour-next]");

    for (let i = 0; i < 4; i++) {
      nextBtn.click();
    }

    expect(localStorage.getItem("azad-tour-completed")).toBeNull();
  });

  it("clears cookie after finish", () => {
    document.cookie = "azad_show_tour=1; path=/";
    initTour();
    const modal = document.getElementById("azad-tour");
    const skipBtn = modal.querySelector("[data-tour-skip]");

    skipBtn.click();

    expect(document.cookie).not.toContain("azad_show_tour=1");
  });

  it("removes highlight classes after finish", () => {
    document.body.dataset.showTour = "true";
    document.body.innerHTML += '<div class="azad-tour__highlight">Target</div>';
    initTour();
    const modal = document.getElementById("azad-tour");
    const skipBtn = modal.querySelector("[data-tour-skip]");

    skipBtn.click();

    expect(document.querySelector(".azad-tour__highlight")).toBeNull();
  });

  it("reuses existing modal on second init", () => {
    document.body.dataset.showTour = "true";
    initTour();
    initTour();

    const modals = document.querySelectorAll("#azad-tour");
    expect(modals.length).toBe(1);
  });

  it("activates dot for current step", () => {
    document.body.dataset.showTour = "true";
    initTour();
    const modal = document.getElementById("azad-tour");
    const dots = modal.querySelectorAll("[data-tour-dot]");

    expect(dots[0].classList.contains("azad-tour__dot--active")).toBe(true);
    expect(dots[1].classList.contains("azad-tour__dot--active")).toBe(false);
  });

  it("scrolls to target element when available", () => {
    document.body.dataset.showTour = "true";
    const navbar = document.createElement("div");
    navbar.setAttribute("data-tour-target", "navbar");
    document.body.appendChild(navbar);

    initTour();

    const modal = document.getElementById("azad-tour");
    expect(modal).toBeTruthy();
    expect(navbar.scrollIntoView).toHaveBeenCalled();
  });

  it("calls scrollIntoView with correct options", () => {
    document.body.dataset.showTour = "true";
    const navbar = document.createElement("div");
    navbar.setAttribute("data-tour-target", "navbar");
    document.body.appendChild(navbar);

    initTour();

    expect(navbar.scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "center" });
  });

  it("adds highlight class to target", () => {
    document.body.dataset.showTour = "true";
    const navbar = document.createElement("div");
    navbar.setAttribute("data-tour-target", "navbar");
    document.body.appendChild(navbar);

    initTour();

    expect(navbar.classList.contains("azad-tour__highlight")).toBe(true);
  });
});

describe("Tour - initTour with custom labels", () => {
  beforeEach(() => {
    localStorage.clear();
    document.cookie.split(";").forEach((c) => {
      const name = c.split("=")[0].trim();
      document.cookie = `${name}=; Max-Age=0; path=/`;
    });
    document.body.innerHTML = "";
    document.body.dataset.showTour = "true";
    Element.prototype.scrollIntoView = vi.fn();
  });

  afterEach(() => {
    delete Element.prototype.scrollIntoView;
  });

  it("uses custom labels for close button", () => {
    window.AzadTourLabels = { close: "Close" };
    initTour();
    const modal = document.getElementById("azad-tour");
    const closeBtn = modal.querySelector("[data-tour-close]");
    expect(closeBtn.getAttribute("aria-label")).toBe("Close");
  });

  it("uses custom labels for skip button", () => {
    window.AzadTourLabels = { skip: "Skip Tour" };
    initTour();
    const modal = document.getElementById("azad-tour");
    const skipBtn = modal.querySelector("[data-tour-skip]");
    expect(skipBtn.textContent).toBe("Skip Tour");
  });

  it("uses custom labels for next button", () => {
    window.AzadTourLabels = { next: "Next Step" };
    initTour();
    const modal = document.getElementById("azad-tour");
    const nextBtn = modal.querySelector("[data-tour-next]");
    expect(nextBtn.textContent).toBe("Next Step");
  });

  it("uses custom labels for finish button", () => {
    window.AzadTourLabels = { next: "Go", finish: "Done" };
    initTour();
    const modal = document.getElementById("azad-tour");
    const nextBtn = modal.querySelector("[data-tour-next]");

    for (let i = 0; i < 3; i++) {
      nextBtn.click();
    }
    expect(nextBtn.textContent).toBe("Done");
  });

  it("uses custom step labels", () => {
    window.AzadTourLabels = {
      steps: [
        { title: "Custom 1", text: "Custom text 1" },
        { title: "Custom 2", text: "Custom text 2" },
        { title: "Custom 3", text: "Custom text 3" },
        { title: "Custom 4", text: "Custom text 4" },
      ],
    };
    initTour();
    const modal = document.getElementById("azad-tour");
    const titleEl = modal.querySelector("[data-tour-step-title]");
    expect(titleEl.textContent).toBe("Custom 1");
  });

  it("uses custom modal aria-label", () => {
    window.AzadTourLabels = { modalLabel: "Onboarding Tour" };
    initTour();
    const modal = document.getElementById("azad-tour");
    expect(modal.getAttribute("aria-label")).toBe("Onboarding Tour");
  });
});
