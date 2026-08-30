/**
 * AI Chat module — ES module
 *
 * - Streaming chat with SSE from /api/ai/chat/stream
 * - Session management persisted in localStorage
 * - Model selector, sidebar history, prompt chips
 */

// Configuration
const API_BASE = "/api/ai";
const STORAGE_KEY = "azad_ai_chats";
const MAX_HISTORY = 50;

// State
let currentSessionId = null;
let messages = [];
let isStreaming = false;
let currentModel = "gpt-4o-mini";
let chatSessions = [];
let currentSession = null;

// DOM Elements
const elements = {
  messagesContainer: document.getElementById("messages-container"),
  messageInput: document.getElementById("message-input"),
  chatForm: document.getElementById("chat-form"),
  sendBtn: document.getElementById("send-btn"),
  newChatBtn: document.getElementById("new-chat-btn"),
  modelSelect: document.getElementById("model-select"),
  modelIndicator: document.getElementById("model-indicator"),
  sidebar: document.getElementById("sidebar"),
  toggleSidebar: document.getElementById("toggle-sidebar"),
  chatHistory: document.getElementById("chat-history"),
  toastContainer: document.getElementById("toast-container"),
  welcomeMessage: document.querySelector(".welcome-message"),
};

function init() {
  loadChatSessions();
  loadCurrentSession();
  bindEvents();
  autoResizeTextarea();
  highlightCodeBlocks();
}

// Load chat sessions from localStorage
function loadChatSessions() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      chatSessions = JSON.parse(stored);
    }
  } catch (e) {
    console.warn("Failed to load chat sessions:", e);
    chatSessions = [];
  }
  renderChatHistory();
}

function saveChatSessions() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(chatSessions.slice(0, MAX_HISTORY)));
}

function loadCurrentSession() {
  const urlParams = new URLSearchParams(window.location.search);
  const sessionId = urlParams.get("session");

  if (sessionId) {
    loadSession(sessionId);
  } else if (chatSessions.length > 0) {
    loadSession(chatSessions[0].id);
  } else {
    startNewChat();
  }
}

function loadSession(sessionId) {
  const session = chatSessions.find((s) => s.id === sessionId);
  if (!session) return;

  currentSession = session;
  currentSessionId = session.id;
  currentModel = session.model || "gpt-4o-mini";
  messages = session.messages || [];
  session.model = currentModel;

  updateModelUI();
  renderMessages();
  updateSidebarActive();
  updateURL();
}

function startNewChat() {
  currentSession = null;
  currentSessionId = null;
  messages = [];
  currentModel = "gpt-4o-mini";
  updateModelUI();
  renderMessages();
  updateSidebarActive();
  updateURL();
  elements.messageInput.focus();
}

function renderMessages() {
  const container = elements.messagesContainer;
  if (!messages.length) {
    container.textContent = "";
    const welcomeDiv = document.createElement("div");
    welcomeDiv.className = "welcome-message";
    const iconDiv = document.createElement("div");
    iconDiv.className = "welcome-icon";
    iconDiv.textContent = "🤖";
    const h2 = document.createElement("h2");
    h2.textContent = _("مرحباً! كيف يمكنني مساعدتك اليوم؟");
    const promptsDiv = document.createElement("div");
    promptsDiv.className = "suggested-prompts";
    const prompts = [
      { text: _("اشرح لي نظرية فيثاغورس بالتفصيل"), label: _("شرح نظرية فيثاغورس") },
      { text: _("ساعدني في حل هذه المعادلة: 2x + 5 = 15"), label: _("حل معادلة") },
      { text: _("اكتب لي مقالاً عن أهمية الرياضة"), label: _("كتابة مقال") },
      { text: _("ما هي قوانين نيوتن الثلاثة؟"), label: _("قوانين نيوتن") },
    ];
    prompts.forEach((p) => {
      const btn = document.createElement("button");
      btn.className = "prompt-chip";
      btn.dataset.prompt = p.text;
      btn.textContent = p.label;
      promptsDiv.appendChild(btn);
    });
    welcomeDiv.appendChild(iconDiv);
    welcomeDiv.appendChild(h2);
    welcomeDiv.appendChild(promptsDiv);
    container.appendChild(welcomeDiv);
    return;
  }

  container.textContent = "";
  messages.forEach((msg) => {
    const msgDiv = document.createElement("div");
    msgDiv.className = `message ${msg.role}`;
    if (msg.id) msgDiv.dataset.messageId = msg.id;

    const contentDiv = document.createElement("div");
    contentDiv.className = "message-content";
    if (typeof DOMPurify !== "undefined") {
      contentDiv.innerHTML = DOMPurify.sanitize(msg.content);
    } else {
      contentDiv.textContent = msg.content;
    }

    const metaDiv = document.createElement("div");
    metaDiv.className = "message-meta";

    const timeSpan = document.createElement("span");
    timeSpan.className = "message-time";
    timeSpan.textContent = formatTime(msg.created_at);
    metaDiv.appendChild(timeSpan);

    if (msg.role === "assistant") {
      const copyBtn = document.createElement("button");
      copyBtn.className = "copy-btn";
      copyBtn.dataset.content = msg.content;
      copyBtn.textContent = _("نسخ");
      metaDiv.appendChild(copyBtn);
    }

    msgDiv.appendChild(contentDiv);
    msgDiv.appendChild(metaDiv);
    container.appendChild(msgDiv);
  });

  highlightCodeBlocks();
  scrollToBottom();
}

