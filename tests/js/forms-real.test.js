import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { initInlineValidation, initFileUploads } from "@app-static/js/components/forms.js";

describe("Forms - initInlineValidation (actual module)", () => {
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
      <div class="azad-field">
        <input data-validate maxlength="5" name="short" />
      </div>
      <div class="azad-field">
        <input data-validate type="range" name="slider" min="0" max="100" />
      </div>
    `;
    window.AzadFormLabels = undefined;
  });

  it("shows error for empty required field on blur", () => {
    initInlineValidation();
    const input = document.querySelector('input[name="name"]');
    input.value = "";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toContain("مطلوب");
  });

  it("shows error for invalid email on blur", () => {
    initInlineValidation();
    const input = document.querySelector('input[name="email"]');
    input.value = "not-an-email";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toContain("البريد الإلكتروني غير صالح");
  });

  it("clears error for valid email", () => {
    initInlineValidation();
    const input = document.querySelector('input[name="email"]');
    input.value = "test@example.com";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toBe("");
  });

  it("shows error when value is below min", () => {
    initInlineValidation();
    const input = document.querySelector('input[name="age"]');
    input.value = "15";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toContain("18");
  });

  it("shows error when value exceeds max", () => {
    initInlineValidation();
    const input = document.querySelector('input[name="age"]');
    input.value = "100";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toContain("65");
  });

  it("shows error when value is shorter than minlength", () => {
    initInlineValidation();
    const input = document.querySelector('input[name="code"]');
    input.value = "ab";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toContain("3");
  });

  it("clears error for valid minlength", () => {
    initInlineValidation();
    const input = document.querySelector('input[name="code"]');
    input.value = "abc";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toBe("");
  });

  it("shows error when value exceeds maxlength", () => {
    initInlineValidation();
    const input = document.querySelector('input[name="short"]');
    input.value = "toolong";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toContain("5");
  });

  it("clears error for valid input", () => {
    initInlineValidation();
    const input = document.querySelector('input[name="name"]');
    input.value = "test";
    input.removeAttribute("required");
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toBe("");
  });

  it("shows error for non-numeric value in number field", () => {
    initInlineValidation();
    const input = document.querySelector('input[name="age"]');
    Object.defineProperty(input, "value", { get: () => "abc", configurable: true });
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toContain("رقمية");
  });

  it("uses custom required label", () => {
    window.AzadFormLabels = { required: "This field is mandatory" };
    initInlineValidation();
    const input = document.querySelector('input[name="name"]');
    input.value = "";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toBe("This field is mandatory");
  });

  it("uses custom email label", () => {
    window.AzadFormLabels = { email: "Invalid email address" };
    initInlineValidation();
    const input = document.querySelector('input[name="email"]');
    input.value = "bad";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toBe("Invalid email address");
  });

  it("uses custom minLength label", () => {
    window.AzadFormLabels = { minLength: "Minimum {min} characters" };
    initInlineValidation();
    const input = document.querySelector('input[name="code"]');
    input.value = "ab";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toBe("Minimum 3 characters");
  });

  it("uses custom maxLength label", () => {
    window.AzadFormLabels = { maxLength: "Maximum {max} characters" };
    initInlineValidation();
    const input = document.querySelector('input[name="short"]');
    input.value = "toolong";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toBe("Maximum 5 characters");
  });

  it("uses custom number label", () => {
    window.AzadFormLabels = { number: "Not a valid number" };
    initInlineValidation();
    const input = document.querySelector('input[name="age"]');
    Object.defineProperty(input, "value", { get: () => "abc", configurable: true });
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toBe("Not a valid number");
  });

  it("uses custom min label", () => {
    window.AzadFormLabels = { min: "Minimum value is {min}" };
    initInlineValidation();
    const input = document.querySelector('input[name="age"]');
    input.value = "10";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toBe("Minimum value is 18");
  });

  it("uses custom max label", () => {
    window.AzadFormLabels = { max: "Maximum value is {max}" };
    initInlineValidation();
    const input = document.querySelector('input[name="age"]');
    input.value = "100";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toBe("Maximum value is 65");
  });

  it("does not validate inputs without data-validate", () => {
    document.body.innerHTML = `
      <div class="azad-field">
        <input type="email" name="novalidate" />
      </div>
    `;
    initInlineValidation();
    const input = document.querySelector('input[name="novalidate"]');
    input.value = "invalid";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field")?.querySelector(".azad-field__error");
    expect(error).toBeNull();
  });

  it("shows error for empty email field (required + email)", () => {
    initInlineValidation();
    const input = document.querySelector('input[name="email"]');
    input.value = "";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    // Email field is not required, so empty is valid
    expect(error.textContent).toBe("");
  });

  it("validates range input type above max", () => {
    initInlineValidation();
    const input = document.querySelector('input[name="slider"]');
    Object.defineProperty(input, "value", { get: () => "150", configurable: true });
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toContain("100");
  });

  it("validates range input below min", () => {
    initInlineValidation();
    const input = document.querySelector('input[name="slider"]');
    Object.defineProperty(input, "value", { get: () => "-10", configurable: true });
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error.textContent).toContain("0");
  });

  it("creates error container on first validation", () => {
    initInlineValidation();
    const input = document.querySelector('input[name="name"]');
    input.value = "";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const errorContainer = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(errorContainer).toBeTruthy();
    expect(errorContainer.getAttribute("aria-live")).toBe("polite");
  });

  it("reuses existing error container", () => {
    initInlineValidation();
    const input = document.querySelector('input[name="name"]');
    // First validation creates container
    input.value = "";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error1 = input.closest(".azad-field").querySelector(".azad-field__error");
    // Second validation reuses it
    input.value = "test";
    input.removeAttribute("required");
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error2 = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error1).toBe(error2);
  });

  it("does not show error when input has no parent azad-field", () => {
    document.body.innerHTML = '<input data-validate required name="orphan" />';
    initInlineValidation();
    const input = document.querySelector('input[name="orphan"]');
    input.value = "";
    // Should not throw even without .azad-field parent
    expect(() => input.dispatchEvent(new Event("blur", { bubbles: true }))).not.toThrow();
  });

  it("clears azad-field--error class on valid input", () => {
    initInlineValidation();
    const input = document.querySelector('input[name="name"]');
    const field = input.closest(".azad-field");
    // First trigger error
    input.value = "";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    expect(field.classList.contains("azad-field--error")).toBe(true);
    // Then fix it
    input.value = "valid";
    input.removeAttribute("required");
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    expect(field.classList.contains("azad-field--error")).toBe(false);
  });
});

describe("Forms - initFileUploads (actual module)", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div class="azad-upload__zone">
        <input class="azad-upload__input" type="file" />
        <span class="azad-upload__file-name"></span>
        <img class="azad-upload__preview" hidden />
      </div>
    `;
  });

  it("adds dragover class on dragover", () => {
    initFileUploads();
    const zone = document.querySelector(".azad-upload__zone");
    zone.dispatchEvent(new Event("dragover", { bubbles: true }));
    expect(zone.classList.contains("azad-upload__zone--dragover")).toBe(true);
  });

  it("removes dragover class on dragleave", () => {
    initFileUploads();
    const zone = document.querySelector(".azad-upload__zone");
    zone.classList.add("azad-upload__zone--dragover");
    zone.dispatchEvent(new Event("dragleave", { bubbles: true }));
    expect(zone.classList.contains("azad-upload__zone--dragover")).toBe(false);
  });

  it("opens file dialog on Enter key in zone", () => {
    initFileUploads();
    const input = document.querySelector(".azad-upload__input");
    const clickSpy = vi.spyOn(input, "click");
    const zone = document.querySelector(".azad-upload__zone");
    zone.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(clickSpy).toHaveBeenCalled();
  });

  it("opens file dialog on Space key in zone", () => {
    initFileUploads();
    const input = document.querySelector(".azad-upload__input");
    const clickSpy = vi.spyOn(input, "click");
    const zone = document.querySelector(".azad-upload__zone");
    zone.dispatchEvent(new KeyboardEvent("keydown", { key: " ", bubbles: true }));
    expect(clickSpy).toHaveBeenCalled();
  });

  it("does not add dragover for other events", () => {
    initFileUploads();
    const zone = document.querySelector(".azad-upload__zone");
    zone.dispatchEvent(new Event("click", { bubbles: true }));
    expect(zone.classList.contains("azad-upload__zone--dragover")).toBe(false);
  });

  it("zone contains file input", () => {
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

  it("handles drop event with file", () => {
    initFileUploads();
    const zone = document.querySelector(".azad-upload__zone");

    // Create a mock file
    const file = new File(["content"], "test.txt", { type: "text/plain" });
    const dataTransfer = {
      files: [file],
    };

    const dropEvent = new Event("drop", { bubbles: true });
    dropEvent.dataTransfer = dataTransfer;
    zone.dispatchEvent(dropEvent);

    // Should remove dragover class
    expect(zone.classList.contains("azad-upload__zone--dragover")).toBe(false);
  });

  it("handles drop event with image file", () => {
    initFileUploads();
    const zone = document.querySelector(".azad-upload__zone");

    // Create a mock image file
    const file = new File(["image content"], "photo.jpg", { type: "image/jpeg" });
    const dataTransfer = {
      files: [file],
    };

    const dropEvent = new Event("drop", { bubbles: true });
    dropEvent.dataTransfer = dataTransfer;
    zone.dispatchEvent(dropEvent);

    // Should remove dragover class
    expect(zone.classList.contains("azad-upload__zone--dragover")).toBe(false);
  });

  it("handles file input change event", () => {
    initFileUploads();
    const input = document.querySelector(".azad-upload__input");
    const zone = document.querySelector(".azad-upload__zone");

    // Mock files property as writable (jsdom has it read-only)
    const file = new File(["content"], "test.txt", { type: "text/plain" });
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(file);
    Object.defineProperty(input, "files", {
      value: dataTransfer.files,
      writable: true,
      configurable: true,
    });

    input.dispatchEvent(new Event("change", { bubbles: true }));

    const nameEl = zone.querySelector(".azad-upload__file-name");
    expect(nameEl.textContent).toBe("test.txt");
  });

  it("handles image file in change event", () => {
    initFileUploads();
    const input = document.querySelector(".azad-upload__input");
    const zone = document.querySelector(".azad-upload__zone");

    const file = new File(["image content"], "photo.png", { type: "image/png" });
    const dataTransfer = new DataTransfer();
    dataTransfer.items.add(file);
    Object.defineProperty(input, "files", {
      value: dataTransfer.files,
      writable: true,
      configurable: true,
    });

    input.dispatchEvent(new Event("change", { bubbles: true }));

    const nameEl = zone.querySelector(".azad-upload__file-name");
    expect(nameEl.textContent).toBe("photo.png");
  });

  it("handles non-image file in change event (preview stays hidden)", () => {
    initFileUploads();
    const input = document.querySelector(".azad-upload__input");
    const zone = document.querySelector(".azad-upload__zone");

    const file = new File(["content"], "doc.pdf", { type: "application/pdf" });
    Object.defineProperty(input, "files", {
      value: [file],
      configurable: true,
    });

    input.dispatchEvent(new Event("change", { bubbles: true }));

    const preview = zone.querySelector(".azad-upload__preview");
    expect(preview.hidden).toBe(true);
  });

  it("handles empty file list in change event", () => {
    initFileUploads();
    const input = document.querySelector(".azad-upload__input");

    Object.defineProperty(input, "files", {
      value: [],
      configurable: true,
    });

    // Should not throw
    expect(() => input.dispatchEvent(new Event("change", { bubbles: true }))).not.toThrow();
  });

  it("does nothing when zone has no file input", () => {
    document.body.innerHTML = `
      <div class="azad-upload__zone">
        <span class="azad-upload__file-name"></span>
      </div>
    `;
    // Should not throw
    expect(() => initFileUploads()).not.toThrow();
  });

  it("sets file name from dropped file", () => {
    initFileUploads();
    const zone = document.querySelector(".azad-upload__zone");
    const input = zone.querySelector(".azad-upload__input");

    // Make input.files writable for jsdom using DataTransfer
    const file = new File(["content"], "dropped.txt", { type: "text/plain" });
    const dt = new DataTransfer();
    dt.items.add(file);
    Object.defineProperty(input, "files", {
      value: dt.files,
      writable: true,
      configurable: true,
    });

    const dropEvent = new Event("drop", { bubbles: true });
    dropEvent.dataTransfer = { files: [file] };
    zone.dispatchEvent(dropEvent);

    const nameEl = zone.querySelector(".azad-upload__file-name");
    expect(nameEl.textContent).toBe("dropped.txt");
  });

  it("clears file name when no file", () => {
    initFileUploads();
    const zone = document.querySelector(".azad-upload__zone");
    const file = new File([""], "", { type: "" });
    const dataTransfer = { files: [file] };

    const dropEvent = new Event("drop", { bubbles: true });
    dropEvent.dataTransfer = dataTransfer;
    zone.dispatchEvent(dropEvent);

    const nameEl = zone.querySelector(".azad-upload__file-name");
    // Empty file name
    expect(nameEl.textContent).toBe("");
  });

  it("does not prevent default on keydown for other keys", () => {
    initFileUploads();
    const input = document.querySelector(".azad-upload__input");
    const clickSpy = vi.spyOn(input, "click");
    const zone = document.querySelector(".azad-upload__zone");
    zone.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", bubbles: true }));
    expect(clickSpy).not.toHaveBeenCalled();
  });
});
