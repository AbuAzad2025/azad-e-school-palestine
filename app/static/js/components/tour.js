/**
 * Onboarding tour module — first-time user guided walkthrough.
 */

const STORAGE_KEY = "azad-tour-completed";
const COOKIE_NAME = "azad_show_tour";

// نصوص الخطوات تأتي من الخادم مترجمة عبر window.AzadTourLabels.steps — والثوابت أدناه fallback فقط.
const STEPS = [
  {
    target: "[data-tour-target='navbar']",
    title: "التنقل",
    text: "من هنا تصل لكل أقسام المنصة بسرعة.",
  },
  {
    target: "[data-tour-target='search']",
    title: "البحث",
    text: "استخدم Ctrl+K للبحث في أي صفحة.",
  },
  {
    target: "[data-tour-target='dashboard-card']",
    title: "لوحتك",
    text: "هنا ملخص نشاطك اليومي والإحصائيات.",
  },
  {
    target: "[data-tour-target='profile']",
    title: "حسابك",
    text: "إعدادات الملف الشخصي، المظهر، والخروج.",
  },
];

const tourLabels = () => window.AzadTourLabels || {};
const localizedSteps = () =>
  STEPS.map((step, i) => ({ ...step, ...(tourLabels().steps?.[i] || {}) }));

function getCookie(name) {
  const match = document.cookie.match(new RegExp(`(^| )${name}=([^;]+)`));
  return match ? match[2] : null;
}

function deleteCookie(name) {
  document.cookie = `${name}=; Max-Age=0; path=/; SameSite=Lax`;
}

function shouldShowTour() {
  if (localStorage.getItem(STORAGE_KEY)) return false;
  if (document.body.dataset.showTour === "true") return true;
  return getCookie(COOKIE_NAME) === "1";
}

function createModal() {
  let modal = document.getElementById("azad-tour");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "azad-tour";
    modal.className = "azad-tour";
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-label", tourLabels().modalLabel || "جولة تعريفية");
    modal.setAttribute("hidden", "");
    modal.innerHTML = `
      <div class="azad-tour__overlay" data-tour-overlay></div>
      <div class="azad-tour__card">
        <div class="azad-tour__header">
          <h2 class="azad-tour__title" data-tour-step-title></h2>
          <button type="button" class="azad-tour__close" data-tour-close aria-label="${tourLabels().close || "إغلاق"}">×</button>
        </div>
        <p class="azad-tour__text" data-tour-step-text></p>
        <div class="azad-tour__progress" aria-hidden="true">
          ${STEPS.map((_, i) => `<span class="azad-tour__dot" data-tour-dot="${i}"></span>`).join("")}
        </div>
        <div class="azad-tour__actions">
          <button type="button" class="azad-btn-outline" data-tour-skip>تخطي</button>
          <button type="button" class="azad-btn" data-tour-next>التالي</button>
        </div>
        <label class="azad-tour__dont-show">
          <input type="checkbox" data-tour-dont-show> لا تُعرض مرة أخرى
        </label>
      </div>
    `;
    document.body.appendChild(modal);
  }
  return modal;
}

export function initTour() {
  if (!shouldShowTour()) return;
  const modal = createModal();
  modal.hidden = false;
  let current = 0;

  const labels = window.AzadTourLabels || {};
  const titleEl = modal.querySelector("[data-tour-step-title]");
  const textEl = modal.querySelector("[data-tour-step-text]");
  const nextBtn = modal.querySelector("[data-tour-next]");
  const skipBtn = modal.querySelector("[data-tour-skip]");
  const closeBtn = modal.querySelector("[data-tour-close]");
  const dontShowCheckbox = modal.querySelector("[data-tour-dont-show]");

  if (skipBtn) skipBtn.textContent = labels.skip || "تخطي";

  const renderStep = () => {
    const step = localizedSteps()[current];
    titleEl.textContent = step.title;
    textEl.textContent = step.text;
    nextBtn.textContent =
      current === STEPS.length - 1
        ? tourLabels().finish || "انتهاء"
        : tourLabels().next || "التالي";
    modal.querySelectorAll("[data-tour-dot]").forEach((dot, i) => {
      dot.classList.toggle("azad-tour__dot--active", i === current);
    });

    const target = document.querySelector(step.target);
    if (target) {
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      target.classList.add("azad-tour__highlight");
    }
  };

  const finish = () => {
    modal.hidden = true;
    if (dontShowCheckbox?.checked) {
      localStorage.setItem(STORAGE_KEY, "1");
    }
    deleteCookie(COOKIE_NAME);
    document.querySelectorAll(".azad-tour__highlight").forEach((el) => {
      el.classList.remove("azad-tour__highlight");
    });
  };

  nextBtn.addEventListener("click", () => {
    if (current < STEPS.length - 1) {
      current += 1;
      renderStep();
    } else {
      finish();
    }
  });

  skipBtn.addEventListener("click", finish);
  closeBtn.addEventListener("click", finish);

  renderStep();
}

export default { initTour };
