/**
 * ai-chat.js — remaining branch coverage: DOM wiring, session restore,
 * DOMPurify/Prism paths, click delegation, existing-session persistence.
 *
 * Strategy mirrors ai-chat-stream.test.js: reset module registry, rebuild the
 * chat DOM, then dynamically import so bindings are fresh. Streaming tests
 * stub fetch with a never-resolving promise (or a real SSE reader) so the
 * async loop is deterministic.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const STORAGE_KEY = "azad_ai_chats";

function buildChatDom() {
  document.body.innerHTML = `
    <div id="messages-container"></div>
    <textarea id="message-input"></textarea>
    <form id="chat-form"></form>
    <button id="send-btn"></button>
    <button id="new-chat-btn"></button>
    <select id="model-select"><option value="gpt-4o-mini">mini</option><option value="gpt-4o">big</option></select>
    <div id="model-indicator"></div>
    <div id="sidebar"></div>
    <button id="toggle-sidebar"></button>
    <div id="chat-history"></div>
    <div id="toast-container"></div>
  `;
}

async function importChat() {
  buildChatDom();
  return await import("@app-static/js/ai-chat.js");
}

function sseChunks(chunks) {
  const encoder = new TextEncoder();
  const events = chunks.map((c) => encoder.encode(c));
  let i = 0;
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    body: {
      getReader: () => ({
        read: async () =>
          i < events.length ? { done: false, value: events[i++] } : { done: true, value: undefined },
      }),
    },
  };
}

function hangFetch() {
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
}

function seedSessions(sessions) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(sessions));
}

function makeSession(id, content, model = "gpt-4o-mini") {
  const iso = new Date().toISOString();
  return {
    id,
    model,
    messages: [{ role: "user", content, created_at: iso }],
    created_at: iso,
    updated_at: iso,
  };
}

// document.readyState stubbing for the DOMContentLoaded init branch
const rsDescriptor = Object.getOwnPropertyDescriptor(Document.prototype, "readyState");

function stubReadyState(value) {
  Object.defineProperty(Document.prototype, "readyState", {
    configurable: true,
    get: () => value,
  });
}

beforeEach(() => {
  vi.resetModules();
  localStorage.clear();
  window.AzadAiChatLabels = undefined;
  delete window.DOMPurify;
  delete window.Prism;
  delete window.AzadToast; // exercise the container fallback in showToast
  window.history.replaceState({}, "", "/");
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  if (rsDescriptor) {
    Object.defineProperty(Document.prototype, "readyState", rsDescriptor);
  }
  window.history.replaceState({}, "", "/");
});

describe("ai-chat dom — storage & session restore", () => {
  it("corrupted localStorage warns, resets sessions, and renders the empty state", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    localStorage.setItem(STORAGE_KEY, "{not json");
    const mod = await importChat();
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("Failed to load"), expect.any(Error));
    expect(mod.renderChatHistory).toBeTypeOf("function");
    expect(document.querySelector("#chat-history .empty-history")).toBeTruthy();
  });

  it("auto-loads the most recent session and syncs model UI + URL", async () => {
    seedSessions([makeSession("s1", "restore me", "gpt-4o"), makeSession("s2", "second")]);
    const mod = await importChat();
    // The restored assistant-side state is visible through the model UI + URL
    expect(document.getElementById("model-select").value).toBe("gpt-4o");
    expect(document.getElementById("model-indicator").textContent).toBe("gpt-4o");
    expect(window.location.search).toContain("session=s1");
    // The session's first message is rendered in the transcript
    const bubbles = document.querySelectorAll("#messages-container .message");
    expect(bubbles.length).toBeGreaterThan(0);
    expect(bubbles[0].textContent).toContain("restore me");
    expect(mod.generateId).toBeTypeOf("function");
  });

  it("an unknown ?session= id falls back to the welcome screen", async () => {
    seedSessions([makeSession("s1", "hello")]);
    window.history.replaceState({}, "/", "/?session=missing");
    const mod = await importChat();
    expect(document.getElementById("model-select").value).toBe("gpt-4o-mini");
    // loadSession early-returns on an unknown id: nothing rendered, nothing crashed
    expect(document.querySelector("#messages-container .message")).toBeNull();
    expect(mod.generateId).toBeTypeOf("function");
  });
});

describe("ai-chat dom — render branches", () => {
  it("sanitizes content through DOMPurify when available", async () => {
    hangFetch();
    vi.stubGlobal("DOMPurify", { sanitize: (c) => `SAFE:${c}` });
    const mod = await importChat();
    mod.addMessage("user", "hi");
    const bubble = document.querySelector("#messages-container .message.user .message-content");
    expect(bubble.innerHTML).toBe("SAFE:hi");
  });

  it("highlights unmarked code blocks via Prism after the debounce tick", async () => {
    vi.useFakeTimers();
    hangFetch();
    const highlight = vi.fn();
    window.Prism = { highlightElement: highlight };
    const mod = await importChat();
    // Blocks live outside the transcript (renderMessages wipes its container)
    document.body.insertAdjacentHTML(
      "beforeend",
      '<pre><code id="cb1">const a = 1;</code></pre>' +
        '<pre><code id="cb2" data-highlighted="true">const b = 2;</code></pre>',
    );
    mod.addMessage("assistant", "plain text");
    await vi.advanceTimersByTimeAsync(60);
    const targets = highlight.mock.calls.map((c) => c[0]);
    expect(targets).toContain(document.getElementById("cb1"));
    expect(targets).not.toContain(document.getElementById("cb2"));
  });
});

describe("ai-chat dom — event wiring", () => {
  it("model change persists to the current session; change without a session skips saving", async () => {
    seedSessions([makeSession("s1", "q")]);
    const mod = await importChat();
    const select = document.getElementById("model-select");
    select.value = "gpt-4o";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY));
    expect(stored[0].model).toBe("gpt-4o");

    // Without any session: updateModelUI still runs, nothing to save (no throw)
    seedSessions([]);
    window.history.replaceState({}, "", "/");
    const mod2 = await importChat();
    expect(mod2.generateId).toBeTypeOf("function");
    const select2 = document.getElementById("model-select");
    select2.value = "gpt-4o";
    expect(() => select2.dispatchEvent(new Event("change", { bubbles: true }))).not.toThrow();
  });

  it("toggle sidebar flips the body class", async () => {
    const mod = await importChat();
    document.getElementById("toggle-sidebar").click();
    expect(document.body.classList.contains("sidebar-open")).toBe(true);
    document.getElementById("toggle-sidebar").click();
    expect(document.body.classList.contains("sidebar-open")).toBe(false);
    expect(mod.generateId).toBeTypeOf("function");
  });

  it("Enter submits the form, Shift+Enter does not", async () => {
    hangFetch();
    const mod = await importChat();
    const input = document.getElementById("message-input");
    input.value = "via enter";
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    expect(document.querySelector("#messages-container .message.user")).toBeTruthy();
    expect(input.value).toBe("");
    expect(mod.generateId).toBeTypeOf("function");

    // Shift+Enter keeps the draft
    input.value = "draft";
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", shiftKey: true, bubbles: true }),
    );
    expect(input.value).toBe("draft");
  });

  it("clicking a copy button copies and toasts", async () => {
    hangFetch();
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    const mod = await importChat();
    const btn = document.createElement("button");
    btn.className = "copy-btn";
    btn.dataset.content = "copy me";
    document.body.appendChild(btn);
    btn.click();
    expect(writeText).toHaveBeenCalledWith("copy me");
    expect(document.querySelector("#toast-container .toast")).toBeTruthy();
    expect(mod.generateId).toBeTypeOf("function");
  });

  it("clicking a prompt chip fills and focuses the input", async () => {
    hangFetch();
    const mod = await importChat();
    const chip = document.createElement("button");
    chip.className = "prompt-chip";
    chip.dataset.prompt = "شرح الجذور التربيعية";
    document.body.appendChild(chip);
    chip.click();
    const input = document.getElementById("message-input");
    expect(input.value).toBe("شرح الجذور التربيعية");
    expect(document.activeElement).toBe(input);
    expect(mod.generateId).toBeTypeOf("function");
  });

  it("clicking a history item loads that session and closes the sidebar", async () => {
    hangFetch();
    seedSessions([makeSession("s1", "first session q"), makeSession("s2", "second session q")]);
    const mod = await importChat();
    document.getElementById("toggle-sidebar").click();
    const items = document.querySelectorAll("#chat-history .chat-history-item");
    expect(items.length).toBe(2);
    items[1].click();
    const bubbles = [...document.querySelectorAll("#messages-container .message")];
    expect(bubbles.some((b) => b.textContent.includes("second session q"))).toBe(true);
    expect(document.body.classList.contains("sidebar-open")).toBe(false);
    expect(window.location.search).toContain("session=s2");
    expect(mod.generateId).toBeTypeOf("function");
  });});

describe("ai-chat dom — existing-session persistence", () => {
  it("streaming into a restored session updates it in place and marks history active", async () => {
    seedSessions([makeSession("s1", "old question")]);
    const mod = await importChat();
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(sseChunks(['data: {"delta": "answer"}\n\n', "data: [DONE]\n\n"])),
      ),
    );
    const input = document.getElementById("message-input");
    input.value = "follow-up";
    document
      .getElementById("chat-form")
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await vi.waitFor(() => {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY));
      expect(stored[0].messages.length).toBe(3); // old + user + assistant
    });
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY));
    expect(stored[0].messages[1].content).toBe("follow-up");
    expect(stored[0].messages[2].content).toBe("answer");
    expect(stored[0].id).toBe("s1");
    // updateSidebarActive marked the loaded session in the history list
    const active = document.querySelector("#chat-history .chat-history-item.active");
    expect(active).toBeTruthy();
    expect(active.dataset.sessionId).toBe("s1");
    expect(mod.generateId).toBeTypeOf("function");
  });
});

describe("ai-chat dom — deferred init", () => {
  it("initializes on DOMContentLoaded when the document is still loading", async () => {
    stubReadyState("loading");
    buildChatDom();
    const mod = await import("@app-static/js/ai-chat.js");
    // Nothing initialized yet: no welcome message
    expect(document.querySelector("#messages-container .message")).toBeNull();
    document.dispatchEvent(new Event("DOMContentLoaded"));
    // init() ran: welcome state rendered
    expect(document.querySelector(".welcome-message")).toBeTruthy();
    expect(mod.generateId).toBeTypeOf("function");
  });
});
