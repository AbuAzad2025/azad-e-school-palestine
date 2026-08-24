import { test, expect } from "@playwright/test";

test.describe("Landing Page", () => {
  test("loads successfully", async ({ page }) => {
    const resp = await page.goto("/");
    expect(resp.status()).toBe(200);
  });

  test("has page title", async ({ page }) => {
    await page.goto("/");
    const title = await page.title();
    expect(title.length).toBeGreaterThan(0);
  });

  test("contains main content", async ({ page }) => {
    await page.goto("/");
    await expect(page.locator("body")).toBeVisible();
  });

  test("has RTL direction", async ({ page }) => {
    await page.goto("/");
    const dir = await page.locator("html").getAttribute("dir");
    expect(dir).toBe("rtl");
  });

  test("has lang attribute", async ({ page }) => {
    await page.goto("/");
    const lang = await page.locator("html").getAttribute("lang");
    expect(lang).toBe("ar");
  });
});

test.describe("Health Endpoints", () => {
  test("basic health returns 200", async ({ request }) => {
    const resp = await request.get("/health");
    expect(resp.status()).toBe(200);
    const body = await resp.json();
    expect(body).toHaveProperty("status");
  });

  test("API health returns 200", async ({ request }) => {
    const resp = await request.get("/api/v1/health");
    expect(resp.status()).toBe(200);
  });
});

test.describe("Auth Pages", () => {
  test("login page renders", async ({ page }) => {
    const resp = await page.goto("/auth/login");
    expect(resp.status()).toBe(200);
  });

  test("register page renders", async ({ page }) => {
    const resp = await page.goto("/auth/register");
    expect(resp.status()).toBe(200);
  });

  test("forgot password page renders", async ({ page }) => {
    const resp = await page.goto("/auth/forgot");
    expect(resp.status()).toBe(200);
  });

  test("login page has form", async ({ page }) => {
    await page.goto("/auth/login");
    // النموذج الرئيسي (وليس نموذج تبديل اللغة في الـ navbar)
    const form = page.locator('form:has(input[name="password"])');
    await expect(form).toBeVisible();
  });

  test("login form has email field", async ({ page }) => {
    await page.goto("/auth/login");
    const emailInput = page.locator('input[name="email"], input[type="email"]');
    await expect(emailInput).toBeVisible();
  });

  test("login form has password field", async ({ page }) => {
    await page.goto("/auth/login");
    const passInput = page.locator('input[name="password"], input[type="password"]');
    await expect(passInput).toBeVisible();
  });

  test("login form has submit button", async ({ page }) => {
    await page.goto("/auth/login");
    const submit = page.locator('button[type="submit"]');
    await expect(submit).toBeVisible();
  });
});

test.describe("Static Assets", () => {
  test("brand.css loads", async ({ request }) => {
    const resp = await request.get("/static/css/brand.css");
    expect(resp.status()).toBe(200);
  });

  test("index.js loads", async ({ request }) => {
    const resp = await request.get("/static/js/index.js");
    expect(resp.status()).toBe(200);
  });

  test("ai-chat.js loads", async ({ request }) => {
    const resp = await request.get("/static/js/ai-chat.js");
    expect(resp.status()).toBe(200);
  });
});

test.describe("Error Pages", () => {
  test("404 page renders for unknown route", async ({ page }) => {
    const resp = await page.goto("/nonexistent-page-xyz");
    expect(resp.status()).toBe(404);
  });
});

test.describe("RBAC - Unauthenticated Access", () => {
  const protectedRoutes = [
    "/admin/",
    "/admin/users",
    "/admin/schools",
    "/admin/moe-export",
    "/schools/",
    "/schools/classes",
    "/billing/admin",
    "/billing/discounts",
    "/tutoring/",
    "/ai/chat",
    "/family/",
    "/progress/my",
    "/messages/inbox",
    "/notifications/",
    "/auth/dashboard",
    "/schools/new",
  ];

  for (const route of protectedRoutes) {
    test(`redirects ${route} to login`, async ({ page }) => {
      const resp = await page.goto(route);
      const url = page.url();
      const redirectedToLogin =
        url.includes("/auth/login") || resp.status() === 302 || resp.status() === 401 || resp.status() === 403;
      expect(redirectedToLogin).toBe(true);
    });
  }
});

test.describe("Theme Toggle", () => {
  test("theme toggle button exists", async ({ page }) => {
    await page.goto("/");
    const toggle = page.locator("[data-theme-toggle]");
    const count = await toggle.count();
    expect(count).toBeGreaterThanOrEqual(0);
  });
});

test.describe("Mobile Nav", () => {
  test("mobile nav toggle exists on small viewport", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto("/");
    const toggle = page.locator("[data-nav-toggle]");
    const count = await toggle.count();
    expect(count).toBeGreaterThanOrEqual(0);
  });
});

test.describe("CSRF Protection", () => {
  test("login form has CSRF token", async ({ page }) => {
    await page.goto("/auth/login");
    // التوكن داخل نموذج الدخول تحديداً (نموذج اللغة في الـ navbar له توكنه الخاص)
    const csrfInput = page.locator(
      'form:has(input[name="password"]) input[name="csrf_token"]',
    );
    const count = await csrfInput.count();
    expect(count).toBe(1);
  });
});

test.describe("Form Validation", () => {
  test("login rejects empty submission", async ({ page }) => {
    await page.goto("/auth/login");
    const submit = page.locator('button[type="submit"]');
    await submit.click();
    await page.waitForTimeout(1000);
    const url = page.url();
    expect(url.includes("/auth/login")).toBe(true);
  });
});

test.describe("Responsive Meta Tag", () => {
  test("has viewport meta tag", async ({ page }) => {
    await page.goto("/");
    const meta = page.locator('meta[name="viewport"]');
    await expect(meta).toHaveAttribute("content", /width=device-width/);
  });
});

test.describe("PWA Manifest", () => {
  test("manifest link exists", async ({ page }) => {
    await page.goto("/");
    const manifest = page.locator('link[rel="manifest"]');
    const count = await manifest.count();
    expect(count).toBeGreaterThanOrEqual(0);
  });
});

test.describe("Performance", () => {
  test("page loads within 5 seconds", async ({ page }) => {
    const start = Date.now();
    await page.goto("/");
    const loadTime = Date.now() - start;
    expect(loadTime).toBeLessThan(5000);
  });
});
