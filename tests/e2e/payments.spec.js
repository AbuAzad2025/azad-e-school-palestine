/**
 * Payments journey — subscription page -> gateway selection -> payment intent
 * -> verification -> invoice.
 *
 * The gateway round trip runs against the `manual` gateway on purpose: it is
 * the one gateway the app owns end to end, so the assertions about ownership
 * (403 on someone else's subscription) and amount/currency binding (400 when
 * they drift from the plan price) are real server behaviour rather than a
 * mocked third party agreeing with itself. Card gateways are covered by the
 * webhook unit suite, which can assert on the HMAC path a browser cannot see.
 *
 * `thirdPartyRequests` aborts and records every off-origin browser request, so
 * a silent CDN dependency fails here instead of in production.
 *
 * Two conventions worth stating:
 *   - Authenticated calls go through `page.request`, never the standalone
 *     `request` fixture: only `page.request` shares the browser context's
 *     session cookie.
 *   - Every JSON POST carries `X-CSRFToken`. Flask-WTF's CSRFProtect is global
 *     and guards API endpoints exactly as it guards forms.
 */

import { csrfToken, expect, test } from "./fixtures.js";

const GATEWAY_IDS = ["stripe", "paytabs", "cashu", "whatsapp", "manual"];

const INTENT = {
  gateway: "manual",
  amount: "500.00",
  currency: "ILS",
};

test.describe("Payments — unauthenticated", () => {
  test("payment methods page requires a session", async ({ page, baseURL }) => {
    await page.goto(`${baseURL}/payments/`);
    // page.goto reports the final response, i.e. the login page it landed on.
    await expect(page).toHaveURL(/\/auth\/login/);
    await expect(page.getByTestId("login-form")).toBeVisible();
  });

  test("create-intent is not reachable without a session", async ({ request, baseURL, seed }) => {
    const response = await request.post(`${baseURL}/payments/create-intent`, {
      // maxRedirects: 0 — Playwright follows redirects by default and would
      // report the login page's 200, hiding the guard that actually rejected it.
      maxRedirects: 0,
      data: { ...INTENT, subscription_id: seed.subscription_id },
    });
    // Flask-Login bounces with a redirect; CSRF rejects the body first. What
    // matters is that no payment intent is ever produced.
    expect([302, 400, 401, 403]).toContain(response.status());
  });
});

test.describe("Payments — gateway catalogue", () => {
  test.beforeEach(async ({ parentSession }) => {
    // The page confirms the pick with window.alert rather than a navigation,
    // so the dialog is captured instead of raced against.
    await parentSession.addInitScript(() => {
      window.__alerts = [];
      window.alert = (message) => window.__alerts.push(String(message));
    });
    await parentSession.goto("/payments/");
  });

  test("lists every configured gateway", async ({ parentSession }) => {
    await expect(parentSession.getByTestId("payment-method")).toHaveCount(GATEWAY_IDS.length);
    for (const id of GATEWAY_IDS) {
      await expect(parentSession.locator(`[data-method-id="${id}"]`)).toBeVisible();
    }
  });

  test("selecting a gateway reports the choice", async ({ parentSession }) => {
    await parentSession.locator('[data-method-id="paytabs"]').getByTestId("payment-method-select").click();
    await expect
      .poll(() => parentSession.evaluate(() => window.__alerts))
      .toEqual([expect.stringContaining("paytabs")]);
  });

  test("the catalogue makes no third-party browser request", async ({ thirdPartyRequests }) => {
    expect(thirdPartyRequests).toEqual([]);
  });

  test("methods API and page agree on the gateway list", async ({ page, baseURL }) => {
    const response = await page.request.get(`${baseURL}/payments/methods`);
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.methods.map((m) => m.id).sort()).toEqual([...GATEWAY_IDS].sort());
  });
});

test.describe("Payments — subscription page", () => {
  test("student sees the active subscription and the seeded plan", async ({ page, seed, loginAs, baseURL }) => {
    await loginAs(seed.student_email);
    await page.goto(`${baseURL}/billing/${seed.class_id}`);

    await expect(page.getByTestId("current-subscription")).toBeVisible();
    await expect(page.getByTestId("current-subscription-status")).toHaveText(/\S/);
    await expect(page.getByTestId("plan-item")).toHaveCount(1);
    await expect(page.getByTestId("plan-name").first()).toContainText("E2E");
  });

  test("parent sees the plan catalogue without a subscribe button", async ({ parentSession, seed }) => {
    await parentSession.goto(`/billing/${seed.class_id}`);
    await expect(parentSession.getByTestId("plan-item")).toHaveCount(1);
    // Parents cannot self-subscribe: the button is the student's alone.
    await expect(parentSession.getByTestId("plan-subscribe")).toHaveCount(0);
  });
});

