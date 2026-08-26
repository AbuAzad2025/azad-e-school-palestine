import { describe, it, expect, beforeEach, vi } from "vitest";

describe("Forms - initInlineValidation", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div class="azad-field">
        <input data-validate type="email" name="email" />
      </div>
      <div class="azad-field">
        <input data-validate required name="name" />
      </div>
      <div class="azad-field">
        <input data-validate type="number" name="age" min="18" max="65" />
      </div>
      <div class="azad-field">
        <input data-validate minlength="3" name="code" />
      </div>
    `;
    window.AzadFormLabels = undefined;
  });

  it("shows error for empty required field on blur", async () => {
    const { initInlineValidation } = await import("@app-static/js/components/forms.js");
    initInlineValidation();

    const input = document.querySelector('input[name="name"]');
    input.value = "";
    input.dispatchEvent(new Event("blur", { bubbles: true }));

    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error).toBeTruthy();
    expect(error.textContent).toContain("مطلوب");
  });

  it("shows error for invalid email on blur", async () => {
    const { initInlineValidation } = await import("@app-static/js/components/forms.js");
    initInlineValidation();

    const input = document.querySelector('input[name="email"]');
    input.value = "not-an-email";
    input.dispatchEvent(new Event("blur", { bubbles: true }));

    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error).toBeTruthy();
    expect(error.textContent).toContain("البريد الإلكتروني غير صالح");
  });

  it("shows error when value is below min", async () => {
    const { initInlineValidation } = await import("@app-static/js/components/forms.js");
    initInlineValidation();

    const input = document.querySelector('input[name="age"]');
    input.value = "15";
    input.dispatchEvent(new Event("blur", { bubbles: true }));

    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error).toBeTruthy();
    expect(error.textContent).toContain("18");
  });

  it("shows error when value exceeds max", async () => {
    const { initInlineValidation } = await import("@app-static/js/components/forms.js");
    initInlineValidation();

    const input = document.querySelector('input[name="age"]');
    input.value = "100";
    input.dispatchEvent(new Event("blur", { bubbles: true }));

    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error).toBeTruthy();
    expect(error.textContent).toContain("65");
  });

  it("shows error when value is shorter than minlength", async () => {
    const { initInlineValidation } = await import("@app-static/js/components/forms.js");
    initInlineValidation();

    const input = document.querySelector('input[name="code"]');
    input.value = "ab";
    input.dispatchEvent(new Event("blur", { bubbles: true }));

    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error).toBeTruthy();
  });

  it("clears error for valid input", async () => {
    const { initInlineValidation } = await import("@app-static/js/components/forms.js");
    initInlineValidation();

    const input = document.querySelector('input[name="name"]');
    input.value = "test";
    input.removeAttribute("required");
    input.dispatchEvent(new Event("blur", { bubbles: true }));

    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toBe("");
  });

  it("shows error for non-numeric value in number field", async () => {
    // jsdom normalizes number input values, so we test via attribute
    const { initInlineValidation } = await import("@app-static/js/components/forms.js");
    initInlineValidation();

    const input = document.querySelector('input[name="age"]');
    // Force the value by overriding the getter
    Object.defineProperty(input, "value", { get: () => "abc", configurable: true });
    input.dispatchEvent(new Event("blur", { bubbles: true }));

    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error).toBeTruthy();
    expect(error.textContent).toContain("رقمية");
  });

  it("uses custom labels when provided", async () => {
    window.AzadFormLabels = { required: "This field is mandatory" };
    const { initInlineValidation } = await import("@app-static/js/components/forms.js");
    initInlineValidation();

    const input = document.querySelector('input[name="name"]');
    input.value = "";
    input.dispatchEvent(new Event("blur", { bubbles: true }));

    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toBe("This field is mandatory");
  });

  it("does not validate inputs without data-validate", async () => {
    document.body.innerHTML = `
      <div class="azad-field">
        <input type="email" name="novalidate" />
      </div>
    `;
    const { initInlineValidation } = await import("@app-static/js/components/forms.js");
    initInlineValidation();

    const input = document.querySelector('input[name="novalidate"]');
    input.value = "invalid";
    input.dispatchEvent(new Event("blur", { bubbles: true }));

    const error = input.closest(".azad-field")?.querySelector(".azad-field__error");
    expect(error).toBeNull();
  });
});

describe("Forms - initFileUploads", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div class="azad-upload__zone">
        <input class="azad-upload__input" type="file" />
        <span class="azad-upload__file-name"></span>
        <img class="azad-upload__preview" hidden />
      </div>
    `;
  });

  it("adds dragover class on dragover", async () => {
    const { initFileUploads } = await import("@app-static/js/components/forms.js");
    initFileUploads();

    const zone = document.querySelector(".azad-upload__zone");
    zone.dispatchEvent(new Event("dragover", { bubbles: true }));
    expect(zone.classList.contains("azad-upload__zone--dragover")).toBe(true);
  });

  it("removes dragover class on dragleave", async () => {
    const { initFileUploads } = await import("@app-static/js/components/forms.js");
    initFileUploads();

    const zone = document.querySelector(".azad-upload__zone");
    zone.classList.add("azad-upload__zone--dragover");
    zone.dispatchEvent(new Event("dragleave", { bubbles: true }));
    expect(zone.classList.contains("azad-upload__zone--dragover")).toBe(false);
  });

  it("opens file dialog on Enter key in zone", async () => {
    const { initFileUploads } = await import("@app-static/js/components/forms.js");
    initFileUploads();

    const input = document.querySelector(".azad-upload__input");
    const clickSpy = vi.spyOn(input, "click");

    const zone = document.querySelector(".azad-upload__zone");
    zone.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
    );
    expect(clickSpy).toHaveBeenCalled();
  });

  it("opens file dialog on Space key in zone", async () => {
    const { initFileUploads } = await import("@app-static/js/components/forms.js");
    initFileUploads();

    const input = document.querySelector(".azad-upload__input");
    const clickSpy = vi.spyOn(input, "click");

    const zone = document.querySelector(".azad-upload__zone");
    zone.dispatchEvent(
      new KeyboardEvent("keydown", { key: " ", bubbles: true }),
    );
    expect(clickSpy).toHaveBeenCalled();
  });

  it("does not add dragover class for other events", async () => {
    const { initFileUploads } = await import("@app-static/js/components/forms.js");
    initFileUploads();

    const zone = document.querySelector(".azad-upload__zone");
    zone.dispatchEvent(new Event("click", { bubbles: true }));
    expect(zone.classList.contains("azad-upload__zone--dragover")).toBe(false);
  });

  it("zone contains file input", async () => {
    const zone = document.querySelector(".azad-upload__zone");
    const input = zone.querySelector(".azad-upload__input");
    expect(input).toBeTruthy();
    expect(input.type).toBe("file");
  });

  it("file name element is initially empty", () => {
    const nameEl = document.querySelector(".azad-upload__file-name");
    expect(nameEl.textContent).toBe("");
  });

  it("preview is initially hidden", () => {
    const preview = document.querySelector(".azad-upload__preview");
    expect(preview.hidden).toBe(true);
  });
});