function formatTime(dateStr) {
  if (!dateStr) return "";
  const date = new Date(dateStr);
  return date.toLocaleTimeString("ar", { hour: "2-digit", minute: "2-digit" });
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

let highlightDebounce = null;
function highlightCodeBlocks() {
  if (!window.Prism) return;
  clearTimeout(highlightDebounce);
  highlightDebounce = setTimeout(() => {
    document.querySelectorAll("pre code").forEach((block) => {
      if (!block.dataset.highlighted) {
        Prism.highlightElement(block);
      }
    });
  }, 50);
}

function scrollToBottom() {
  const container = elements.messagesContainer;
  if (container) {
    container.scrollTop = container.scrollHeight;
  }
}

// Event Binding
function bindEvents() {
  elements.chatForm.addEventListener("submit", handleSubmit);

  elements.newChatBtn.addEventListener("click", startNewChat);

  elements.modelSelect.addEventListener("change", (e) => {
    currentModel = e.target.value;
    updateModelUI();
    if (currentSession) {
      currentSession.model = currentModel;
      saveChatSessions();
    }
  });

  elements.toggleSidebar.addEventListener("click", () => {
    document.body.classList.toggle("sidebar-open");
  });

  elements.messageInput.addEventListener("input", autoResizeTextarea);

  elements.messageInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      elements.chatForm.dispatchEvent(new Event("submit"));
    }
  });

  // Click delegation: copy buttons, prompt chips, chat history items
  document.addEventListener("click", (e) => {
    if (e.target.classList.contains("copy-btn")) {
      copyToClipboard(e.target.dataset.content);
      showToast(_("تم النسخ"));
      return;
    }
    if (e.target.classList.contains("prompt-chip")) {
      if (elements.messageInput) {
        elements.messageInput.value = e.target.dataset.prompt;
        autoResizeTextarea();
        elements.messageInput.focus();
      }
      return;
    }
    const historyItem = e.target.closest(".chat-history-item");
    if (historyItem) {
      loadSession(historyItem.dataset.sessionId);
      document.body.classList.remove("sidebar-open");
    }
  });
}

function handleSubmit(e) {
  e.preventDefault();
  const text = elements.messageInput.value.trim();
  if (!text || isStreaming) return;

  addMessage("user", text);
  elements.messageInput.value = "";
  autoResizeTextarea();
  elements.sendBtn.disabled = true;

  sendMessage(text);
}

function addMessage(role, content) {
  const message = {
    role,
    content,
    created_at: new Date().toISOString(),
  };
  messages.push(message);
  renderMessages();
  return message;
}

async function sendMessage(text) {
  isStreaming = true;
  elements.sendBtn.disabled = true;
  elements.messageInput.disabled = true;
  elements.sendBtn.classList.add("loading");

  const assistantMsg = { role: "assistant", content: "", created_at: new Date().toISOString() };
  messages.push(assistantMsg);
  renderMessages();

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 120000);

  try {
    const response = await fetch(`${API_BASE}/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCsrfToken(),
      },
      body: JSON.stringify({
        question: text,
        context: getContext(),
        model: currentModel,
      }),
      signal: controller.signal,
    });

    if (!response.ok) {
      const errText = await response.text().catch(() => "");
      throw new Error(`HTTP ${response.status}: ${errText || response.statusText}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value, { stream: true });
      buffer += chunk;

      const lines = buffer.split("\n");
      buffer = lines.pop();

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          const data = line.slice(6).trim();
          if (data === "[DONE]") break;
          try {
            const parsed = JSON.parse(data);
            if (parsed.delta) {
              updateLastMessage(parsed.delta);
            }
            if (parsed.error) {
              throw new Error(parsed.error);
            }
          } catch (e) {
            console.warn("Parse error:", e);
          }
        }
      }
    }
  } catch (error) {
    if (error.name === "AbortError") {
      updateLastMessage(_("انتهت مهلة الطلب. يرجى المحاولة مرة أخرى."));
      showToast(_("انتهت مهلة الاتصال"), "error");
    } else {
      console.error("Stream error:", error);
      updateLastMessage(_("حدث خطأ في الاتصال. يرجى المحاولة مرة أخرى."));
      showToast(_("حدث خطأ: ") + error.message, "error");
    }
  } finally {
    clearTimeout(timeoutId);
    isStreaming = false;
    elements.sendBtn.disabled = false;
    elements.messageInput.disabled = false;
    elements.sendBtn.classList.remove("loading");
    elements.messageInput.focus();

    saveCurrentSession();
  }
}

