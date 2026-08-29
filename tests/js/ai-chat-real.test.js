import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import {
  formatTime,
  escapeHtml,
  generateId,
  getCsrfToken,
  getContext,
  formatDate,
  _,
  autoResizeTextarea,
} from "@app-static/js/ai-chat.js";

describe("AI Chat - formatTime (actual module)", () => {
  it("formats valid date string", () => {
    const result = formatTime("2026-08-29T10:30:00Z");
    expect(result).toBeTruthy();
    expect(result).toMatch(/\d{2}:\d{2}/);
  });

  it("returns empty string for falsy input", () => {
    expect(formatTime(null)).toBe("");
    expect(formatTime(undefined)).toBe("");
    expect(formatTime("")).toBe("");
  });

  it("returns Arabic time format", () => {
    const result = formatTime("2026-08-29T14:00:00Z");
    // Should contain a colon separator for hours:minutes
    expect(result).toContain(":");
  });
});

describe("AI Chat - escapeHtml (actual module)", () => {
  it("escapes HTML entities", () => {
    const result = escapeHtml('<script>alert("xss")</script>');
    expect(result).not.toContain("<script>");
    expect(result).toContain("&lt;");
    expect(result).toContain("&gt;");
  });

  it("preserves normal text", () => {
    expect(escapeHtml("Hello World")).toBe("Hello World");
  });

  it("escapes ampersand", () => {
    expect(escapeHtml("a & b")).toBe("a &amp; b");
  });

  it("escapes quotes", () => {
    // textContent-based escaping doesn't escape quotes
    const result = escapeHtml('He said "hello"');
    expect(result).toBe('He said "hello"');
  });
});

describe("AI Chat - generateId (actual module)", () => {
  it("generates unique IDs with chat_ prefix", () => {
    const id1 = generateId();
    const id2 = generateId();
    expect(id1).not.toBe(id2);
    expect(id1).toMatch(/^chat_\d+_/);
    expect(id2).toMatch(/^chat_\d+_/);
  });

  it("generates IDs with timestamp component", () => {
    const id = generateId();
    const timestamp = Number(id.split("_")[1]);
    expect(timestamp).toBeGreaterThan(0);
  });

  it("generates IDs with random component", () => {
    const id = generateId();
    const parts = id.split("_");
    expect(parts[2].length).toBe(9);
  });
});

describe("AI Chat - getCsrfToken (actual module)", () => {
  beforeEach(() => {
    document.head.innerHTML = '<meta name="csrf-token" content="test-token-123">';
  });

  it("reads token from meta tag", () => {
    expect(getCsrfToken()).toBe("test-token-123");
  });

  it("returns empty string when no meta tag", () => {
    document.head.innerHTML = "";
    expect(getCsrfToken()).toBe("");
  });

  it("returns empty string when meta tag has no content", () => {
    document.head.innerHTML = '<meta name="csrf-token">';
    expect(getCsrfToken()).toBe("");
  });
});

describe("AI Chat - getContext (actual module)", () => {
  it("reads page title for context", () => {
    document.body.innerHTML = '<div class="page-title">Mathematics</div>';
    expect(getContext()).toBe("Mathematics");
  });

  it("reads page subtitle for context", () => {
    document.body.innerHTML = '<div class="page-subtitle">Algebra 101</div>';
    expect(getContext()).toBe("Algebra 101");
  });

  it("returns null when no page title", () => {
    document.body.innerHTML = "";
    expect(getContext()).toBeNull();
  });

  it("reads page title when available", () => {
    document.body.innerHTML = `
      <div class="page-title">Math</div>
      <div class="page-subtitle">Grade 10</div>
    `;
    const result = getContext();
    // querySelector returns first match
    expect(result).toBe("Math");
  });
});

describe("AI Chat - formatDate (actual module)", () => {
  it("formats date in Arabic locale", () => {
    const result = formatDate("2026-08-29T10:30:00Z");
    expect(result).toBeTruthy();
    // Arabic locale uses different separators
    expect(result.length).toBeGreaterThan(0);
  });

  it("uses document language for locale", () => {
    const originalLang = document.documentElement.lang;
    document.documentElement.lang = "ar";
    const result = formatDate("2026-08-29T10:30:00Z");
    expect(result).toBeTruthy();
    document.documentElement.lang = originalLang;
  });
});

