/**
 * Azad API client — ES module
 *
 * Thin wrapper around fetch with:
 * - CSRF token injection
 * - JSON/form serialization
 * - AbortController / timeout
 * - Consistent error handling
 */

const DEFAULT_TIMEOUT = 30000;

function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta) return meta.content;
  const input = document.querySelector('input[name="csrf_token"]');
  return input ? input.value : "";
}

function buildUrl(path, base = "") {
  if (path.startsWith("http") || path.startsWith("/")) return path;
  return base ? `${base.replace(/\/$/, "")}/${path}` : path;
}

/**
 * Perform an HTTP request.
 * @param {string} method
 * @param {string} url
 * @param {object} options
 */
export async function request(method, url, options = {}) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), options.timeout || DEFAULT_TIMEOUT);

  const headers = new Headers(options.headers || {});
  const csrfToken = options.csrfToken ?? getCsrfToken();
  if (csrfToken && !["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase())) {
    headers.set("X-CSRFToken", csrfToken);
  }

  const init = {
    method: method.toUpperCase(),
    signal: controller.signal,
    headers,
  };

  let body = options.body;
  if (
    body &&
    !(body instanceof FormData) &&
    !(body instanceof URLSearchParams) &&
    typeof body !== "string"
  ) {
    body = JSON.stringify(body);
    if (!headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
  }
  if (body !== undefined) init.body = body;

  try {
    const response = await fetch(buildUrl(url, options.baseUrl), init);
    clearTimeout(timeoutId);

    if (!response.ok) {
      const err = new Error(`HTTP ${response.status}: ${response.statusText}`);
      err.response = response;
      throw err;
    }

    const contentType = response.headers.get("Content-Type") || "";
    if (contentType.includes("application/json")) {
      return await response.json();
    }
    return await response.text();
  } catch (error) {
    clearTimeout(timeoutId);
    if (error.name === "AbortError") {
      const err = new Error("Request timeout");
      err.name = "TimeoutError";
      throw err;
    }
    if (!navigator.onLine) {
      const err = new Error("No internet connection");
      err.name = "NetworkError";
      throw err;
    }
    throw error;
  }
}

export const get = (url, options = {}) => request("GET", url, options);
export const post = (url, options = {}) => request("POST", url, options);
export const put = (url, options = {}) => request("PUT", url, options);
export const del = (url, options = {}) => request("DELETE", url, options);

export default { request, get, post, put, delete: del };