function updateLastMessage(delta) {
  if (messages.length === 0) return;
  const lastMsg = messages[messages.length - 1];
  if (lastMsg.role === "assistant") {
    lastMsg.content += delta;
    renderMessages();
  }
}

async function saveCurrentSession() {
  if (!currentSessionId) {
    const sessionData = {
      id: generateId(),
      model: currentModel,
      messages: messages,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    chatSessions.unshift(sessionData);
    currentSessionId = sessionData.id;
    currentSession = sessionData;
  } else {
    currentSession.messages = messages;
    currentSession.model = currentModel;
    currentSession.updated_at = new Date().toISOString();
  }
  saveChatSessions();
  renderChatHistory();
  updateURL();
}

function updateModelUI() {
  elements.modelSelect.value = currentModel;
  if (elements.modelIndicator) {
    elements.modelIndicator.textContent = currentModel;
  }
}

function updateSidebarActive() {
  document.querySelectorAll(".chat-history-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.sessionId === currentSessionId);
  });
}

function renderChatHistory() {
  const container = elements.chatHistory;
  if (!chatSessions.length) {
    container.innerHTML = `<p class="empty-history">${_("لا توجد محادثات سابقة")}</p>`;
    return;
  }

  container.innerHTML = chatSessions
    .map(
      (session) => `
      <li class="chat-history-item ${session.id === currentSessionId ? "active" : ""}"
          data-session-id="${session.id}">
        <div class="chat-history-title">${escapeHtml(session.messages[0]?.content?.slice(0, 40) || _("محادثة جديدة"))}</div>
        <div class="chat-history-meta">
          <span>${formatDate(session.updated_at || session.created_at)}</span>
          <span class="model-badge">${session.model || "gpt-4o-mini"}</span>
        </div>
        <button class="delete-chat" data-session-id="${session.id}" aria-label="${_("حذف")}">🗑️</button>
      </li>
    `,
    )
    .join("");
}

function updateURL() {
  const url = new URL(window.location);
  if (currentSessionId) {
    url.searchParams.set("session", currentSessionId);
  } else {
    url.searchParams.delete("session");
  }
  window.history.replaceState({}, "", url);
}

function generateId() {
  return `chat_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
}

function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta?.getAttribute("content") || "";
}

function getContext() {
  const contextParts = [];
  const pageTitle = document.querySelector(".page-title, .page-subtitle");
  if (pageTitle) contextParts.push(pageTitle.textContent.trim());
  return contextParts.join(" | ") || null;
}

function autoResizeTextarea() {
  const textarea = elements.messageInput;
  textarea.style.height = "auto";
  textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
}

function copyToClipboard(text) {
  navigator.clipboard.writeText(text).catch(console.error);
}

function showToast(message, type = "info") {
  // Reuse the centralized toast system if available
  if (window.AzadToast && typeof window.AzadToast.show === "function") {
    window.AzadToast.show({ type, message, duration: 3000 });
    return;
  }
  const container = elements.toastContainer;
  if (!container) return;
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add("show"));
  setTimeout(() => {
    toast.classList.remove("show");
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

function _(text) {
  const L = window.AzadAiChatLabels || {};
  const map = {
    "مرحباً! كيف يمكنني مساعدتك اليوم؟": L.welcome,
    "اشرح لي نظرية فيثاغورس بالتفصيل": L.suggest1,
    "شرح نظرية فيثاغورس": L.suggest1Label,
    "ساعدني في حل هذه المعادلة: 2x + 5 = 15": L.suggest2,
    "حل معادلة": L.suggest2Label,
    "اكتب لي مقالاً عن أهمية الرياضة": L.suggest3,
    "كتابة مقال": L.suggest3Label,
    "ما هي قوانين نيوتن الثلاثة؟": L.suggest4,
    "قوانين نيوتن": L.suggest4Label,
    نسخ: L.copy,
    "تم النسخ": L.copied,
    "انتهت مهلة الطلب. يرجى المحاولة مرة أخرى.": L.timeout,
    "انتهت مهلة الاتصال": L.timeoutToast,
    "حدث خطأ في الاتصال. يرجى المحاولة مرة أخرى.": L.connError,
    "حدث خطأ: ": L.errorPrefix,
    "لا توجد محادثات سابقة": L.noHistory,
    "محادثة جديدة": L.newChat,
    حذف: L.delete,
  };
  return map[text] || text;
}

function formatDate(dateStr) {
  const date = new Date(dateStr);
  return date.toLocaleDateString(document.documentElement.lang || "ar", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Initialize on DOM ready (guard: only run when required elements exist)
if (elements.chatForm && elements.messagesContainer) {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
}

export {
  _,
  addMessage,
  autoResizeTextarea,
  copyToClipboard,
  escapeHtml,
  formatDate,
  formatTime,
  generateId,
  getContext,
  getCsrfToken,
  init,
  loadChatSessions,
  renderChatHistory,
  renderMessages,
  showToast,
  startNewChat,
  updateLastMessage,
  updateModelUI,
};
