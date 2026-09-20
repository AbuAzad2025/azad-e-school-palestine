import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { closeModal, openModal } from "@app-static/js/pages/search.js";

// يغطي search.js أسطر 102-105: تحديث aria-activedescendant عند التنقل بالكيبورد
// (فرع الإسناد عند وجود عنصر نشط، وفرع الإزالة عند غيابه).
describe("Search - aria-activedescendant (lines 102-105)", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    // jsdom لا يطبّق scrollIntoView — نستبدلها بترقعة اختبار قياسية
    Element.prototype.scrollIntoView = vi.fn();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  async function renderOneResult() {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: vi.fn().mockResolvedValue({
          data: {
            schools: [{ title: "مدرسة أزاد", subtitle: "رام الله", url: "/schools/1", icon: "school" }],
            users: [],
            classes: [],
            subscriptions: [],
          },
        }),
      }),
    );

    openModal();
    const input = document.getElementById("azad-search-input");
    input.value = "أزا";
    input.dispatchEvent(new Event("input", { bubbles: true }));
    vi.advanceTimersByTime(250);
    await vi.advanceTimersByTimeAsync(0);
    return input;
  }

  it("sets aria-activedescendant when a result becomes active", async () => {
    const input = await renderOneResult();

    input.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));

    expect(input.getAttribute("aria-activedescendant")).toBe("azad-search-active");
    const active = document.getElementById("azad-search-active");
    expect(active).toBeTruthy();
    expect(active.classList.contains("is-active")).toBe(true);
  });

  it("removes aria-activedescendant when no item is active", async () => {
    const input = await renderOneResult();

    // تنشيط ثم تفريغ النتائج باستعلام قصير → activeIndex=-1 → فرع الإزالة
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    expect(input.hasAttribute("aria-activedescendant")).toBe(true);

    const input2 = document.getElementById("azad-search-input");
    input2.value = "أ";
    input2.dispatchEvent(new Event("input", { bubbles: true }));
    vi.advanceTimersByTime(250);
    await vi.advanceTimersByTimeAsync(0);

    expect(input2.hasAttribute("aria-activedescendant")).toBe(false);
  });

  it("clears aria state on close", async () => {
    const input = await renderOneResult();
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true }));
    expect(input.hasAttribute("aria-activedescendant")).toBe(true);

    closeModal();
    const inputAfter = document.getElementById("azad-search-input");
    if (inputAfter) {
      expect(inputAfter.hasAttribute("aria-activedescendant")).toBe(false);
    }
  });
});