test.describe("Payments — payment intent and verification", () => {
  /** POST /payments/create-intent with the session's CSRF token attached. */
  const createIntent = async (page, baseURL, seed, overrides = {}) =>
    page.request.post(`${baseURL}/payments/create-intent`, {
      headers: { "X-CSRFToken": await csrfToken(page) },
      data: { ...INTENT, subscription_id: seed.subscription_id, ...overrides },
    });

  test("a matching intent verifies successfully", async ({ page, baseURL, seed, loginAs }) => {
    await loginAs(seed.student_email);
    await page.goto(`${baseURL}/billing/${seed.class_id}`);

    const created = await createIntent(page, baseURL, seed);
    expect(created.status()).toBe(200);
    const body = await created.json();
    expect(body.gateway).toBe("manual");
    expect(body.amount).toBe("500.00");
    expect(body.payment_id).toBeTruthy();

    const verified = await page.request.post(`${baseURL}/payments/verify`, {
      headers: { "X-CSRFToken": await csrfToken(page) },
      data: { payment_id: body.payment_id, gateway: "manual", verification_data: {} },
    });
    expect(verified.status()).toBe(200);
    expect((await verified.json()).success).toBe(true);
  });

  test("an amount that does not match the plan price is rejected", async ({ page, baseURL, seed, loginAs }) => {
    await loginAs(seed.student_email);
    await page.goto(`${baseURL}/billing/${seed.class_id}`);

    const response = await createIntent(page, baseURL, seed, { amount: "1.00" });
    expect(response.status()).toBe(400);
    expect((await response.json()).error).toBeTruthy();
  });

  test("a currency that does not match the subscription is rejected", async ({ page, baseURL, seed, loginAs }) => {
    await loginAs(seed.student_email);
    await page.goto(`${baseURL}/billing/${seed.class_id}`);

    const response = await createIntent(page, baseURL, seed, { currency: "USD" });
    expect(response.status()).toBe(400);
    expect((await response.json()).error).toBeTruthy();
  });

  test("a subscription owned by somebody else is forbidden", async ({ parentSession, baseURL, seed }) => {
    await parentSession.goto(`/billing/${seed.class_id}`);

    const response = await createIntent(parentSession, baseURL, seed);
    expect(response.status()).toBe(403);
  });

  test("an unsupported gateway is rejected", async ({ page, baseURL, seed, loginAs }) => {
    await loginAs(seed.student_email);
    await page.goto(`${baseURL}/payments/`);

    const response = await page.request.post(`${baseURL}/payments/create-intent`, {
      headers: { "X-CSRFToken": await csrfToken(page) },
      data: { gateway: "western-union", amount: "500.00", currency: "ILS" },
    });
    expect(response.status()).toBe(400);
    expect((await response.json()).error).toBeTruthy();
  });

  test("a non-positive amount is rejected", async ({ page, baseURL, seed, loginAs }) => {
    await loginAs(seed.student_email);
    await page.goto(`${baseURL}/payments/`);

    const response = await page.request.post(`${baseURL}/payments/create-intent`, {
      headers: { "X-CSRFToken": await csrfToken(page) },
      data: { ...INTENT, amount: "0" },
    });
    expect(response.status()).toBe(400);
  });

  test("verification without a payment id is rejected", async ({ page, baseURL, seed, loginAs }) => {
    await loginAs(seed.student_email);
    await page.goto(`${baseURL}/payments/`);

    const response = await page.request.post(`${baseURL}/payments/verify`, {
      headers: { "X-CSRFToken": await csrfToken(page) },
      data: { gateway: "manual" },
    });
    expect(response.status()).toBe(400);
  });

  test("verification of an unsupported gateway is rejected", async ({ page, baseURL, seed, loginAs }) => {
    await loginAs(seed.student_email);
    await page.goto(`${baseURL}/payments/`);

    const response = await page.request.post(`${baseURL}/payments/verify`, {
      headers: { "X-CSRFToken": await csrfToken(page) },
      data: { payment_id: "manual_x", gateway: "western-union" },
    });
    expect(response.status()).toBe(400);
  });
});

test.describe("Payments — invoice", () => {
  test("renders number, status and balance for the seeded subscription", async ({ parentSession, seed }) => {
    await parentSession.goto(`/billing/invoices/${seed.subscription_id}`);

    await expect(parentSession.getByTestId("invoice-number")).toContainText(/\d/);
    await expect(parentSession.getByTestId("invoice-status")).toHaveText(/\S/);
    await expect(parentSession.getByTestId("invoice-balance")).toContainText(/\d/);
  });

  test("an anonymous caller cannot read an invoice", async ({ request, baseURL, seed }) => {
    const response = await request.get(`${baseURL}/billing/invoices/${seed.subscription_id}`, {
      maxRedirects: 0,
    });
    expect([302, 400, 401, 403]).toContain(response.status());
  });

  test("an unknown subscription id is a 404", async ({ page, baseURL, seed, loginAs }) => {
    await loginAs(seed.student_email);
    await page.goto(`${baseURL}/payments/`);

    const response = await page.request.get(`${baseURL}/billing/invoices/99999999`);
    expect(response.status()).toBe(404);
  });
});
