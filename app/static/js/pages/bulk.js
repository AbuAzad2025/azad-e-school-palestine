/**
 * Bulk actions for unified tables.
 *
 * - Select all / per-row checkboxes update the bulk action bar.
 * - Apply sends a POST to /admin/bulk-action with {entity, action, ids}.
 * - Loading state prevents double-submits.
 */

const BULK_ENDPOINT = "/admin/bulk-action";

function getTable(root) {
  return root.closest("[data-bulk-entity]");
}

function updateBulkBar(table) {
  const bar = table?.previousElementSibling;
  if (!bar?.matches("[data-bulk-bar]")) return;

  const checked = table.querySelectorAll("[data-bulk-id]:checked");
  const count = checked.length;
  const countEl = bar.querySelector("[data-bulk-count]");
  if (countEl) {
    countEl.textContent = window.AzadBulkLabels
      ? window.AzadBulkLabels.selected.replace("{count}", String(count))
      : `${count} محدد`;
  }
  bar.classList.toggle("is-active", count > 0);

  const selectAll = table.querySelector("[data-bulk-select-all]");
  if (selectAll) {
    const total = table.querySelectorAll("[data-bulk-id]").length;
    selectAll.checked = count > 0 && count === total;
    selectAll.indeterminate = count > 0 && count < total;
  }
}

function showError(message) {
  if (window.AzadToast) {
    window.AzadToast.show(message, "error");
  } else {
    alert(message);
  }
}

async function applyBulk(table) {
  const bar = table.previousElementSibling;
  if (!bar?.matches("[data-bulk-bar]")) return;

  const select = bar.querySelector("[data-bulk-action-select]");
  const action = select?.value;
  if (!action) return;

  const checked = Array.from(table.querySelectorAll("[data-bulk-id]:checked")).map(
    (cb) => cb.dataset.bulkId,
  );
  if (!checked.length) return;

  const selectedOption = select.querySelector(`option[value="${action}"]`);
  const confirmMessage = selectedOption?.dataset.confirm;
  if (confirmMessage && !confirm(confirmMessage)) return;

  const btn = bar.querySelector("[data-bulk-apply]");
  if (btn) {
    btn.disabled = true;
    btn.classList.add("btn-loading");
  }

  const entity = table.dataset.bulkEntity;
  try {
    const response = await fetch(BULK_ENDPOINT, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "X-CSRFToken": document.querySelector('input[name="csrf_token"]')?.value || "",
      },
      body: JSON.stringify({ entity, action, ids: checked }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const result = await response.json();
    if (result.success) {
      window.location.reload();
      return; // reload will abort further execution
    } else {
      showError(result.message || window.AzadBulkLabels?.actionFailed || "فشل تنفيذ الإجراء");
    }
  } catch {
    showError(window.AzadBulkLabels?.error || "حدث خطأ أثناء تنفيذ الإجراء الجماعي");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.classList.remove("btn-loading");
    }
  }
}

function init() {
  document.addEventListener("change", (e) => {
    const target = e.target;
    if (target.matches("[data-bulk-select-all]")) {
      const table = getTable(target);
      if (!table) return;
      table.querySelectorAll("[data-bulk-id]").forEach((cb) => {
        cb.checked = target.checked;
      });
      updateBulkBar(table);
      return;
    }

    if (target.matches("[data-bulk-id]")) {
      updateBulkBar(getTable(target));
    }
  });

  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-bulk-apply]");
    if (!btn) return;
    const table = btn.closest("[data-bulk-bar]")?.nextElementSibling;
    if (!table?.matches("[data-bulk-entity]")) return;
    applyBulk(table);
  });

  document.querySelectorAll("[data-bulk-entity]").forEach((table) => {
    updateBulkBar(table);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}

export { updateBulkBar };
