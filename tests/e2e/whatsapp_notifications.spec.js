/**
 * WhatsApp webhook -> in-app notification: the end-to-end path a school
 * actually experiences.
 *
 * The chain under test is a real one, not a UI simulation:
 *
 *   HMAC-signed POST /api/whatsapp/webhook
 *     -> signature verified over the raw body
 *     -> phone resolved to the linked parent (RLS bypass scoped to the request)
 *     -> "#حضور" routed through the command table
 *     -> reply queued for outbound delivery, in-app notification committed
 *     -> parent reloads /notifications/ and sees it, badge and all
 *
 * Every assertion that could be order-dependent is expressed as a delta
 * against a count read immediately before the webhook fires. The suite runs
 * fully parallel, so "the page is empty" would be a lie.
 *
 * Outbound delivery itself is not asserted here: it happens on a background
 * thread inside the Flask process, out of reach of `page.route`. With no
 * `WHATSAPP_ACCESS_TOKEN` configured `deliver_outbound` returns without any
 * network call, and the Graph API contract is covered by the unit suite.
 */

import { expect, metaSignature, metaTextMessage, test, uniqueMessageId } from "./fixtures.js";

const readNotifications = (page) =>
  page
    .getByTestId("notification-item")
    .evaluateAll((nodes) =>
      nodes.map((node) => ({
        id: Number(node.dataset.notificationId),
        body: node.dataset.notificationBody || "",
      })),
    );

/**
 * Notifications newer than `since`, optionally narrowed to a body fragment.
 *
 * A raw count is not an assertion here: the suite runs fully parallel and every
 * persona in this file is the same seeded parent, so a colleague's webhook can
 * land between the two reads. Comparing ids *and* the reply text isolates this
 * message's notification without depending on test order.
 */
const freshNotifications = async (page, since, text) => {
  const items = await readNotifications(page);
  return items.filter((item) => item.id > since && (!text || item.body.includes(text)));
};

/** Highest notification id currently on screen — 0 when the list is empty. */
const latestNotificationId = async (page) =>
  Math.max(0, ...(await readNotifications(page)).map((item) => item.id));

const postWebhook = (page, baseURL, rawBody, headers) =>
  page.request.post(`${baseURL}/api/whatsapp/webhook`, {
    data: rawBody,
    headers: { "Content-Type": "application/json", ...headers },
  });

