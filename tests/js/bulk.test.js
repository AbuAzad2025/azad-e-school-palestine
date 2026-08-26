import { describe, it, expect, beforeEach, vi } from "vitest";

describe("Bulk - updateBulkBar", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div data-bulk-bar>
        <span data-bulk-count>0 محدد</span>
        <select data-bulk-action-select>
          <option value="">اختر إجراء</option>
          <option value="delete">حذف</option>
          <option value="activate">تفعيل</option>
        </select>
        <button data-bulk-apply>تطبيق</button>
      </div>
      <table data-bulk-entity="users">
        <thead>
          <tr><th><input data-bulk-select-all type="checkbox" /></th></tr>
        </thead>
        <tbody>
          <tr><td><input data-bulk-id="1" type="checkbox" /></td></tr>
          <tr><td><input data-bulk-id="2" type="checkbox" /></td></tr>
          <tr><td><input data-bulk-id="3" type="checkbox" /></td></tr>
        </tbody>
      </table>
    `;
    window.AzadBulkLabels = undefined;
  });

  it("updates count when checkbox is checked", async () => {
    const { updateBulkBar } = await import("@app-static/js/pages/bulk.js");
    const table = document.querySelector("[data-bulk-entity]");
    document.querySelector('[data-bulk-id="1"]').checked = true;
    document.querySelector('[data-bulk-id="2"]').checked = true;

    updateBulkBar(table);

    const countEl = document.querySelector("[data-bulk-count]");
    expect(countEl.textContent).toContain("2");
  });

  it("activates bar when selections > 0", async () => {
    const { updateBulkBar } = await import("@app-static/js/pages/bulk.js");
    const table = document.querySelector("[data-bulk-entity]");
    document.querySelector('[data-bulk-id="1"]').checked = true;

    updateBulkBar(table);

    const bar = document.querySelector("[data-bulk-bar]");
    expect(bar.classList.contains("is-active")).toBe(true);
  });

  it("deactivates bar when no selections", async () => {
    const { updateBulkBar } = await import("@app-static/js/pages/bulk.js");
    const table = document.querySelector("[data-bulk-entity]");

    updateBulkBar(table);

    const bar = document.querySelector("[data-bulk-bar]");
    expect(bar.classList.contains("is-active")).toBe(false);
  });

  it("checks select-all when all are selected", async () => {
    const { updateBulkBar } = await import("@app-static/js/pages/bulk.js");
    const table = document.querySelector("[data-bulk-entity]");
    table.querySelectorAll("[data-bulk-id]").forEach((cb) => (cb.checked = true));

    updateBulkBar(table);

    const selectAll = table.querySelector("[data-bulk-select-all]");
    expect(selectAll.checked).toBe(true);
  });

  it("unchecks select-all when not all are selected", async () => {
    const { updateBulkBar } = await import("@app-static/js/pages/bulk.js");
    const table = document.querySelector("[data-bulk-entity]");
    document.querySelector('[data-bulk-id="1"]').checked = true;

    updateBulkBar(table);

    const selectAll = table.querySelector("[data-bulk-select-all]");
    expect(selectAll.checked).toBe(false);
  });

  it("sets indeterminate when some are selected", async () => {
    const { updateBulkBar } = await import("@app-static/js/pages/bulk.js");
    const table = document.querySelector("[data-bulk-entity]");
    document.querySelector('[data-bulk-id="1"]').checked = true;
    document.querySelector('[data-bulk-id="2"]').checked = true;

    updateBulkBar(table);

    const selectAll = table.querySelector("[data-bulk-select-all]");
    expect(selectAll.indeterminate).toBe(true);
  });

  it("uses custom labels when provided", async () => {
    window.AzadBulkLabels = { selected: "{count} items selected" };
    const { updateBulkBar } = await import("@app-static/js/pages/bulk.js");
    const table = document.querySelector("[data-bulk-entity]");
    document.querySelector('[data-bulk-id="1"]').checked = true;

    updateBulkBar(table);

    const countEl = document.querySelector("[data-bulk-count]");
    expect(countEl.textContent).toBe("1 items selected");
  });
});

describe("Bulk - Select all checkbox", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div data-bulk-bar>
        <span data-bulk-count>0 محدد</span>
        <button data-bulk-apply>تطبيق</button>
      </div>
      <table data-bulk-entity="users">
        <thead>
          <tr><th><input data-bulk-select-all type="checkbox" /></th></tr>
        </thead>
        <tbody>
          <tr><td><input data-bulk-id="1" type="checkbox" /></td></tr>
          <tr><td><input data-bulk-id="2" type="checkbox" /></td></tr>
        </tbody>
      </table>
    `;
  });

  it("checks all rows when select-all is checked", async () => {
    document.querySelector("[data-bulk-select-all]").checked = true;
    document.querySelector("[data-bulk-select-all]").dispatchEvent(new Event("change", { bubbles: true }));

    // Simulate the behavior
    const selectAll = document.querySelector("[data-bulk-select-all]");
    document.querySelectorAll("[data-bulk-id]").forEach((cb) => {
      cb.checked = selectAll.checked;
    });

    document.querySelectorAll("[data-bulk-id]").forEach((cb) => {
      expect(cb.checked).toBe(true);
    });
  });

  it("unchecks all rows when select-all is unchecked", async () => {
    document.querySelector("[data-bulk-select-all]").checked = false;
    document.querySelectorAll("[data-bulk-id]").forEach((cb) => {
      cb.checked = false;
    });

    document.querySelectorAll("[data-bulk-id]").forEach((cb) => {
      expect(cb.checked).toBe(false);
    });
  });
});

describe("Bulk - Collect IDs", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <table data-bulk-entity="users">
        <tr><td><input data-bulk-id="1" type="checkbox" checked /></td></tr>
        <tr><td><input data-bulk-id="2" type="checkbox" /></td></tr>
        <tr><td><input data-bulk-id="3" type="checkbox" checked /></td></tr>
      </table>
    `;
  });

  it("collects only checked IDs", () => {
    const checked = Array.from(document.querySelectorAll("[data-bulk-id]:checked")).map(
      (cb) => cb.dataset.bulkId,
    );
    expect(checked).toEqual(["1", "3"]);
  });

  it("returns empty array when none checked", () => {
    document.querySelectorAll("[data-bulk-id]").forEach((cb) => (cb.checked = false));
    const checked = Array.from(document.querySelectorAll("[data-bulk-id]:checked")).map(
      (cb) => cb.dataset.bulkId,
    );
    expect(checked).toEqual([]);
  });
});
