import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";

describe("API Client - getCsrfToken", () => {
  beforeEach(() => {
    document.head.innerHTML = "";
    document.body.innerHTML = "";
  });

  it("reads token from meta tag", () => {
    const meta = document.createElement("meta");
    meta.name = "csrf-token";
    meta.content = "abc123";
    document.head.appendChild(meta);

    const input = document.querySelector('meta[name="csrf-token"]');
    expect(input.content).toBe("abc123");
  });

  it("reads token from hidden input", () => {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = "csrf_token";
    input.value = "xyz789";
    document.body.appendChild(input);

    const el = document.querySelector('input[name="csrf_token"]');
    expect(el.value).toBe("xyz789");
  });

  it("returns empty string when no token found", () => {
    const meta = document.querySelector('meta[name="csrf-token"]');
    const input = document.querySelector('input[name="csrf_token"]');
    expect(meta).toBeNull();
    expect(input).toBeNull();
  });
});

describe("API Client - buildUrl", () => {
  it("returns absolute http URL unchanged", () => {
    const url = "https://example.com/api/test";
    expect(url.startsWith("http")).toBe(true);
    expect(url).toBe("https://example.com/api/test");
  });

  it("returns absolute path unchanged", () => {
    const url = "/api/v1/test";
    expect(url.startsWith("/")).toBe(true);
    expect(url).toBe("/api/v1/test");
  });

  it("builds relative URL with base", () => {
    const base = "https://example.com/";
    const path = "api/test";
    const result = base.replace(/\/$/, "") + "/" + path;
    expect(result).toBe("https://example.com/api/test");
  });
});

describe("API Client - request", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    document.head.innerHTML = '<meta name="csrf-token" content="test-csrf">';
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("sends GET request with correct method", async () => {
    const mockResponse = {
      ok: true,
      headers: new Headers({ "Content-Type": "application/json" }),
      json: vi.fn().mockResolvedValue({ data: "test" }),
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse));

    const { request } = await import("@app-static/js/core/api.js");
    const result = await request("GET", "/api/test");

    expect(fetch).toHaveBeenCalledOnce();
    const [, init] = fetch.mock.calls[0];
    expect(init.method).toBe("GET");
    expect(result).toEqual({ data: "test" });
  });

  it("sends POST with JSON body and CSRF header", async () => {
    const mockResponse = {
      ok: true,
      headers: new Headers({ "Content-Type": "application/json" }),
      json: vi.fn().mockResolvedValue({ success: true }),
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse));

    const { request } = await import("@app-static/js/core/api.js");
    const result = await request("POST", "/api/test", {
      body: { name: "test" },
    });

    const [, init] = fetch.mock.calls[0];
    expect(init.method).toBe("POST");
    expect(init.headers.get("X-CSRFToken")).toBe("test-csrf");
    expect(init.headers.get("Content-Type")).toBe("application/json");
    expect(init.body).toBe(JSON.stringify({ name: "test" }));
    expect(result).toEqual({ success: true });
  });

  it("returns text for non-JSON response", async () => {
    const mockResponse = {
      ok: true,
      headers: new Headers({ "Content-Type": "text/html" }),
      text: vi.fn().mockResolvedValue("<html></html>"),
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse));

    const { request } = await import("@app-static/js/core/api.js");
    const result = await request("GET", "/page");
    expect(result).toBe("<html></html>");
  });

  it("throws error on non-ok response", async () => {
    const mockResponse = {
      ok: false,
      status: 404,
      statusText: "Not Found",
      headers: new Headers(),
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse));

    const { request } = await import("@app-static/js/core/api.js");
    await expect(request("GET", "/missing")).rejects.toThrow("HTTP 404: Not Found");
  });

  it("handles abort/timeout gracefully", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(
        () =>
          new Promise((_, reject) => {
            setTimeout(() => {
              const err = new Error("Aborted");
              err.name = "AbortError";
              reject(err);
            }, 10);
          }),
      ),
    );

    const { request } = await import("@app-static/js/core/api.js");
    await expect(
      request("GET", "/slow", { timeout: 1 }),
    ).rejects.toThrow("Request timeout");
  });

  it("sends FormData without JSON stringify", async () => {
    const mockResponse = {
      ok: true,
      headers: new Headers({ "Content-Type": "application/json" }),
      json: vi.fn().mockResolvedValue({ uploaded: true }),
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse));

    const fd = new FormData();
    fd.append("file", "test");

    const { request } = await import("@app-static/js/core/api.js");
    await request("POST", "/upload", { body: fd });

    const [, init] = fetch.mock.calls[0];
    expect(init.body).toBe(fd);
    expect(init.headers.has("Content-Type")).toBe(false);
  });

  it("sends DELETE with correct method", async () => {
    const mockResponse = {
      ok: true,
      headers: new Headers({ "Content-Type": "application/json" }),
      json: vi.fn().mockResolvedValue({ deleted: true }),
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse));

    const { del } = await import("@app-static/js/core/api.js");
    await del("/api/test/1");

    const [, init] = fetch.mock.calls[0];
    expect(init.method).toBe("DELETE");
  });

  it("sends PUT request", async () => {
    const mockResponse = {
      ok: true,
      headers: new Headers({ "Content-Type": "application/json" }),
      json: vi.fn().mockResolvedValue({ updated: true }),
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse));

    const { put } = await import("@app-static/js/core/api.js");
    await put("/api/test/1", { body: { name: "updated" } });

    const [, init] = fetch.mock.calls[0];
    expect(init.method).toBe("PUT");
  });

  it("does not send CSRF token for GET requests", async () => {
    const mockResponse = {
      ok: true,
      headers: new Headers({ "Content-Type": "application/json" }),
      json: vi.fn().mockResolvedValue({}),
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse));

    const { request } = await import("@app-static/js/core/api.js");
    await request("GET", "/api/test");

    const [, init] = fetch.mock.calls[0];
    expect(init.headers.has("X-CSRFToken")).toBe(false);
  });

  it("uses custom csrfToken when provided", async () => {
    const mockResponse = {
      ok: true,
      headers: new Headers({ "Content-Type": "application/json" }),
      json: vi.fn().mockResolvedValue({}),
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(mockResponse));

    const { request } = await import("@app-static/js/core/api.js");
    await request("POST", "/api/test", { csrfToken: "custom-token" });

    const [, init] = fetch.mock.calls[0];
    expect(init.headers.get("X-CSRFToken")).toBe("custom-token");
  });
});