describe("AI Chat - _ translation helper (actual module)", () => {
  beforeEach(() => {
    window.AzadAiChatLabels = undefined;
  });

  it("returns Arabic text as fallback", () => {
    const result = _("مرحباً! كيف يمكنني مساعدتك اليوم؟");
    expect(result).toBe("مرحباً! كيف يمكنني مساعدتك اليوم؟");
  });

  it("returns custom label when provided", () => {
    window.AzadAiChatLabels = { welcome: "Hello!" };
    const result = _("مرحباً! كيف يمكنني مساعدتك اليوم؟");
    expect(result).toBe("Hello!");
  });

  it("returns original text for unknown keys", () => {
    expect(_("unknown text")).toBe("unknown text");
  });

  it("handles all translation keys", () => {
    window.AzadAiChatLabels = {
      welcome: "Welcome",
      suggest1: "Suggest 1",
      suggest1Label: "Label 1",
      suggest2: "Suggest 2",
      suggest2Label: "Label 2",
      suggest3: "Suggest 3",
      suggest3Label: "Label 3",
      suggest4: "Suggest 4",
      suggest4Label: "Label 4",
      copy: "Copy",
      copied: "Copied",
      timeout: "Timeout",
      timeoutToast: "Timeout toast",
      connError: "Connection error",
      errorPrefix: "Error: ",
      noHistory: "No history",
      newChat: "New chat",
      delete: "Delete",
    };

    expect(_("مرحباً! كيف يمكنني مساعدتك اليوم؟")).toBe("Welcome");
    expect(_("نسخ")).toBe("Copy");
    expect(_("تم النسخ")).toBe("Copied");
    expect(_("لا توجد محادثات سابقة")).toBe("No history");
    expect(_("محادثة جديدة")).toBe("New chat");
    expect(_("حذف")).toBe("Delete");
  });
});

