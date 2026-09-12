/**
 * B8 — ai-chat.js deep coverage: streaming protocol, error paths, session state.
 *
 * The module binds `elements` at import time and auto-inits when the chat DOM
 * exists. Each test therefore resets the module registry, rebuilds the chat
 * DOM, then re-imports so state and bindings are fresh. sendMessage is not
 * exported, so streaming is driven through the real form submit handler.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

function buildChatDom() {
  document.body.innerHTML = `
    <div id="messages-container"></div>
    <textarea id="message-input"></textarea>
    <form id="chat-form"></form>
    <button id="send-btn"></button>
    <button id="new-chat-btn"></button>
    <select id="model-select"><option value="gpt-4o-mini">mini</option></select>
    <div id="model-indicator"></div>
    <div id="sidebar"></div>
    <button id="toggle-sidebar"></button>
    <div id="chat-history"></div>
    <div id="toast-container"></div>
  `;
}

function sseResponse(chunks, { ok = true, status = 200, statusText = "OK" } = {}) {
  const encoder = new TextEncoder();
  const events = chunks.map((c) => encoder.encode(c));
  let i = 0;
  return {
    ok,
    status,
    statusText,
    text: async () => "err-body",
    body: {
      getReader: () => ({
        read: async () => (i < events.length ? { done: false, value: events[i++] } : { done: true, value: undefined }),
      }),
    },
  };
}

async function importChat() {
  buildChatDom();
  return await import("@app-static/js/ai-chat.js");
}

function submitForm(mod, text) {
  const input = document.getElementById("message-input");
  input.value = text;
  document.getElementById("chat-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
}

beforeEach(() => {
  vi.resetModules();
  localStorage.clear();
  window.AzadAiChatLabels = undefined;
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("ai-chat stream — pure helpers", () => {
  it("generateId returns unique prefixed ids", async () => {
    const mod = await importChat();
    const a = mod.generateId();
    const b = mod.generateId();
    expect(a).toMatch(/^chat_\d+_/);
    expect(a).not.toBe(b);
  });

  it("escapeHtml escapes angle brackets", async () => {
    const mod = await importChat();
    expect(mod.escapeHtml("<script>")).not.toContain("<script>");
  });

  it("formatTime renders a time string", async () => {
    const mod = await importChat();
    // locale-dependent (ar → '05:30 م'), so assert the clock shape loosely
    expect(mod.formatTime("2026-09-12T14:30:00Z")).toMatch(/\d{1,2}:\d{2}/);
  });

  it("getCsrfToken reads meta tag or empty", async () => {
    const mod = await importChat();
    expect(mod.getCsrfToken()).toBe("");
    document.head.innerHTML = '<meta name="csrf-token" content="tok123">';
    expect(mod.getCsrfToken()).toBe("tok123");
    document.head.innerHTML = "";
  });

  it("getContext builds context from page title", async () => {
    const mod = await importChat();
    document.body.insertAdjacentHTML("beforeend", '<div class="page-title">الرياضيات</div>');
    expect(mod.getContext()).toBe("الرياضيات");
  });

  it("getContext returns null without title", async () => {
    const mod = await importChat();
    expect(mod.getContext()).toBeNull();
  });
});

describe("ai-chat stream — labels & translation", () => {
  it("_ returns original text without labels", async () => {
    const mod = await importChat();
    expect(mod._("hello")).toBe("hello");
  });

  it("_ maps text when AzadAiChatLabels provided", async () => {
    window.AzadAiChatLabels = { welcome: "Welcome!", copy: "Copy" };
    const mod = await importChat();
    expect(mod._("مرحباً! كيف يمكنني مساعدتك اليوم؟")).toBe("Welcome!");
    expect(mod._("نسخ")).toBe("Copy");
    expect(mod._("unmapped")).toBe("unmapped");
  });
});

describe("ai-chat stream — messages & rendering", () => {
  it("addMessage appends and renders message bubble", async () => {
    const mod = await importChat();
    const msg = mod.addMessage("user", "مرحبا");
    expect(msg.role).toBe("user");
    expect(msg.created_at).toBeTruthy();
    expect(document.getElementById("messages-container").innerHTML).toContain("مرحبا");
  });

  it("updateLastMessage appends only to assistant messages", async () => {
    const mod = await importChat();
    mod.addMessage("user", "سؤال");
    mod.updateLastMessage("ignored");
    const assistant = mod.addMessage("assistant", "");
    mod.updateLastMessage("جواب");
    mod.updateLastMessage(" إضافي");
    expect(assistant.content).toBe("جواب إضافي");
  });

  it("updateLastMessage is a no-op with empty messages", async () => {
    const mod = await importChat();
    expect(() => mod.updateLastMessage("x")).not.toThrow();
  });

  it("showToast delegates to AzadToast when available", async () => {
    const mod = await importChat();
    const show = vi.fn();
    window.AzadToast = { show };
    mod.showToast("تنبيه", "error");
    expect(show).toHaveBeenCalledWith(expect.objectContaining({ type: "error", message: "تنبيه" }));
    delete window.AzadToast;
  });

  it("showToast falls back to inline toast container and auto-removes", async () => {
    vi.useFakeTimers();
    const mod = await importChat();
    delete window.AzadToast;
    mod.showToast("رسالة", "info");
    const toast = document.querySelector("#toast-container .toast");
    expect(toast).toBeTruthy();
    expect(toast.textContent).toBe("رسالة");
    vi.advanceTimersByTime(3400);
    expect(document.querySelector("#toast-container .toast")).toBeNull();
  });

  it("copyToClipboard writes and swallows clipboard errors", async () => {
    const mod = await importChat();
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    expect(() => mod.copyToClipboard("text")).not.toThrow();
    expect(writeText).toHaveBeenCalledWith("text");
  });
});

describe("ai-chat stream — sessions & model UI", () => {
  it("updateModelUI syncs select and indicator", async () => {
    const mod = await importChat();
    mod.updateModelUI();
    expect(document.getElementById("model-select").value).toBe("gpt-4o-mini");
    expect(document.getElementById("model-indicator").textContent).toBe("gpt-4o-mini");
  });

  it("renderChatHistory shows empty state then session list", async () => {
    const mod = await importChat();
    mod.renderChatHistory();
    expect(document.querySelector(".empty-history")).toBeTruthy();
    const session = {
      id: "chat_1",
      model: "gpt-4o-mini",
      messages: [{ role: "user", content: "first question" }],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    localStorage.setItem("azad_ai_chats", JSON.stringify([session]));
    mod.loadChatSessions();
    mod.renderChatHistory();
    const item = document.querySelector(".chat-history-item");
    expect(item).toBeTruthy();
    expect(item.dataset.sessionId).toBe("chat_1");
    expect(item.querySelector(".chat-history-title").textContent).toContain("first question");
  });

  it("startNewChat resets to welcome state", async () => {
    const mod = await importChat();
    mod.startNewChat();
    expect(document.querySelector(".welcome-message")).toBeTruthy();
  });
});

describe("ai-chat stream — streaming via form submit (mocked fetch)", () => {
  it("streams deltas into the assistant bubble and saves the session", async () => {
    const mod = await importChat();
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse(['data: {"delta": "مرحبا"}\n\n', 'data: {"delta": " بك"}\n\n', "data: [DONE]\n\n"]),
    );
    vi.stubGlobal("fetch", fetchMock);

    submitForm(mod, "سؤال");
    await vi.waitFor(() => {
      expect(JSON.parse(localStorage.getItem("azad_ai_chats") || "[]").length).toBe(1);
    });

    const container = document.getElementById("messages-container");
    expect(container.innerHTML).toContain("مرحبا");
    expect(container.innerHTML).toContain(" بك");
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/ai/chat/stream");
    expect(opts.method).toBe("POST");
    expect(JSON.parse(opts.body).question).toBe("سؤال");
    expect(opts.headers["X-CSRFToken"]).toBe("");
    const stored = JSON.parse(localStorage.getItem("azad_ai_chats"));
    expect(stored[0].messages.some((m) => m.role === "assistant" && m.content.includes("مرحبا"))).toBe(true);
    // UI restored after stream ends
    expect(document.getElementById("send-btn").disabled).toBe(false);
  });

  it("ignores empty submissions", async () => {
    const mod = await importChat();
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    submitForm(mod, "   ");
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(document.getElementById("messages-container").innerHTML).not.toContain("user-bubble");
  });

  it("skips malformed SSE lines without crashing", async () => {
    const mod = await importChat();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(sseResponse(["data: {broken json}\n\n", 'data: {"delta": "ok"}\n\n'])),
    );
    submitForm(mod, "q");
    await vi.waitFor(() => {
      expect(document.getElementById("messages-container").innerHTML).toContain("ok");
    });
    expect(warn).toHaveBeenCalled();
  });

  it("rejects HTTP errors and restores UI state", async () => {
    const mod = await importChat();
    const err = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse([], { ok: false, status: 500, statusText: "boom" })));
    submitForm(mod, "q");
    await vi.waitFor(() => {
      expect(err).toHaveBeenCalled();
    });
    expect(document.getElementById("send-btn").disabled).toBe(false);
    expect(document.getElementById("message-input").disabled).toBe(false);
  });

  it("routes SSE error events to the parse-warning path", async () => {
    // Module behavior: parsed.error throws inside the JSON.parse try, which the
    // inner catch handles as a parse warning (not a fatal stream error).
    const mod = await importChat();
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse(['data: {"error": "quota exceeded"}\n\n'])));
    submitForm(mod, "q");
    await vi.waitFor(() => {
      expect(warn).toHaveBeenCalled();
    });
  });

  it("maps AbortError to timeout message and toast", async () => {
    const mod = await importChat();
    const abortErr = new Error("aborted");
    abortErr.name = "AbortError";
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abortErr));
    submitForm(mod, "q");
    await vi.waitFor(() => {
      expect(document.getElementById("messages-container").innerHTML).toContain("مهلة");
    });
  });
});

describe("ai-chat stream — init via DOM", () => {
  it("init binds events and autosizes the textarea", async () => {
    const mod = await importChat();
    mod.init();
    const input = document.getElementById("message-input");
    expect(input.style.height).toBeTruthy();
  });
});
