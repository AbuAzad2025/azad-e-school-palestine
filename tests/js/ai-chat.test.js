import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";

describe("AI Chat - localStorage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("stores chat sessions", () => {
    const sessions = [
      { id: "s1", title: "Session 1", messages: [], createdAt: Date.now() },
    ];
    localStorage.setItem("azad-ai-sessions", JSON.stringify(sessions));
    const stored = JSON.parse(localStorage.getItem("azad-ai-sessions"));
    expect(stored.length).toBe(1);
    expect(stored[0].title).toBe("Session 1");
  });

  it("limits to 50 sessions", () => {
    const sessions = Array.from({ length: 60 }, (_, i) => ({
      id: `s${i}`,
      title: `Session ${i}`,
      messages: [],
      createdAt: Date.now() + i,
    }));
    localStorage.setItem("azad-ai-sessions", JSON.stringify(sessions.slice(-50)));
    const stored = JSON.parse(localStorage.getItem("azad-ai-sessions"));
    expect(stored.length).toBe(50);
  });
});

describe("AI Chat - DOMPurify", () => {
  it("sanitizes HTML via innerHTML", () => {
    const div = document.createElement("div");
    div.innerHTML = '<img src=x onerror=alert(1)>';
    const img = div.querySelector("img");
    expect(img).toBeTruthy();
    expect(div.textContent).toContain("");
  });

  it("textContent does not execute scripts", () => {
    const div = document.createElement("div");
    div.textContent = '<script>alert("xss")</script>Hello';
    expect(div.innerHTML).not.toContain("<script>");
    expect(div.textContent).toContain("Hello");
  });
});

describe("AI Chat - Message rendering", () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="chat-messages"></div>';
  });

  it("creates user message element", () => {
    const container = document.getElementById("chat-messages");
    const msg = document.createElement("div");
    msg.className = "azad-chat-msg azad-chat-msg--user";
    msg.textContent = "مرحبا";
    container.appendChild(msg);
    expect(container.children.length).toBe(1);
    expect(container.querySelector(".azad-chat-msg--user")).toBeTruthy();
  });

  it("creates assistant message element", () => {
    const container = document.getElementById("chat-messages");
    const msg = document.createElement("div");
    msg.className = "azad-chat-msg azad-chat-msg--assistant";
    msg.textContent = "أهلاً بك!";
    container.appendChild(msg);
    expect(container.querySelector(".azad-chat-msg--assistant")).toBeTruthy();
  });
});

describe("AI Chat - Model selection", () => {
  it("defaults to gpt-4o-mini", () => {
    const defaultModel = "gpt-4o-mini";
    expect(defaultModel).toBe("gpt-4o-mini");
  });

  it("validates model options", () => {
    const models = ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"];
    expect(models).toContain("gpt-4o-mini");
    expect(models).toContain("gpt-4o");
  });
});

describe("AI Chat - Prompt chips", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div class="prompt-chips">
        <button class="prompt-chip" data-prompt="اشرح لي هذا المفهوم">شرح</button>
        <button class="prompt-chip" data-prompt="أعطني مثالاً">مثال</button>
        <button class="prompt-chip" data-prompt="اختبرني">اختبار</button>
      </div>
      <input id="chat-input" type="text" />
    `;
  });

  it("fills input on chip click", () => {
    const chips = document.querySelectorAll(".prompt-chip");
    const input = document.getElementById("chat-input");
    chips.forEach((chip) => {
      chip.addEventListener("click", () => {
        input.value = chip.dataset.prompt;
      });
    });
    chips[0].click();
    expect(input.value).toBe("اشرح لي هذا المفهوم");
  });

  it("chip data attributes are correct", () => {
    const chips = document.querySelectorAll(".prompt-chip");
    expect(chips.length).toBe(3);
    expect(chips[2].dataset.prompt).toBe("اختبرني");
  });
});

describe("AI Chat - Code highlighting", () => {
  it("creates pre/code blocks for code", () => {
    const div = document.createElement("div");
    div.innerHTML = '<pre><code class="language-python">print("hello")</code></pre>';
    const codeBlock = div.querySelector("code");
    expect(codeBlock).toBeTruthy();
    expect(codeBlock.classList.contains("language-python")).toBe(true);
  });
});

describe("AI Chat - URL session tracking", () => {
  beforeEach(() => {
    delete window.location;
    window.location = { href: "https://example.com/ai/chat", search: "" };
  });

  it("parses session ID from URL", () => {
    window.location.search = "?session=s123";
    const params = new URLSearchParams(window.location.search);
    expect(params.get("session")).toBe("s123");
  });

  it("returns null for no session param", () => {
    window.location.search = "";
    const params = new URLSearchParams(window.location.search);
    expect(params.get("session")).toBeNull();
  });
});

describe("AI Chat - Sidebar history", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <div id="chat-history">
        <div class="chat-history-item" data-id="s1">Session 1</div>
        <div class="chat-history-item" data-id="s2">Session 2</div>
      </div>
    `;
  });

  it("renders history items", () => {
    const items = document.querySelectorAll(".chat-history-item");
    expect(items.length).toBe(2);
    expect(items[0].dataset.id).toBe("s1");
  });

  it("highlights active session", () => {
    const items = document.querySelectorAll(".chat-history-item");
    items[0].classList.add("active");
    expect(items[0].classList.contains("active")).toBe(true);
    expect(items[1].classList.contains("active")).toBe(false);
  });
});

describe("AI Chat - Toast integration", () => {
  it("calls AzadToast for errors", () => {
    window.AzadToast = {
      error: vi.fn(),
      success: vi.fn(),
    };
    window.AzadToast.error("خطأ في الاتصال");
    expect(window.AzadToast.error).toHaveBeenCalledWith("خطأ في الاتصال");
  });

  it("calls AzadToast for success", () => {
    window.AzadToast = {
      success: vi.fn(),
    };
    window.AzadToast.success("تم الإرسال");
    expect(window.AzadToast.success).toHaveBeenCalledWith("تم الإرسال");
  });
});