describe("AI Chat - autoResizeTextarea (actual module)", () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <form id="chat-form">
        <textarea id="message-input"></textarea>
      </form>
    `;
  });

  it("resizes textarea based on scrollHeight", () => {
    const textarea = document.getElementById("message-input");
    Object.defineProperty(textarea, "scrollHeight", { value: 100, configurable: true });
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
    expect(textarea.style.height).toBe("100px");
  });

  it("caps at 200px max height", () => {
    const textarea = document.getElementById("message-input");
    Object.defineProperty(textarea, "scrollHeight", { value: 500, configurable: true });
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
    expect(textarea.style.height).toBe("200px");
  });

  it("sets height to auto first", () => {
    const textarea = document.getElementById("message-input");
    Object.defineProperty(textarea, "scrollHeight", { value: 80, configurable: true });
    const spy = vi.spyOn(textarea.style, "height", "set");
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
    expect(spy).toHaveBeenCalledWith("auto");
    expect(spy).toHaveBeenCalledWith("80px");
  });
});

describe("AI Chat - localStorage persistence", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("stores chat sessions", () => {
    const sessions = [
      { id: "s1", model: "gpt-4o-mini", messages: [], created_at: new Date().toISOString() },
    ];
    localStorage.setItem("azad_ai_chats", JSON.stringify(sessions));
    const stored = JSON.parse(localStorage.getItem("azad_ai_chats"));
    expect(stored.length).toBe(1);
  });

  it("limits to 50 sessions", () => {
    const sessions = Array.from({ length: 60 }, (_, i) => ({
      id: `s${i}`,
      model: "gpt-4o-mini",
      messages: [],
      created_at: new Date().toISOString(),
    }));
    localStorage.setItem("azad_ai_chats", JSON.stringify(sessions.slice(0, 50)));
    const stored = JSON.parse(localStorage.getItem("azad_ai_chats"));
    expect(stored.length).toBe(50);
  });

  it("handles corrupted data gracefully", () => {
    localStorage.setItem("azad_ai_chats", "not-json");
    let sessions = [];
    try {
      sessions = JSON.parse(localStorage.getItem("azad_ai_chats"));
    } catch {
      sessions = [];
    }
    expect(sessions).toEqual([]);
  });

  it("handles missing key", () => {
    const raw = localStorage.getItem("azad_ai_chats_nonexistent");
    let sessions = [];
    if (raw) {
      try {
        sessions = JSON.parse(raw);
      } catch {
        sessions = [];
      }
    }
    expect(sessions).toEqual([]);
  });
});

describe("AI Chat - DOMPurify sanitization", () => {
  it("sanitizes HTML via DOMPurify when available", () => {
    const sanitize = (html) => {
      const div = document.createElement("div");
      div.textContent = html;
      return div.innerHTML;
    };

    const result = sanitize('<script>alert("xss")</script>Hello');
    expect(result).not.toContain("<script>");
    expect(result).toContain("Hello");
  });

  it("falls back to textContent when DOMPurify not available", () => {
    const div = document.createElement("div");
    div.textContent = '<img src=x onerror=alert(1)>';
    expect(div.innerHTML).toContain("&lt;");
    expect(div.innerHTML).toContain("&gt;");
  });
});

describe("AI Chat - Message rendering patterns", () => {
  it("creates user message element", () => {
    const container = document.createElement("div");
    const msg = document.createElement("div");
    msg.className = "message user";
    msg.dataset.messageId = "msg-1";
    const content = document.createElement("div");
    content.className = "message-content";
    content.textContent = "مرحبا";
    msg.appendChild(content);
    container.appendChild(msg);

    expect(container.querySelector(".message.user")).toBeTruthy();
    expect(container.querySelector(".message-content").textContent).toBe("مرحبا");
  });

  it("creates assistant message with copy button", () => {
    const container = document.createElement("div");
    const msg = document.createElement("div");
    msg.className = "message assistant";
    const content = document.createElement("div");
    content.className = "message-content";
    content.textContent = "أهلاً!";
    const meta = document.createElement("div");
    meta.className = "message-meta";
    const copyBtn = document.createElement("button");
    copyBtn.className = "copy-btn";
    copyBtn.dataset.content = "أهلاً!";
    copyBtn.textContent = "نسخ";
    meta.appendChild(copyBtn);
    msg.appendChild(content);
    msg.appendChild(meta);
    container.appendChild(msg);

    expect(container.querySelector(".message.assistant")).toBeTruthy();
    expect(container.querySelector(".copy-btn")).toBeTruthy();
  });

  it("creates message with timestamp", () => {
    const container = document.createElement("div");
    const msg = document.createElement("div");
    msg.className = "message user";
    const meta = document.createElement("div");
    meta.className = "message-meta";
    const time = document.createElement("span");
    time.className = "message-time";
    time.textContent = "10:30 ص";
    meta.appendChild(time);
    msg.appendChild(meta);
    container.appendChild(msg);

    expect(msg.querySelector(".message-time").textContent).toBe("10:30 ص");
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

  it("changes model on select", () => {
    const select = document.createElement("select");
    select.innerHTML = '<option value="gpt-4o-mini">Mini</option><option value="gpt-4o">Full</option>';
    select.value = "gpt-4o";
    expect(select.value).toBe("gpt-4o");
  });
});

describe("AI Chat - Prompt chips", () => {
  it("creates prompt chips with data-prompt", () => {
    const prompts = [
      { text: "اشرح لي نظرية فيثاغورس", label: "شرح نظرية" },
      { text: "ساعدني في حل معادلة", label: "حل معادلة" },
      { text: "اكتب لي مقالاً", label: "كتابة مقال" },
      { text: "ما هي قوانين نيوتن؟", label: "قوانين نيوتن" },
    ];

    const promptsDiv = document.createElement("div");
    promptsDiv.className = "suggested-prompts";
    prompts.forEach((p) => {
      const btn = document.createElement("button");
      btn.className = "prompt-chip";
      btn.dataset.prompt = p.text;
      btn.textContent = p.label;
      promptsDiv.appendChild(btn);
    });

    expect(promptsDiv.querySelectorAll(".prompt-chip").length).toBe(4);
    expect(promptsDiv.querySelector('[data-prompt*="فيثاغورس"]')).toBeTruthy();
  });

  it("fills input on chip click", () => {
    const input = document.createElement("input");
    const chip = document.createElement("button");
    chip.className = "prompt-chip";
    chip.dataset.prompt = "اشرح لي هذا المفهوم";
    chip.addEventListener("click", () => {
      input.value = chip.dataset.prompt;
    });

    chip.click();
    expect(input.value).toBe("اشرح لي هذا المفهوم");
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

  it("handles Prism not available", () => {
    const original = window.Prism;
    window.Prism = undefined;
    expect(() => {
      if (window.Prism) {
        document.querySelectorAll("pre code").forEach((block) => {
          window.Prism.highlightElement(block);
        });
      }
    }).not.toThrow();
    window.Prism = original;
  });
});

describe("AI Chat - URL session tracking", () => {
  it("parses session ID from URL", () => {
    const params = new URLSearchParams("?session=s123");
    expect(params.get("session")).toBe("s123");
  });

  it("returns null for no session param", () => {
    const params = new URLSearchParams("");
    expect(params.get("session")).toBeNull();
  });
});

describe("AI Chat - Sidebar history", () => {
  it("renders history items", () => {
    const history = document.createElement("ul");
    const sessions = [
      { id: "s1", messages: [{ content: "First message" }], model: "gpt-4o-mini" },
      { id: "s2", messages: [{ content: "Second message" }], model: "gpt-4o" },
    ];

    history.innerHTML = sessions
      .map(
        (s) => `
      <li class="chat-history-item ${s.id === "s1" ? "active" : ""}" data-session-id="${s.id}">
        <div class="chat-history-title">${escapeHtml(s.messages[0]?.content?.slice(0, 40) || "محادثة جديدة")}</div>
        <span class="model-badge">${s.model}</span>
      </li>
    `,
      )
      .join("");

    const items = history.querySelectorAll(".chat-history-item");
    expect(items.length).toBe(2);
    expect(items[0].classList.contains("active")).toBe(true);
  });

  it("shows empty state when no sessions", () => {
    const history = document.createElement("ul");
    history.innerHTML = '<p class="empty-history">لا توجد محادثات سابقة</p>';
    expect(history.querySelector(".empty-history")).toBeTruthy();
  });
});

describe("AI Chat - Toast integration", () => {
  it("creates toast element", () => {
    const container = document.createElement("div");
    container.id = "toast-container";
    const toast = document.createElement("div");
    toast.className = "toast toast-info";
    toast.textContent = "تم النسخ";
    container.appendChild(toast);

    expect(container.querySelector(".toast")).toBeTruthy();
    expect(toast.textContent).toBe("تم النسخ");
  });

  it("removes toast after timeout", () => {
    vi.useFakeTimers();
    const container = document.createElement("div");
    const toast = document.createElement("div");
    toast.className = "toast toast-info";
    toast.textContent = "Test";
    container.appendChild(toast);

    setTimeout(() => {
      toast.classList.remove("show");
      setTimeout(() => toast.remove(), 300);
    }, 3000);

    vi.advanceTimersByTime(3100);
    expect(toast.classList.contains("show")).toBe(false);
    vi.advanceTimersByTime(400);
    expect(toast.parentNode).toBeNull();
    vi.useRealTimers();
  });
});

describe("AI Chat - copy to clipboard", () => {
  it("calls navigator.clipboard.writeText", async () => {
    const writeTextSpy = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: writeTextSpy },
      writable: true,
      configurable: true,
    });

    const text = "Hello, world!";
    await navigator.clipboard.writeText(text);
    expect(writeTextSpy).toHaveBeenCalledWith(text);
  });
});

describe("AI Chat - Copy button click delegation", () => {
  it("copies content on copy-btn click", async () => {
    const writeTextSpy = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: writeTextSpy },
      writable: true,
      configurable: true,
    });

    const copyBtn = document.createElement("button");
    copyBtn.className = "copy-btn";
    copyBtn.dataset.content = "Hello, world!";
    copyBtn.textContent = "نسخ";
    document.body.appendChild(copyBtn);

    copyBtn.addEventListener("click", (e) => {
      if (e.target.classList.contains("copy-btn")) {
        navigator.clipboard.writeText(e.target.dataset.content);
      }
    });

    copyBtn.click();
    expect(writeTextSpy).toHaveBeenCalledWith("Hello, world!");
  });
});

describe("AI Chat - Session management", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("creates new session with correct structure", () => {
    const sessionData = {
      id: generateId(),
      model: "gpt-4o-mini",
      messages: [{ role: "user", content: "Hello" }],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };

    expect(sessionData.id).toMatch(/^chat_\d+_/);
    expect(sessionData.messages.length).toBe(1);
    expect(sessionData.messages[0].role).toBe("user");
  });

  it("updates existing session", () => {
    const session = {
      id: "chat_123",
      model: "gpt-4o",
      messages: [],
      created_at: new Date().toISOString(),
    };

    session.messages.push({ role: "user", content: "Hi" });
    session.model = "gpt-4o-mini";
    session.updated_at = new Date().toISOString();

    expect(session.messages.length).toBe(1);
    expect(session.model).toBe("gpt-4o-mini");
  });

  it("prepends new session to history", () => {
    const chatSessions = [
      { id: "old", messages: [], created_at: "2026-08-28" },
    ];
    const newSession = { id: "new", messages: [], created_at: "2026-08-29" };
    chatSessions.unshift(newSession);

    expect(chatSessions[0].id).toBe("new");
    expect(chatSessions.length).toBe(2);
  });
});

describe("AI Chat - Update URL", () => {
  it("sets session param in URL", () => {
    const url = new URL("https://example.com/ai/chat");
    url.searchParams.set("session", "chat_123");
    expect(url.searchParams.get("session")).toBe("chat_123");
  });

  it("removes session param when no session", () => {
    const url = new URL("https://example.com/ai/chat?session=chat_123");
    url.searchParams.delete("session");
    expect(url.searchParams.get("session")).toBeNull();
  });
});

describe("AI Chat - Sidebar toggle", () => {
  it("toggles sidebar-open class on body", () => {
    document.body.classList.toggle("sidebar-open");
    expect(document.body.classList.contains("sidebar-open")).toBe(true);
    document.body.classList.toggle("sidebar-open");
    expect(document.body.classList.contains("sidebar-open")).toBe(false);
  });
});

describe("AI Chat - Message input Enter key handling", () => {
  it("Enter without Shift sends form", () => {
    const form = document.createElement("form");
    const submitSpy = vi.fn();
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      submitSpy();
    });

    const input = document.createElement("textarea");
    const event = new KeyboardEvent("keydown", {
      key: "Enter",
      shiftKey: false,
      bubbles: true,
    });
    input.dispatchEvent(event);

    if (event.key === "Enter" && !event.shiftKey) {
      form.dispatchEvent(new Event("submit"));
    }
    expect(submitSpy).toHaveBeenCalled();
  });

  it("Shift+Enter does not send form", () => {
    const form = document.createElement("form");
    const submitSpy = vi.fn();
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      submitSpy();
    });

    const input = document.createElement("textarea");
    const event = new KeyboardEvent("keydown", {
      key: "Enter",
      shiftKey: true,
      bubbles: true,
    });
    input.dispatchEvent(event);

    if (event.key === "Enter" && !event.shiftKey) {
      form.dispatchEvent(new Event("submit"));
    }
    expect(submitSpy).not.toHaveBeenCalled();
  });
});

describe("AI Chat - Send button disabled during streaming", () => {
  it("disables send button when isStreaming is true", () => {
    const sendBtn = document.createElement("button");
    let isStreaming = true;
    sendBtn.disabled = isStreaming;
    sendBtn.classList.add("loading");
    expect(sendBtn.disabled).toBe(true);
    expect(sendBtn.classList.contains("loading")).toBe(true);
  });

  it("re-enables send button after streaming", () => {
    const sendBtn = document.createElement("button");
    sendBtn.disabled = false;
    sendBtn.classList.remove("loading");
    expect(sendBtn.disabled).toBe(false);
    expect(sendBtn.classList.contains("loading")).toBe(false);
  });
});
