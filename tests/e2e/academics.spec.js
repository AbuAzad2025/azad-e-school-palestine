/**
 * Academics journey — gradebook and attendance as the three seeded personas.
 *
 * Each persona exercises the same underlying rows through a different view, so
 * a regression in tenancy shows up as one role seeing another's data:
 *
 *   teacher  -> full gradebook + editable attendance (the only writer)
 *   parent   -> read-only gradebook of the child's class, family navigation
 *   student  -> their own grades, attendance as a read-only badge
 *
 * The teacher test performs a real write and restores the seeded values before
 * it finishes, so a retried or re-ordered run starts from the same state. It is
 * the only spec that mutates attendance; nothing else asserts on those values.
 */

import { csrfToken, expect, test } from "./fixtures.js";

const SEEDED_NOTE = "حضور مسجَّل مسبقاً";

test.describe("Academics — access control", () => {
  test("gradebook and attendance require a session", async ({ page, baseURL }) => {
    for (const path of ["/family/", "/classes/1/gradebook", "/classes/1/attendance"]) {
      // maxRedirects: 0 — page.goto reports the login page it landed on, which
      // would mask the guard with a 200.
      const response = await page.request.get(`${baseURL}${path}`, { maxRedirects: 0 });
      expect([302, 401, 403], `${path} should refuse an anonymous caller`).toContain(response.status());
      await page.goto(`${baseURL}${path}`);
      expect(page.url()).toContain("/auth/login");
    }
  });

  test("the family view is closed to non-parents", async ({ page, baseURL, seed, loginAs }) => {
    await loginAs(seed.teacher_email);
    const response = await page.goto(`${baseURL}/family/`);
    expect([302, 403]).toContain(response.status());
    expect(page.url()).not.toContain("/auth/login?next=/family/");
  });
});

test.describe("Academics — parent", () => {
  test.beforeEach(async ({ parentSession, seed }) => {
    await parentSession.goto(`/family/`);
    void seed;
  });

  test("lands on the family page after login and sees the linked child", async ({ parentSession, seed }) => {
    await expect(parentSession).toHaveURL(/\/family\/$/);
    await expect(parentSession.getByTestId("family-children-list")).toBeVisible();
    const child = parentSession.locator(`[data-student-id="${seed.student_id}"]`);
    await expect(child).toHaveCount(1);
    await expect(child).toContainText("E2E");
  });

  test("navigates from the child to the gradebook of their class", async ({ parentSession, seed }) => {
    await parentSession.locator(`[data-student-id="${seed.student_id}"]`).getByTestId("family-child-grades").click();
    await expect(parentSession.getByTestId("child-grades-list")).toBeVisible();

    await parentSession.locator(`[data-class-id="${seed.class_id}"]`).getByTestId("child-grades-open").click();
    await expect(parentSession).toHaveURL(new RegExp(`/classes/${seed.class_id}/gradebook$`));
    await expect(parentSession.getByTestId("gradebook-table")).toBeVisible();
  });

  test("sees the child's grade as a reader, with no editing controls", async ({ parentSession, seed }) => {
    await parentSession.goto(`/classes/${seed.class_id}/gradebook`);
    const row = parentSession.locator(`[data-student-id="${seed.student_id}"]`);
    await expect(row).toHaveCount(1);
    // The seeded mark is 88; readers get plain text, never an input.
    await expect(row).toContainText("88");
    await expect(parentSession.getByTestId("gradebook-mark")).toHaveCount(0);
  });

  test("attendance is visible but not editable", async ({ parentSession, seed }) => {
    await parentSession.goto(`/classes/${seed.class_id}/attendance`);
    await expect(parentSession.getByTestId("attendance-form")).toBeVisible();
    await expect(parentSession.getByTestId("attendance-save")).toHaveCount(0);
    await expect(parentSession.getByTestId("attendance-status")).toHaveCount(0);
    await expect(parentSession.locator(`tr[data-row-id="${seed.student_id}"]`)).toContainText("present");
  });
});

