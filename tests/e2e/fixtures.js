/**
 * Shared E2E fixtures.
 *
 * Three rules this module exists to enforce:
 *
 * 1. No hardcoded row ids. `scripts/seed_e2e.py` writes `tests/e2e/.seed.json`
 *    (identifiers only, never the password) and the specs read it. A spec that
 *    guesses an id fails on a fresh CI database for reasons unrelated to the
 *    behaviour under test.
 *
 * 2. No secrets in the repo. `E2E_PASSWORD` and `WHATSAPP_APP_SECRET` come from
 *    the environment; the suite refuses to run without them rather than
 *    silently passing against an unauthenticated app.
 *
 * 3. Hermetic network. Every request whose origin is not the app under test is
 *    aborted and recorded, so a third-party CDN or analytics beacon can neither
 *    slow the suite down nor mask a missing asset. `thirdPartyRequests` exposes
 *    what was blocked so a test can assert the journey stayed internal.
 */

import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import { test as base, expect } from "@playwright/test";

// Playwright transpiles these specs to CommonJS, so `import.meta` is not
// available; `__dirname` is.
const MANIFEST = path.join(__dirname, ".seed.json");

/** localStorage key the onboarding tour checks before it opens. */
const TOUR_KEY = "azad-tour-completed";

export function requireEnv(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `${name} is required for the E2E suite. Run \`scripts/seed_e2e.py\` with it exported, ` +
        `and start the app with the same environment (see .github/workflows/ci.yml).`,
    );
  }
  return value;
}

export function loadSeed() {
  if (!fs.existsSync(MANIFEST)) {
    throw new Error(
      `Missing ${MANIFEST}. Run \`E2E_PASSWORD=... python scripts/seed_e2e.py\` before the suite — ` +
        `the E2E database starts empty, so there is nothing to assert on without it.`,
    );
  }
  return JSON.parse(fs.readFileSync(MANIFEST, "utf8"));
}

/** Meta signs the raw request body; the hex digest is prefixed with the algorithm. */
export function metaSignature(rawBody, secret) {
  return `sha256=${crypto.createHmac("sha256", secret).update(rawBody).digest("hex")}`;
}

/**
 * A message id that has never been seen before.
 *
 * The engine records every processed `message_id` in `ProcessedEvent`, so a
 * fixed id makes the *second* run of the suite replay itself: the command is
 * skipped as a duplicate and the notification the test waits for never
 * arrives. Fresh ids keep the idempotency assertions honest — the replay spec
 * deliberately reuses one id three times within a single run.
 */
export function uniqueMessageId(name) {
  return `wamid.E2E.${Date.now()}.${Math.random().toString(36).slice(2, 8)}.${name}`;
}

/** A single inbound text message in Meta's Cloud API envelope. */
export function metaTextMessage({ messageId, phone, text }) {
  return {
    object: "whatsapp_business_account",
    entry: [
      {
        id: "WABA-E2E",
        changes: [
          {
            field: "messages",
            value: {
              messaging_product: "whatsapp",
              metadata: { display_phone_number: "970500000000", phone_number_id: "PNID-E2E" },
              messages: [
                {
                  from: phone,
                  id: messageId,
                  timestamp: String(Math.floor(Date.now() / 1000)),
                  type: "text",
                  text: { body: text },
                },
              ],
            },
          },
        ],
      },
    ],
  };
}

/**
 * Read the CSRF token the app rendered into `<meta name="csrf-token">`.
 *
 * Flask-WTF's CSRFProtect is global, so it guards JSON endpoints too — an
 * `X-CSRFToken` header is as mandatory for `POST /payments/create-intent` as it
 * is for a form post. Reading it from the page keeps the spec honest about
 * what a real session does.
 */
export async function csrfToken(page) {
  const token = await page.locator('meta[name="csrf-token"]').getAttribute("content");
  if (!token) throw new Error("No csrf-token meta tag — the app did not render a session page.");
  return token;
}

export const test = base.extend({
  /** Parsed seed manifest: school/class/student ids plus the accounts. */
  seed: [
    async ({}, use) => {
      await use(loadSeed());
    },
    { scope: "test" },
  ],

  /** Password from the environment. Resolved once so specs stay declarative. */
  e2ePassword: [
    async ({}, use) => {
      await use(requireEnv("E2E_PASSWORD"));
    },
    { scope: "test" },
  ],

  /** App secret Meta would sign the webhook body with. */
  appSecret: [
    async ({}, use) => {
      await use(requireEnv("WHATSAPP_APP_SECRET"));
    },
    { scope: "test" },
  ],

  /** Shared secret Meta echoes back during webhook subscription. */
  verifyToken: [
    async ({}, use) => {
      await use(requireEnv("WHATSAPP_VERIFY_TOKEN"));
    },
    { scope: "test" },
  ],

  /** Blocked off-origin requests, in order, for assertions. */
  // eslint-disable-next-line no-empty-pattern
  thirdPartyRequests: async ({ page }, use) => {
    const blocked = [];
    await page.route("**/*", (route) => {
      const url = new URL(route.request().url());
      if (!["127.0.0.1", "localhost"].includes(url.hostname)) {
        blocked.push(url.href);
        return route.abort();
      }
      return route.continue();
    });
    await use(blocked);
  },

  /**
   * Log in through the real form. The onboarding tour opens on a first login
   * and its modal would swallow clicks, so it is marked done in localStorage
   * before the first navigation rather than dismissed by selector.
   */
  loginAs: async ({ page, e2ePassword, baseURL }, use) => {
    await page.addInitScript((key) => {
      window.localStorage.setItem(key, "1");
    }, TOUR_KEY);

    const login = async (email) => {
      await page.goto(`${baseURL}/auth/login`);
      await page.getByTestId("login-form").waitFor();
      await page.locator('form[data-testid="login-form"] input[name="email"]').fill(email);
      await page.locator('form[data-testid="login-form"] input[name="password"]').fill(e2ePassword);
      await page.getByTestId("login-submit").click();
      // The server bounces each role to its own landing page; any of them is
      // proof the session cookie landed, so wait for the login form to go away.
      await expect(page.getByTestId("login-form")).toHaveCount(0, { timeout: 15_000 });
      return page;
    };

    await use(login);
  },

  /** Logged-in parent — the persona that owns the seeded family links. */
  parentSession: async ({ page, seed, loginAs }, use) => {
    await loginAs(seed.parent_email);
    await use(page);
  },
});

export { expect };
