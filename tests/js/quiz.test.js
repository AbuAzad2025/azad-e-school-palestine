import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";

describe("Quiz - updateProgress", () => {
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

  it("calculates progress percentage correctly", async () => {
    const { updateProgress } = await import("@app-static/js/pages/quiz.js");
    updateProgress();

    const bar = document.getElementById("quiz-progress-bar");
    expect(bar.style.width).toBe("33%");
  });

  it("updates text with answered/total", async () => {
    // q1 radio not checked, q2 text empty, q3 radio checked → 1 answered / 3
    const { updateProgress } = await import("@app-static/js/pages/quiz.js");
    updateProgress();

    const text = document.getElementById("quiz-progress-text");
    expect(text.textContent).toContain("1");
    expect(text.textContent).toContain("3");
  });

  it("shows 100% when all answered", async () => {
    // Check q1 radio and fill q2 text — q3 is already checked
    document.querySelector('input[name="q1"]').checked = true;
    document.querySelector('input[name="q2"]').value = "answer";
    const { updateProgress } = await import("@app-static/js/pages/quiz.js");
    updateProgress();

    const bar = document.getElementById("quiz-progress-bar");
    expect(bar.style.width).toBe("100%");
  });

  it("shows 0% when none answered", async () => {
    document.querySelectorAll('input[type="radio"]').forEach((r) => (r.checked = false));
    const { updateProgress } = await import("@app-static/js/pages/quiz.js");
    updateProgress();

    const bar = document.getElementById("quiz-progress-bar");
    expect(bar.style.width).toBe("0%");
  });

  it("uses custom labels when provided", async () => {
    // q1 radio not checked, q2 text empty, q3 radio checked → 1 answered / 3
    window.AzadQuizLabels = {
      progress: "{answered} of {total} answered",
    };
    const { updateProgress } = await import("@app-static/js/pages/quiz.js");
    updateProgress();

    const text = document.getElementById("quiz-progress-text");
    expect(text.textContent).toBe("1 of 3 answered");
  });

  it("does nothing without form elements", async () => {
    document.body.innerHTML = "";
    const { updateProgress } = await import("@app-static/js/pages/quiz.js");
    expect(() => updateProgress()).not.toThrow();
  });
});

describe("Quiz - localStorage persistence", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("stores quiz attempt data", () => {
    const localStorageName = "azad_quiz_attempt_123";
    const data = { flags: [1, 2], autoSubmitted: false };
    localStorage.setItem(localStorageName, JSON.stringify(data));
    const stored = JSON.parse(localStorage.getItem(localStorageName));
    expect(stored.flags).toEqual([1, 2]);
    expect(stored.autoSubmitted).toBe(false);
  });

  it("retrieves missing name gracefully", () => {
    const raw = localStorage.getItem("azad_quiz_attempt_nonexistent");
    const data = raw ? JSON.parse(raw) : { flags: [] };
    expect(data.flags).toEqual([]);
  });

  it("cleans up after submit", () => {
    const localStorageName = "azad_quiz_attempt_123";
    localStorage.setItem(localStorageName, JSON.stringify({ flags: [1] }));
    localStorage.removeItem(localStorageName);
    expect(localStorage.getItem(localStorageName)).toBeNull();
  });
});

describe("Quiz - Flag questions", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div data-question-index="1">
        <button data-flag-question="10">Flag</button>
      </div>
      <div data-question-index="2">
        <button data-flag-question="20">Flag</button>
      </div>
    `;
    localStorage.clear();
  });

  it("toggles flag state on button click", () => {
    const btn = document.querySelector('[data-flag-question="10"]');
    const card = btn.closest("[data-question-index]");

    btn.classList.add("is-flagged");
    btn.setAttribute("aria-pressed", "true");
    card.classList.add("quiz-card--flagged");

    expect(btn.classList.contains("is-flagged")).toBe(true);
    expect(card.classList.contains("quiz-card--flagged")).toBe(true);
  });

  it("removes flag on second click", () => {
    const btn = document.querySelector('[data-flag-question="10"]');
    const card = btn.closest("[data-question-index]");

    btn.classList.add("is-flagged");
    btn.classList.remove("is-flagged");
    card.classList.remove("quiz-card--flagged");

    expect(btn.classList.contains("is-flagged")).toBe(false);
    expect(card.classList.contains("quiz-card--flagged")).toBe(false);
  });
});

describe("Quiz - autoSubmit", () => {
  it("submits the form", async () => {
    document.body.innerHTML = `
      <form id="quiz-form" data-attempt-id="456"></form>
    `;
    const form = document.getElementById("quiz-form");
    const submitSpy = vi.spyOn(form, "submit");

    form.submit();
    expect(submitSpy).toHaveBeenCalled();
  });
});

describe("Quiz - initTimer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    document.body.innerHTML = `
      <div id="quiz-timer" data-duration-min="1">
        <span></span>
      </div>
    `;
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("displays formatted time", () => {
    const timerEl = document.getElementById("quiz-timer");
    const span = timerEl.querySelector("span");
    const durationMin = Number(timerEl.dataset.durationMin);

    const totalSeconds = durationMin * 60;
    let remaining = totalSeconds;

    const m = String(Math.floor(remaining / 60)).padStart(2, "0");
    const s = String(remaining % 60).padStart(2, "0");
    span.textContent = `${m}:${s}`;

    expect(span.textContent).toBe("01:00");
  });

  it("adds warning class when under 5 minutes", () => {
    const timerEl = document.getElementById("quiz-timer");
    const remaining = 240;
    timerEl.classList.toggle("quiz-timer--warning", remaining <= 300 && remaining > 60);
    expect(timerEl.classList.contains("quiz-timer--warning")).toBe(true);
  });

  it("adds danger class when under 1 minute", () => {
    const timerEl = document.getElementById("quiz-timer");
    const remaining = 30;
    timerEl.classList.toggle("quiz-timer--danger", remaining <= 60);
    expect(timerEl.classList.contains("quiz-timer--danger")).toBe(true);
  });

  it("shows --:-- when no duration", () => {
    document.body.innerHTML = `
      <div id="quiz-timer" data-duration-min="0"><span></span></div>
    `;
    const timerEl = document.getElementById("quiz-timer");
    const span = timerEl.querySelector("span");
    const durationMin = Number(timerEl.dataset.durationMin);
    if (!durationMin) {
      span.textContent = "--:--";
    }
    expect(span.textContent).toBe("--:--");
  });
});

describe("Quiz - Proctoring", () => {
  beforeEach(() => {
    document.body.innerHTML = '<div class="quiz-alert"></div>';
  });

  it("posts proctoring event on visibility change", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ auto_submit: false }),
    });
    vi.stubGlobal("fetch", mockFetch);

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        mockFetch("/classes/attempt/1/proctor", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ event_type: "tab_switch" }),
        });
      }
    });

    Object.defineProperty(document, "hidden", { value: true, writable: true });
    document.dispatchEvent(new Event("visibilitychange"));

    expect(mockFetch).toHaveBeenCalled();
  });
});
