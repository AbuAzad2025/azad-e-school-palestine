/**
 * Quiz attempt module.
 *
 * - Progress bar updated on any answer change.
 * - Countdown timer from quiz.duration_min; auto-submit on expiry.
 * - Flag-for-review state persisted in localStorage keyed by attempt.id.
 * - Proctoring events when enabled.
 */

const ATTEMPT_KEY = (id) => `azad_quiz_attempt_${id}`;

function getStoredData(attemptId) {
  try {
    const raw = localStorage.getItem(ATTEMPT_KEY(attemptId));
    return raw ? JSON.parse(raw) : { flags: [] };
  } catch {
    return { flags: [] };
  }
}

function setStoredData(attemptId, data) {
  try {
    localStorage.setItem(ATTEMPT_KEY(attemptId), JSON.stringify(data));
  } catch {
    // ignore storage errors
  }
}

function updateProgress() {
  const form = document.getElementById("quiz-form");
  const bar = document.getElementById("quiz-progress-bar");
  const text = document.getElementById("quiz-progress-text");
  if (!form || !bar || !text) return;

  const questions = form.querySelectorAll("[data-question-index]");
  const total = questions.length;
  let answered = 0;
  questions.forEach((card) => {
    const inputs = card.querySelectorAll("input, textarea");
    const hasAnswer = Array.from(inputs).some((input) => {
      if (input.type === "radio") return input.checked;
      return (input.value || "").trim().length > 0;
    });
    if (hasAnswer) answered += 1;
  });

  const pct = total ? Math.round((answered / total) * 100) : 0;
  bar.style.width = `${pct}%`;
  text.textContent = window.AzadQuizLabels
    ? window.AzadQuizLabels.progress
        .replace("{answered}", String(answered))
        .replace("{total}", String(total))
    : `${answered} من ${total} تمت الإجابة عليه`;
}

function initTimer() {
  const timerEl = document.getElementById("quiz-timer");
  if (!timerEl) return;
  const durationMin = Number(timerEl.dataset.durationMin) || 0;
  if (!durationMin) {
    timerEl.querySelector("span").textContent = "--:--";
    return;
  }

  const totalSeconds = durationMin * 60;
  let remaining = totalSeconds;
  const span = timerEl.querySelector("span");

  const tick = () => {
    const m = String(Math.floor(remaining / 60)).padStart(2, "0");
    const s = String(remaining % 60).padStart(2, "0");
    span.textContent = `${m}:${s}`;

    timerEl.classList.toggle("quiz-timer--warning", remaining <= 300 && remaining > 60);
    timerEl.classList.toggle("quiz-timer--danger", remaining <= 60);

    if (remaining <= 0) {
      clearInterval(interval);
      autoSubmit();
      return;
    }
    remaining -= 1;
  };

  const interval = setInterval(tick, 1000);
  tick();
}

function autoSubmit() {
  const form = document.getElementById("quiz-form");
  if (!form) return;
  const data = getStoredData(form.dataset.attemptId);
  data.autoSubmitted = true;
  setStoredData(form.dataset.attemptId, data);
  form.submit();
}

function initFlags(attemptId) {
  const stored = getStoredData(attemptId);
  document.querySelectorAll("[data-flag-question]").forEach((btn) => {
    const questionId = Number(btn.dataset.flagQuestion);
    const card = btn.closest("[data-question-index]");
    const isFlagged = stored.flags.includes(questionId);
    if (isFlagged) {
      btn.classList.add("is-flagged");
      btn.setAttribute("aria-pressed", "true");
      if (card) card.classList.add("quiz-card--flagged");
    }

    btn.addEventListener("click", () => {
      const currentlyFlagged = btn.classList.toggle("is-flagged");
      btn.setAttribute("aria-pressed", String(currentlyFlagged));
      if (card) card.classList.toggle("quiz-card--flagged", currentlyFlagged);

      const data = getStoredData(attemptId);
      if (currentlyFlagged) {
        if (!data.flags.includes(questionId)) data.flags.push(questionId);
      } else {
        data.flags = data.flags.filter((id) => id !== questionId);
      }
      setStoredData(attemptId, data);
    });
  });
}

function initSaveButton() {
  const saveBtn = document.querySelector("[data-save]");
  if (!saveBtn) return;
  saveBtn.addEventListener("click", (e) => {
    e.preventDefault();
    const form = saveBtn.closest("form");
    form.action = saveBtn.href;
    form.submit();
  });
}

function initProctoring(attemptId) {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const csrfInput = document.querySelector('input[name="csrf_token"]');
  const token = csrfToken || (csrfInput ? csrfInput.value : "");
  const proctorUrl = `/classes/attempt/${attemptId}/proctor`;

  function postProctor(eventType, extra) {
    const payload = Object.assign({ event_type: eventType }, extra || {});
    fetch(proctorUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": token },
      body: JSON.stringify(payload),
    })
      .then((r) => r.json())
      .then((data) => {
        if (data.auto_submit) {
          autoSubmit();
        }
      })
      .catch(() => {});
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) postProctor("tab_switch");
  });

  document.addEventListener("fullscreenchange", () => {
    if (!document.fullscreenElement && document.fullscreenEnabled !== undefined) {
      postProctor("fullscreen_exit");
    }
  });
}

function init() {
  const form = document.getElementById("quiz-form");
  if (!form) return;
  const attemptId = form.dataset.attemptId;

  initTimer();
  initFlags(attemptId);
  initSaveButton();

  form.addEventListener("change", updateProgress);
  form.addEventListener("input", updateProgress);
  updateProgress();

  if (document.querySelector(".quiz-alert")) {
    initProctoring(attemptId);
  }

  // Clear flags after successful submit
  form.addEventListener("submit", () => {
    try {
      localStorage.removeItem(ATTEMPT_KEY(attemptId));
    } catch {
      // ignore
    }
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}

export {
  autoSubmit,
  getStoredData,
  init,
  initFlags,
  initProctoring,
  initSaveButton,
  initTimer,
  setStoredData,
  updateProgress,
};
