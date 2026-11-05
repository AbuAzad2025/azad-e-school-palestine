import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { initInlineValidation, initFileUploads, initFormDoubleSubmitPrevention, initForms } from "@app-static/js/components/forms.js";

describe("Forms - initFormDoubleSubmitPrevention (actual module)", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <form id="test-form">
        <button type="submit" id="submit-btn">Submit</button>
        <input type="submit" id="submit-input" value="Submit" />
      </form>
      <form id="no-double-form" data-no-double-submit="true">
        <button type="submit" id="no-double-btn">Submit</button>
      </form>
      <form id="allow-double-form">
        <button type="submit" id="allow-double-btn" data-allow-double-submit="true">Submit</button>
      </form>
    `;
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("disables submit buttons after form submission", () => {
    initFormDoubleSubmitPrevention();
    const form = document.querySelector("#test-form");
    const btn = document.querySelector("#submit-btn");
    const input = document.querySelector("#submit-input");

    form.dispatchEvent(new Event("submit", { bubbles: true }));
    vi.runAllTimers();

    expect(btn.disabled).toBe(true);
    expect(input.disabled).toBe(true);
  });

  it("does not disable buttons for noDoubleSubmit forms", () => {
    initFormDoubleSubmitPrevention();
    const form = document.querySelector("#no-double-form");
    const btn = document.querySelector("#no-double-btn");

    form.dispatchEvent(new Event("submit", { bubbles: true }));
    vi.runAllTimers();

    expect(btn.disabled).toBe(false);
  });

  it("does not disable buttons marked allowDoubleSubmit", () => {
    initFormDoubleSubmitPrevention();
    const form = document.querySelector("#allow-double-form");
    const btn = document.querySelector("#allow-double-btn");

    form.dispatchEvent(new Event("submit", { bubbles: true }));
    vi.runAllTimers();

    expect(btn.disabled).toBe(false);
  });

  it("ignores non-form submit events", () => {
    initFormDoubleSubmitPrevention();
    const div = document.createElement("div");
    document.body.appendChild(div);
    // Should not throw
    div.dispatchEvent(new Event("submit", { bubbles: true }));
  });
});

describe("Forms - initForms (actual module)", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div class="azad-field">
        <input data-validate type="email" name="email" />
      </div>
      <div class="azad-upload__zone">
        <input class="azad-upload__input" type="file" />
      </div>
      <form id="test-form">
        <button type="submit">Submit</button>
      </form>
    `;
  });

  it("calls all init functions", () => {
    initForms();
    // Verify inline validation works
    const input = document.querySelector('input[name="email"]');
    input.value = "bad";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    const error = input.closest(".azad-field").querySelector(".azad-field__error");
    expect(error).not.toBeNull();
  });
});
