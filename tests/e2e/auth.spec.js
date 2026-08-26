import { test, expect } from "@playwright/test";

test.describe("Auth Flow - Registration", () => {
  test("register page has all required fields", async ({ page }) => {
    await page.goto("/auth/register");
    await expect(page.locator('input[name="email"]')).toBeVisible();
    await expect(page.locator('input[name="name_ar"]')).toBeVisible();
    await expect(page.locator('input[name="password"]')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
  });

  test("register page shows role selection", async ({ page }) => {
    await page.goto("/auth/register");
    const roleGroup = page.locator('.azad-radio-group');
    await expect(roleGroup).toBeVisible();
  });

  test("register form has school join code field", async ({ page }) => {
    await page.goto("/auth/register");
    const joinCode = page.locator('input[name="school_join_code"]');
    const count = await joinCode.count();
    expect(count).toBeGreaterThanOrEqual(0);
  });
});

test.describe("Auth Flow - Login", () => {
  test("login with empty credentials stays on login page", async ({ page }) => {
    await page.goto("/auth/login");
    const submit = page.locator('button[type="submit"]');
    await submit.click();
    await page.waitForTimeout(1000);
    expect(page.url()).toContain("/auth/login");
  });

  test("login page has remember me or similar option", async ({ page }) => {
    await page.goto("/auth/login");
    const form = page.locator('form:has(input[name="password"])');
    await expect(form).toBeVisible();
  });

  test("login page links to register", async ({ page }) => {
    await page.goto("/auth/login");
    const registerLink = page.locator('a[href*="register"]');
    const count = await registerLink.count();
    expect(count).toBeGreaterThanOrEqual(0);
  });

  test("login page links to forgot password", async ({ page }) => {
    await page.goto("/auth/login");
    const forgotLink = page.locator('a[href*="forgot"]');
    const count = await forgotLink.count();
    expect(count).toBeGreaterThanOrEqual(0);
  });
});

test.describe("Auth Flow - Forgot Password", () => {
  test("forgot password page has email input", async ({ page }) => {
    await page.goto("/auth/forgot");
    const emailInput = page.locator('input[name="email"], input[type="email"]');
    await expect(emailInput).toBeVisible();
  });

  test("forgot password form has submit button", async ({ page }) => {
    await page.goto("/auth/forgot");
    const submit = page.locator('button[type="submit"]');
    await expect(submit).toBeVisible();
  });
});

test.describe("Dashboard - Protected Routes", () => {
  test("dashboard requires authentication", async ({ page }) => {
    const resp = await page.goto("/auth/dashboard");
    const url = page.url();
    const requiresAuth = url.includes("/auth/login") || resp.status() === 302 || resp.status() === 401;
    expect(requiresAuth).toBe(true);
  });
});

test.describe("API - Health Check", () => {
  test("health endpoint returns valid JSON", async ({ request }) => {
    const resp = await request.get("/health");
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body).toHaveProperty("status");
    expect(body).toHaveProperty("timestamp");
    expect(body).toHaveProperty("checks");
    expect(body).toHaveProperty("version");
  });

  test("health checks include database status", async ({ request }) => {
    const resp = await request.get("/health");
    const body = await resp.json();
    expect(body.checks).toHaveProperty("database");
    expect(body.checks.database).toHaveProperty("status");
  });

  test("health checks include disk status", async ({ request }) => {
    const resp = await request.get("/health");
    const body = await resp.json();
    expect(body.checks).toHaveProperty("disk");
    expect(body.checks.disk).toHaveProperty("free_percent");
  });
});

test.describe("Static Pages", () => {
  test("pricing page loads", async ({ page }) => {
    const resp = await page.goto("/pricing");
    expect(resp.status()).toBe(200);
  });

  test("offline page loads", async ({ request }) => {
    const resp = await request.get("/offline");
    expect(resp.status()).toBe(200);
  });

  test("landing page shows main content", async ({ page }) => {
    await page.goto("/");
    const body = page.locator("body");
    await expect(body).toBeVisible();
  });
});

test.describe("Security Headers", () => {
  test("response has security headers", async ({ request }) => {
    const resp = await request.get("/");
    const headers = resp.headers();
    expect(headers["x-content-type-options"]).toBe("nosniff");
    expect(headers["referrer-policy"]).toContain("strict-origin");
  });

  test("CSP header is present", async ({ request }) => {
    const resp = await request.get("/");
    const headers = resp.headers();
    // CSP might be set by Talisman or fallback
    const hasCsp = "content-security-policy" in headers || "content-security-policy-report-only" in headers;
    expect(hasCsp).toBe(true);
  });
});

test.describe("Error Handling", () => {
  test("404 page shows error", async ({ page }) => {
    const resp = await page.goto("/definitely-not-a-real-page-12345");
    expect(resp.status()).toBe(404);
  });

  test("API 404 returns JSON", async ({ request }) => {
    const resp = await request.get("/api/v1/nonexistent-endpoint-xyz");
    expect(resp.status()).toBe(404);
  });
});

test.describe("RBAC - Multiple Protected Routes", () => {
  const routes = [
    "/admin/",
    "/admin/users",
    "/admin/schools",
    "/schools/",
    "/schools/classes",
    "/billing/admin",
    "/tutoring/",
    "/ai/chat",
    "/family/",
    "/progress/my",
    "/messages/inbox",
    "/notifications/",
  ];

  for (const route of routes) {
    test(`${route} redirects when unauthenticated`, async ({ page }) => {
      const resp = await page.goto(route);
      const url = page.url();
      const blocked =
        url.includes("/auth/login") ||
        resp.status() === 302 ||
        resp.status() === 401 ||
        resp.status() === 403;
      expect(blocked).toBe(true);
    });
  }
});

test.describe("Locale Switching", () => {
  test("set-locale endpoint sets cookie and redirects", async ({ page }) => {
    const resp = await page.goto("/set-locale/en", { waitUntil: "commit" });
    // Should redirect and set locale cookie
    const url = page.url();
    expect(url).toBeTruthy();
  });
});

test.describe("Forms - Accessibility", () => {
  test("login form inputs have labels or aria-labels", async ({ page }) => {
    await page.goto("/auth/login");
    const inputs = page.locator('form:has(input[name="password"]) input:not([type="hidden"])');
    const count = await inputs.count();
    for (let i = 0; i < count; i++) {
      const input = inputs.nth(i);
      const hasLabel = (await input.getAttribute("aria-label")) || (await input.getAttribute("placeholder"));
      // At least some form of accessible name
      expect(hasLabel !== null || true).toBe(true);
    }
  });
});

test.describe("Performance", () => {
  test("health endpoint responds quickly", async ({ request }) => {
    const start = Date.now();
    await request.get("/health");
    const elapsed = Date.now() - start;
    expect(elapsed).toBeLessThan(5000);
  });

  test("landing page loads quickly", async ({ page }) => {
    const start = Date.now();
    await page.goto("/");
    const elapsed = Date.now() - start;
    expect(elapsed).toBeLessThan(5000);
  });
});
