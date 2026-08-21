/**
 * Form UX module — inline validation and custom file upload zone.
 */

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function getErrorContainer(input) {
  const field = input.closest(".azad-field");
  if (!field) return null;
  let error = field.querySelector(".azad-field__error");
  if (!error) {
    error = document.createElement("div");
    error.className = "azad-field__error";
    error.setAttribute("aria-live", "polite");
    field.appendChild(error);
  }
  return error;
}

function showError(input, message) {
  const container = getErrorContainer(input);
  if (!container) return;
  container.textContent = message;
  input.closest(".azad-field")?.classList.add("azad-field--error");
}

function clearError(input) {
  const container = getErrorContainer(input);
  if (!container) return;
  container.textContent = "";
  input.closest(".azad-field")?.classList.remove("azad-field--error");
}

function validateInput(input) {
  const value = input.value.trim();

  if (input.required && value === "") {
    return window.AzadFormLabels?.required || "هذا الحقل مطلوب";
  }

  if (input.type === "email" && value !== "" && !EMAIL_RE.test(value)) {
    return window.AzadFormLabels?.email || "البريد الإلكتروني غير صالح";
  }

  const minLen = input.getAttribute("minlength");
  if (minLen && value.length < Number(minLen)) {
    return (
      window.AzadFormLabels?.minLength?.replace("{min}", minLen) || `يجب ألا يقل عن ${minLen} حرف`
    );
  }

  const maxLen = input.getAttribute("maxlength");
  if (maxLen && value.length > Number(maxLen)) {
    return (
      window.AzadFormLabels?.maxLength?.replace("{max}", maxLen) || `يجب ألا يزيد عن ${maxLen} حرف`
    );
  }

  const minNum = input.getAttribute("min");
  const maxNum = input.getAttribute("max");
  if ((input.type === "number" || input.type === "range") && value !== "") {
    const num = Number(value);
    if (Number.isNaN(num)) return window.AzadFormLabels?.number || "قيمة رقمية غير صالحة";
    if (minNum && num < Number(minNum)) {
      return window.AzadFormLabels?.min?.replace("{min}", minNum) || `يجب ألا تقل عن ${minNum}`;
    }
    if (maxNum && num > Number(maxNum)) {
      return window.AzadFormLabels?.max?.replace("{max}", maxNum) || `يجب ألا تزيد عن ${maxNum}`;
    }
  }

  return "";
}

export function initInlineValidation() {
  document.addEventListener(
    "blur",
    (e) => {
      const input = e.target.closest("[data-validate]");
      if (!input) return;
      const message = validateInput(input);
      if (message) {
        showError(input, message);
      } else {
        clearError(input);
      }
    },
    true,
  );
}

function updateUploadZone(zone, file) {
  const nameEl = zone.querySelector(".azad-upload__file-name");
  const previewEl = zone.querySelector(".azad-upload__preview");
  if (nameEl) nameEl.textContent = file ? file.name : "";

  if (previewEl && file?.type.startsWith("image/")) {
    const reader = new FileReader();
    reader.onload = (ev) => {
      previewEl.src = ev.target.result;
      previewEl.hidden = false;
    };
    reader.readAsDataURL(file);
  } else if (previewEl) {
    previewEl.hidden = true;
    previewEl.src = "";
  }
}

function handleFiles(zone, files) {
  const input = zone.querySelector(".azad-upload__input");
  if (!input) return;
  if (files.length) {
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(files[0]);
    input.files = dataTransfer.files;
    updateUploadZone(zone, files[0]);
  }
}

export function initFileUploads() {
  document.querySelectorAll(".azad-upload__zone").forEach((zone) => {
    const input = zone.querySelector(".azad-upload__input");
    if (!input) return;

    zone.addEventListener("dragover", (e) => {
      e.preventDefault();
      zone.classList.add("azad-upload__zone--dragover");
    });

    zone.addEventListener("dragleave", () => {
      zone.classList.remove("azad-upload__zone--dragover");
    });

    zone.addEventListener("drop", (e) => {
      e.preventDefault();
      zone.classList.remove("azad-upload__zone--dragover");
      handleFiles(zone, e.dataTransfer.files);
    });

    zone.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        input.click();
      }
    });

    input.addEventListener("change", () => {
      handleFiles(zone, input.files);
    });
  });
}

export default {
  initInlineValidation,
  initFileUploads,
};