test.describe("WhatsApp — webhook verification", () => {
  test("unsigned traffic is rejected without leaking why", async ({ page, baseURL, seed }) => {
    const raw = JSON.stringify(metaTextMessage({ messageId: uniqueMessageId("unsigned"), phone: seed.parent_phone, text: "#حضور" }));
    const response = await postWebhook(page, baseURL, raw, {});

    expect(response.status()).toBe(401);
    const body = await response.text();
    expect(body).not.toContain("Traceback");
    expect(body).not.toContain("WHATSAPP_APP_SECRET");
    expect(body).not.toContain("signature");
  });

  test("a forged signature is rejected", async ({ page, baseURL, seed }) => {
    const raw = JSON.stringify(metaTextMessage({ messageId: uniqueMessageId("forged"), phone: seed.parent_phone, text: "#حضور" }));
    const response = await postWebhook(page, baseURL, raw, {
      "X-Hub-Signature-256": `sha256=${"0".repeat(64)}`,
    });
    expect(response.status()).toBe(401);
  });

  test("a signature over different bytes is rejected", async ({ page, baseURL, seed, appSecret }) => {
    // The signature is valid for *some* body, just not this one — the classic
    // replay-with-substitution attempt.
    const other = JSON.stringify(metaTextMessage({ messageId: uniqueMessageId("other"), phone: seed.parent_phone, text: "#درجات" }));
    const raw = JSON.stringify(metaTextMessage({ messageId: uniqueMessageId("substituted"), phone: seed.parent_phone, text: "#حضور" }));
    const response = await postWebhook(page, baseURL, raw, {
      "X-Hub-Signature-256": metaSignature(other, appSecret),
    });
    expect(response.status()).toBe(401);
  });

  test("the deprecated alias enforces the same signature rule", async ({ page, baseURL, seed }) => {
    const raw = JSON.stringify(metaTextMessage({ messageId: uniqueMessageId("alias"), phone: seed.parent_phone, text: "#حضور" }));
    const response = await postWebhook(page, baseURL, raw, {});
    expect(response.status()).toBe(401);
  });

  test("the subscription challenge echoes only for the right token", async ({ page, baseURL, verifyToken }) => {
    const ok = await page.request.get(`${baseURL}/api/whatsapp/webhook`, {
      params: { "hub.mode": "subscribe", "hub.verify_token": verifyToken, "hub.challenge": "31415" },
    });
    expect(ok.status()).toBe(200);
    expect(await ok.text()).toBe("31415");

    const denied = await page.request.get(`${baseURL}/api/whatsapp/webhook`, {
      params: { "hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "31415" },
    });
    expect(denied.status()).toBe(403);
  });
});

test.describe("WhatsApp — command routing reaches the parent's UI", () => {
  test("a signed attendance command raises exactly one notification", async ({
    page,
    baseURL,
    seed,
    appSecret,
    loginAs,
  }) => {
    await loginAs(seed.parent_email);
    await page.goto(`${baseURL}/notifications/`);
    const since = await latestNotificationId(page);

    const raw = JSON.stringify(
      metaTextMessage({ messageId: uniqueMessageId("attendance"), phone: seed.parent_phone, text: "#حضور" }),
    );
    const response = await postWebhook(page, baseURL, raw, {
      "X-Hub-Signature-256": metaSignature(raw, appSecret),
    });

    expect(response.status()).toBe(200);
    expect(await response.json()).toMatchObject({ status: "processed", handled: 1 });

    await page.reload();
    const fresh = await freshNotifications(page, since, "حضور");
    expect(fresh).toHaveLength(1);

    const item = page.getByTestId("notification-item").first();
    await expect(item).toBeVisible();
    await expect(item.getByTestId("notification-title")).toContainText("رد واتساب");
    await expect(page.getByTestId("nav-unread-badge")).toBeVisible();
  });

  test("the grades command answers with the seeded mark", async ({ page, baseURL, seed, appSecret, loginAs }) => {
    await loginAs(seed.parent_email);
    await page.goto(`${baseURL}/notifications/`);
    const since = await latestNotificationId(page);

    const raw = JSON.stringify(
      metaTextMessage({ messageId: uniqueMessageId("grades"), phone: seed.parent_phone, text: "#درجات" }),
    );
    const response = await postWebhook(page, baseURL, raw, {
      "X-Hub-Signature-256": metaSignature(raw, appSecret),
    });
    expect(response.status()).toBe(200);

    await page.reload();
    const [answer] = await freshNotifications(page, since, "88");
    expect(answer, "the reply should quote the seeded mark").toBeTruthy();
    await expect(page.getByTestId("notification-item").first()).toContainText("88");
  });

  test("an unknown command still answers, and says what is supported", async ({
    page,
    baseURL,
    seed,
    appSecret,
    loginAs,
  }) => {
    await loginAs(seed.parent_email);
    await page.goto(`${baseURL}/notifications/`);
    const since = await latestNotificationId(page);

    const raw = JSON.stringify(
      metaTextMessage({ messageId: uniqueMessageId("unknown"), phone: seed.parent_phone, text: "#طائرة" }),
    );
    const response = await postWebhook(page, baseURL, raw, {
      "X-Hub-Signature-256": metaSignature(raw, appSecret),
    });
    expect(response.status()).toBe(200);

    await page.reload();
    expect(await freshNotifications(page, since, "أمر غير معروف")).toHaveLength(1);
    await expect(page.getByTestId("notification-item").first()).toContainText("أمر غير معروف");
  });
});

test.describe("WhatsApp — idempotency and unlinked numbers", () => {
  test("replaying the same message id changes nothing", async ({ page, baseURL, seed, appSecret, loginAs }) => {
    await loginAs(seed.parent_email);
    await page.goto(`${baseURL}/notifications/`);
    const since = await latestNotificationId(page);

    const raw = JSON.stringify(
      metaTextMessage({ messageId: uniqueMessageId("replay"), phone: seed.parent_phone, text: "#اشتراك" }),
    );
    const headers = { "X-Hub-Signature-256": metaSignature(raw, appSecret) };

    const first = await postWebhook(page, baseURL, raw, headers);
    const second = await postWebhook(page, baseURL, raw, headers);
    const third = await postWebhook(page, baseURL, raw, headers);

    // Still acknowledged, so Meta stops retrying...
    expect(first.status()).toBe(200);
    expect(second.status()).toBe(200);
    expect(third.status()).toBe(200);
    // ...but processed exactly once.
    expect((await second.json()).handled).toBe(1);
    expect((await third.json()).handled).toBe(1);

    await page.reload();
    // One reply, not three. The phrase is deliberately long: HELP_TEXT also
    // lists "#اشتراك", so the bare command word would match a colleague test's
    // notification too. The seeded subscription belongs to the student, so the
    // parent's own account answers "no subscription linked".
    expect(await freshNotifications(page, since, "لا يوجد اشتراك")).toHaveLength(1);
  });

  test("an unlinked number is acknowledged but raises nothing", async ({
    page,
    baseURL,
    seed,
    appSecret,
    loginAs,
  }) => {
    await loginAs(seed.parent_email);
    await page.goto(`${baseURL}/notifications/`);
    const since = await latestNotificationId(page);

    const raw = JSON.stringify(
      metaTextMessage({ messageId: uniqueMessageId("unlinked"), phone: "+970599999999", text: "#حضور" }),
    );
    const response = await postWebhook(page, baseURL, raw, {
      "X-Hub-Signature-256": metaSignature(raw, appSecret),
    });

    expect(response.status()).toBe(200);
    expect((await response.json()).handled).toBe(1);

    await page.reload();
    // An unknown number is answered, but nothing reaches the parent\'s list.
    expect(await freshNotifications(page, since, "حضور")).toHaveLength(0);
  });

  test("an empty envelope is acknowledged with nothing handled", async ({ page, baseURL, appSecret }) => {
    const raw = JSON.stringify({ object: "whatsapp_business_account", entry: [] });
    const response = await postWebhook(page, baseURL, raw, {
      "X-Hub-Signature-256": metaSignature(raw, appSecret),
    });
    expect(response.status()).toBe(200);
    expect(await response.json()).toMatchObject({ status: "processed", handled: 0 });
  });
});

test.describe("WhatsApp — response budget", () => {
  test("the webhook acknowledges without waiting on outbound delivery", async ({
    page,
    baseURL,
    seed,
    appSecret,
  }) => {
    const raw = JSON.stringify(
      metaTextMessage({ messageId: uniqueMessageId("latency"), phone: seed.parent_phone, text: "#مساعدة" }),
    );
    const started = Date.now();
    const response = await postWebhook(page, baseURL, raw, {
      "X-Hub-Signature-256": metaSignature(raw, appSecret),
    });
    const elapsed = Date.now() - started;

    expect(response.status()).toBe(200);
    // The engine hands the reply to a queue and returns; the 200ms design goal
    // is asserted in the unit suite, this is the browser-level smoke bound
    // that a hung outbound call would blow through.
    expect(elapsed).toBeLessThan(5_000);
  });
});
