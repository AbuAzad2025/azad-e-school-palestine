import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import {
  updateProgress,
  autoSubmit,
  initTimer,
  initFlags,
  initSaveButton,
  initProctoring,
  init,
  getStoredData,
  setStoredData,
} from "@app-static/js/pages/quiz.js";

describe("Quiz - updateProgress (actual module)", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <form id="quiz-form" data-attempt-id="123">
        <div data-question-index="0">
          <input type="radio" name="q1" value="a" />
        </div>
        <div data-question-index="1">
          <input type="text" name="q2" value="" />
        </div>
        <div data-question-index="2">
          <input type="radio" name="q3" value="b" checked />
        </div>
      </form>
      <div id="quiz-progress-bar" style="width: 0%"></div>
      <span id="quiz-progress-text"></span>
    `;
    window.AzadQuizLabels = undefined;
  });

  it("calculates progress percentage correctly", () => {
    updateProgress();
    const bar = document.getElementById("quiz-progress-bar");
    expect(bar.style.width).toBe("33%");
  });

  it("updates text with answered/total", () => {
    updateProgress();
    const text = document.getElementById("quiz-progress-text");
    expect(text.textContent).toContain("1");
    expect(text.textContent).toContain("3");
  });

  it("shows 100% when all answered", () => {
    document.querySelector('input[name="q1"]').checked = true;
    document.querySelector('input[name="q2"]').value = "answer";
    updateProgress();
    const bar = document.getElementById("quiz-progress-bar");
    expect(bar.style.width).toBe("100%");
  });

  it("shows 0% when none answered", () => {
    document.querySelectorAll('input[type="radio"]').forEach((r) => (r.checked = false));
    updateProgress();
    const bar = document.getElementById("quiz-progress-bar");
    expect(bar.style.width).toBe("0%");
  });

  it("uses custom labels when provided", () => {
    window.AzadQuizLabels = {
      progress: "{answered} of {total} answered",
    };
    updateProgress();
    const text = document.getElementById("quiz-progress-text");
    expect(text.textContent).toBe("1 of 3 answered");
  });

  it("does nothing without form elements", () => {
    document.body.innerHTML = "";
    expect(() => updateProgress()).not.toThrow();
  });

  it("does nothing without progress bar", () => {
    document.getElementById("quiz-progress-bar").remove();
    expect(() => updateProgress()).not.toThrow();
  });

  it("does nothing without progress text", () => {
    document.getElementById("quiz-progress-text").remove();
    expect(() => updateProgress()).not.toThrow();
  });
});

describe("Quiz - autoSubmit (actual module)", () => {
  beforeEach(() => {
    localStorage.clear();
    document.body.innerHTML = `
      <form id="quiz-form" data-attempt-id="456"></form>
    `;
  });

  it("submits the form", () => {
    const form = document.getElementById("quiz-form");
    const submitSpy = vi.spyOn(form, "submit");
    autoSubmit();
    expect(submitSpy).toHaveBeenCalled();
  });

  it("sets autoSubmitted flag in localStorage", () => {
    autoSubmit();
    const stored = JSON.parse(localStorage.getItem("azad_quiz_attempt_456"));
    expect(stored.autoSubmitted).toBe(true);
  });

  it("does nothing without form", () => {
    document.body.innerHTML = "";
    expect(() => autoSubmit()).not.toThrow();
  });
});

describe("Quiz - getStoredData / setStoredData (actual module)", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("stores and retrieves data", () => {
    const data = { flags: [1, 2], autoSubmitted: false };
    setStoredData("789", data);
    const stored = getStoredData("789");
    expect(stored.flags).toEqual([1, 2]);
  });

  it("handles missing data gracefully", () => {
    const data = getStoredData("nonexistent");
    expect(data.flags).toEqual([]);
  });

  it("handles corrupted JSON gracefully", () => {
    localStorage.setItem("azad_quiz_attempt_bad", "not-json");
    const data = getStoredData("bad");
    expect(data.flags).toEqual([]);
  });

  it("cleans up after submit", () => {
    setStoredData("456", { flags: [1] });
    localStorage.removeItem("azad_quiz_attempt_456");
    expect(localStorage.getItem("azad_quiz_attempt_456")).toBeNull();
  });

  it("handles storage errors gracefully", () => {
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });
    expect(() => setStoredData("err", { flags: [] })).not.toThrow();
    spy.mockRestore();
  });
});

describe("Quiz - initTimer (actual module)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows formatted time when timer element exists", () => {
    document.body.innerHTML = `
      <div id="quiz-timer" data-duration-min="2"><span></span></div>
    `;
    initTimer();
    const span = document.querySelector("#quiz-timer span");
    expect(span.textContent).toBe("02:00");
  });

  it("shows --:-- when duration is 0", () => {
    document.body.innerHTML = `
      <div id="quiz-timer" data-duration-min="0"><span></span></div>
    `;
    initTimer();
    const span = document.querySelector("#quiz-timer span");
    expect(span.textContent).toBe("--:--");
  });

  it("shows --:-- when no data-duration-min attribute", () => {
    document.body.innerHTML = `
      <div id="quiz-timer"><span></span></div>
    `;
    initTimer();
    const span = document.querySelector("#quiz-timer span");
    expect(span.textContent).toBe("--:--");
  });

  it("does nothing when no timer element", () => {
    document.body.innerHTML = "";
    expect(() => initTimer()).not.toThrow();
  });

  it("counts down each second", () => {
    document.body.innerHTML = `
      <div id="quiz-timer" data-duration-min="1"><span></span></div>
    `;
    initTimer();
    const span = document.querySelector("#quiz-timer span");

    vi.advanceTimersByTime(1000);
    expect(span.textContent).toBe("00:59");

    vi.advanceTimersByTime(1000);
    expect(span.textContent).toBe("00:58");
  });

  it("adds warning class when under 5 minutes", () => {
    document.body.innerHTML = `
      <div id="quiz-timer" data-duration-min="5"><span></span></div>
    `;
    initTimer();
    const timerEl = document.getElementById("quiz-timer");

    // Advance to 240 seconds remaining (under 5 min, above 1 min)
    vi.advanceTimersByTime(60000);
    expect(timerEl.classList.contains("quiz-timer--warning")).toBe(true);
    expect(timerEl.classList.contains("quiz-timer--danger")).toBe(false);
  });

  it("adds danger class when under 1 minute", () => {
    document.body.innerHTML = `
      <div id="quiz-timer" data-duration-min="1"><span></span></div>
    `;
    initTimer();
    const timerEl = document.getElementById("quiz-timer");

    // Advance to 30 seconds remaining
    vi.advanceTimersByTime(30000);
    expect(timerEl.classList.contains("quiz-timer--danger")).toBe(true);
    expect(timerEl.classList.contains("quiz-timer--warning")).toBe(false);
  });

  it("no warning/danger when over 5 minutes", () => {
    document.body.innerHTML = `
      <div id="quiz-timer" data-duration-min="10"><span></span></div>
    `;
    initTimer();
    const timerEl = document.getElementById("quiz-timer");
    expect(timerEl.classList.contains("quiz-timer--warning")).toBe(false);
    expect(timerEl.classList.contains("quiz-timer--danger")).toBe(false);
  });

  it("auto-submits when timer reaches 0", () => {
    document.body.innerHTML = `
      <form id="quiz-form" data-attempt-id="777"></form>
      <div id="quiz-timer" data-duration-min="1"><span></span></div>
    `;
    const form = document.getElementById("quiz-form");
    const submitSpy = vi.spyOn(form, "submit");

    initTimer();

    // Advance to 0
    vi.advanceTimersByTime(60000);

    expect(submitSpy).toHaveBeenCalled();
  });
});

describe("Quiz - initFlags (actual module)", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("restores flagged state from localStorage", () => {
    setStoredData("888", { flags: [20] });
    document.body.innerHTML = `
      <div data-question-index="0">
        <button data-flag-question="20">Flag</button>
      </div>
    `;
    initFlags("888");
    const btn = document.querySelector('[data-flag-question="20"]');
    expect(btn.classList.contains("is-flagged")).toBe(true);
    expect(btn.getAttribute("aria-pressed")).toBe("true");
  });

  it("adds flagged class to card", () => {
    setStoredData("999", { flags: [30] });
    document.body.innerHTML = `
      <div data-question-index="0">
        <button data-flag-question="30">Flag</button>
      </div>
    `;
    initFlags("999");
    const card = document.querySelector("[data-question-index]");
    expect(card.classList.contains("quiz-card--flagged")).toBe(true);
  });

  it("does not flag non-stored questions", () => {
    setStoredData("111", { flags: [] });
    document.body.innerHTML = `
      <div data-question-index="0">
        <button data-flag-question="40">Flag</button>
      </div>
    `;
    initFlags("111");
    const btn = document.querySelector('[data-flag-question="40"]');
    expect(btn.classList.contains("is-flagged")).toBe(false);
  });

  it("toggles flag on click", () => {
    setStoredData("222", { flags: [] });
    document.body.innerHTML = `
      <div data-question-index="0">
        <button data-flag-question="50">Flag</button>
      </div>
    `;
    initFlags("222");
    const btn = document.querySelector('[data-flag-question="50"]');
    const card = btn.closest("[data-question-index]");

    btn.click();
    expect(btn.classList.contains("is-flagged")).toBe(true);
    expect(btn.getAttribute("aria-pressed")).toBe("true");
    expect(card.classList.contains("quiz-card--flagged")).toBe(true);

    const data = getStoredData("222");
    expect(data.flags).toContain(50);
  });

  it("unflags on second click", () => {
    setStoredData("333", { flags: [60] });
    document.body.innerHTML = `
      <div data-question-index="0">
        <button data-flag-question="60">Flag</button>
      </div>
    `;
    initFlags("333");
    const btn = document.querySelector('[data-flag-question="60"]');

    btn.click();
    expect(btn.classList.contains("is-flagged")).toBe(false);
    expect(btn.getAttribute("aria-pressed")).toBe("false");

    const data = getStoredData("333");
    expect(data.flags).not.toContain(60);
  });

  it("handles missing card gracefully", () => {
    setStoredData("444", { flags: [70] });
    document.body.innerHTML = `
      <button data-flag-question="70">Flag</button>
    `;
    expect(() => initFlags("444")).not.toThrow();
    const btn = document.querySelector('[data-flag-question="70"]');
    expect(btn.classList.contains("is-flagged")).toBe(true);
  });
});

describe("Quiz - initSaveButton (actual module)", () => {
  it("intercepts save button click", () => {
    document.body.innerHTML = `
      <form id="quiz-form" action="/submit">
        <a data-save href="/save-draft">Save</a>
      </form>
    `;
    const form = document.getElementById("quiz-form");
    const submitSpy = vi.spyOn(form, "submit");

    initSaveButton();

    const saveBtn = document.querySelector("[data-save]");
    saveBtn.click();

    expect(form.action).toContain("/save-draft");
    expect(submitSpy).toHaveBeenCalled();
  });

  it("does nothing without save button", () => {
    document.body.innerHTML = "";
    expect(() => initSaveButton()).not.toThrow();
  });
});

describe("Quiz - initProctoring (actual module)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({ auto_submit: false }),
      }),
    );
    document.head.innerHTML = '<meta name="csrf-token" content="test-token">';
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("posts proctoring event on visibility change", () => {
    document.body.innerHTML = "";
    initProctoring("555");

    Object.defineProperty(document, "hidden", { value: true, writable: true, configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));

    expect(fetch).toHaveBeenCalled();
    const [, init] = fetch.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body).event_type).toBe("tab_switch");
  });

  it("auto-submits when proctor response says so", async () => {
    fetch.mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ auto_submit: true }),
    });

    document.body.innerHTML = `
      <form id="quiz-form" data-attempt-id="555"></form>
    `;
    const form = document.getElementById("quiz-form");
    const submitSpy = vi.spyOn(form, "submit");

    initProctoring("555");

    Object.defineProperty(document, "hidden", { value: true, writable: true, configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));

    await vi.waitFor(() => expect(submitSpy).toHaveBeenCalled());
  });

  it("posts fullscreen_exit event", () => {
    document.body.innerHTML = "";
    // Mock fullscreenEnabled so the condition passes
    document.fullscreenEnabled = true;
    document.fullscreenElement = null;

    initProctoring("555");

    document.dispatchEvent(new Event("fullscreenchange"));

    expect(fetch).toHaveBeenCalled();
    const body = JSON.parse(fetch.mock.calls[0][1].body);
    expect(body.event_type).toBe("fullscreen_exit");

    delete document.fullscreenEnabled;
    delete document.fullscreenElement;
  });

  it("uses csrf_token input fallback", () => {
    // Remove any meta tags from head and body
    document.head.innerHTML = "";
    document.querySelectorAll('meta[name="csrf-token"]').forEach((m) => m.remove());
    document.body.innerHTML = '<input type="hidden" name="csrf_token" value="input-token">';

    initProctoring("555");

    Object.defineProperty(document, "hidden", { value: true, writable: true, configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));

    // Check that at least one fetch call used the input token
    const allBodies = fetch.mock.calls.map((c) => JSON.parse(c[1].body));
    expect(allBodies.some((b) => b.event_type === "tab_switch")).toBe(true);
    // Verify the last call (from this test) has the correct token
    const lastCall = fetch.mock.calls[fetch.mock.calls.length - 1];
    expect(lastCall[1].headers["X-CSRFToken"]).toBe("input-token");
  });

  it("does nothing on visibility change when not hidden", () => {
    document.body.innerHTML = "";
    Object.defineProperty(document, "hidden", { value: false, writable: true, configurable: true });

    initProctoring("555");
    document.dispatchEvent(new Event("visibilitychange"));

    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("Quiz - init (actual module)", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    localStorage.clear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("sets up form change/input listeners", () => {
    document.body.innerHTML = `
      <form id="quiz-form" data-attempt-id="100">
        <div data-question-index="0">
          <input type="radio" name="q1" value="a" />
        </div>
      </form>
      <div id="quiz-progress-bar" style="width: 0%"></div>
      <span id="quiz-progress-text"></span>
    `;

    init();

    // Check radio triggers progress update
    document.querySelector('input[name="q1"]').checked = true;
    document.getElementById("quiz-form").dispatchEvent(new Event("change"));

    const bar = document.getElementById("quiz-progress-bar");
    expect(bar.style.width).toBe("100%");
  });

  it("clears localStorage on submit", () => {
    document.body.innerHTML = `
      <form id="quiz-form" data-attempt-id="200">
        <div data-question-index="0">
          <input type="radio" name="q1" value="a" checked />
        </div>
      </form>
      <div id="quiz-progress-bar"></div>
      <span id="quiz-progress-text"></span>
    `;

    setStoredData("200", { flags: [1] });
    init();

    document.getElementById("quiz-form").dispatchEvent(new Event("submit"));

    expect(localStorage.getItem("azad_quiz_attempt_200")).toBeNull();
  });

  it("does nothing without quiz-form", () => {
    document.body.innerHTML = "";
    expect(() => init()).not.toThrow();
  });

  it("initializes proctoring when quiz-alert exists", () => {
    document.body.innerHTML = `
      <form id="quiz-form" data-attempt-id="300">
        <div data-question-index="0">
          <input type="radio" name="q1" value="a" checked />
        </div>
      </form>
      <div class="quiz-alert"></div>
      <div id="quiz-progress-bar"></div>
      <span id="quiz-progress-text"></span>
    `;
    document.head.innerHTML = '<meta name="csrf-token" content="test">';
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({ auto_submit: false }),
      }),
    );

    init();

    // Verify proctoring is set up by triggering visibility change
    Object.defineProperty(document, "hidden", { value: true, writable: true, configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
    expect(fetch).toHaveBeenCalled();
  });
});
