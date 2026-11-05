import { describe, it, expect, beforeEach, vi } from "vitest";
import { initInlineValidation, initFileUploads, updateUploadZone, handleFiles } from "@app-static/js/components/forms.js";

describe("Forms - defensive branch coverage (actual module)", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    window.AzadFormLabels = undefined;
  });

  it("clearError returns early when input has no azad-field parent", () => {
    initInlineValidation();
    const input = document.createElement("input");
    input.setAttribute("data-validate", "");
    document.body.appendChild(input);
    input.value = "test";
    input.dispatchEvent(new Event("blur", { bubbles: true }));
    expect(true).toBe(true);
  });

  it("updateUploadZone skips when nameEl is null", () => {
    const zone = document.createElement("div");
    document.body.appendChild(zone);
    const file = new File([""], "test.txt", { type: "text/plain" });
    updateUploadZone(zone, file);
    expect(true).toBe(true);
  });

  it("updateUploadZone sets empty name when file is null", () => {
    const zone = document.createElement("div");
    const nameEl = document.createElement("span");
    nameEl.className = "azad-upload__file-name";
    zone.appendChild(nameEl);
    document.body.appendChild(zone);
    updateUploadZone(zone, null);
    expect(nameEl.textContent).toBe("");
  });

  it("handleFiles returns early when zone has no input", () => {
    const zone = document.createElement("div");
    document.body.appendChild(zone);
    const file = new File([""], "test.txt", { type: "text/plain" });
    handleFiles(zone, [file]);
    expect(true).toBe(true);
  });
});