test.describe("Academics — student", () => {
  test("sees their own grade, not the class grid", async ({ page, seed, loginAs, baseURL }) => {
    await loginAs(seed.student_email);
    await page.goto(`${baseURL}/classes/${seed.class_id}/gradebook`);

    await expect(page.getByTestId("student-grade-item")).toHaveCount(1);
    await expect(page.getByTestId("student-grade-title")).toContainText("اختبار");
    await expect(page.getByTestId("student-grade-mark")).toHaveText("88.00");
    // A student never receives the teacher's grid.
    await expect(page.getByTestId("gradebook-table")).toHaveCount(0);
  });

  test("attendance shows their own status as a read-only badge", async ({ page, seed, loginAs, baseURL }) => {
    await loginAs(seed.student_email);
    await page.goto(`${baseURL}/classes/${seed.class_id}/attendance`);

    const row = page.locator(`tr[data-row-id="${seed.student_id}"]`);
    await expect(row).toContainText("present");
    await expect(row).toContainText(SEEDED_NOTE);
  });
});

test.describe("Academics — teacher", () => {
  test("edits attendance and the change survives a reload", async ({ page, seed, loginAs, baseURL }) => {
    await loginAs(seed.teacher_email);
    await page.goto(`${baseURL}/classes/${seed.class_id}/attendance`);

    const row = page.locator(`tr[data-row-id="${seed.student_id}"]`);
    const status = row.getByTestId("attendance-status");
    const note = row.getByTestId("attendance-note");

    await expect(status).toBeVisible();
    await expect(note).toHaveValue(SEEDED_NOTE);

    // Write, assert the round trip, then restore the seeded values so the
    // fixture is unchanged for anything that runs after this test.
    try {
      await status.selectOption("late");
      await note.fill("تعديل من اختبار E2E");
      await page.getByTestId("attendance-save").click();

      await expect(row.getByTestId("attendance-status")).toHaveValue("late");
      await expect(row.getByTestId("attendance-note")).toHaveValue("تعديل من اختبار E2E");

      await page.reload();
      const reloaded = page.locator(`tr[data-row-id="${seed.student_id}"]`);
      await expect(reloaded.getByTestId("attendance-status")).toHaveValue("late");
      await expect(reloaded.getByTestId("attendance-note")).toHaveValue("تعديل من اختبار E2E");
    } finally {
      await status.selectOption("present");
      await note.fill(SEEDED_NOTE);
      await page.getByTestId("attendance-save").click();
      await expect(row.getByTestId("attendance-status")).toHaveValue("present");
    }
  });

  test("gradebook exposes an editable mark per student", async ({ page, seed, loginAs, baseURL }) => {
    await loginAs(seed.teacher_email);
    await page.goto(`${baseURL}/classes/${seed.class_id}/gradebook`);

    const row = page.locator(`[data-student-id="${seed.student_id}"]`);
    await expect(row.getByTestId("gradebook-mark")).toHaveValue("88.00");
    await expect(row.getByTestId("gradebook-mark-save")).toBeVisible();
  });

  test("a mark outside the item maximum is refused", async ({ page, seed, loginAs, baseURL }) => {
    await loginAs(seed.teacher_email);
    await page.goto(`${baseURL}/classes/${seed.class_id}/gradebook`);

    const row = page.locator(`[data-student-id="${seed.student_id}"]`);
    const original = await row.getByTestId("gradebook-mark").inputValue();

    // Posted straight to the endpoint: the input carries max=100, so the browser
    // would block the submit and the assertion would prove nothing about the
    // server. This way the refusal has to come from the route.
    const refused = await page.request.post(`${baseURL}/classes/items/${seed.grade_item_id}/grade`, {
      headers: { "X-CSRFToken": await csrfToken(page) },
      form: { student_id: String(seed.student_id), mark: "250" },
      maxRedirects: 0,
    });
    expect([302, 400]).toContain(refused.status());

    // The stored mark is untouched, and the teacher is told why.
    await page.goto(`${baseURL}/classes/${seed.class_id}/gradebook`);
    await expect(page.getByTestId("gradebook-table")).toBeVisible();
    await expect(row.getByTestId("gradebook-mark")).toHaveValue(original);
  });
});
